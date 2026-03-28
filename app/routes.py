import hashlib
import hmac
import json
import threading
import time
import datetime as dt
from flask import Blueprint, request, jsonify

from app.config import Config
from app.services.github_service import extract_push_context
from app.services.diff_service import get_repository_python_files
from app.services.deepseek_service import generate_script_summary
from app.services.confluence_service import get_script_page, upsert_script_page


webhook_bp = Blueprint("webhook", __name__)


def _now_utc() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _log(message: str) -> None:
    print(f"[{_now_utc()}] {message}", flush=True)


def process_push_event(context: dict) -> None:
    delivery_id = context.get("delivery_id", "n/a")
    repo_name = context.get("repo_full_name", "unknown")
    webhook_start = time.perf_counter()
    try:
        _log(f"[webhook:{delivery_id}] start repo={repo_name} ref={context.get('ref')}")
        _log(
            f"[webhook:{delivery_id}] source_branch={context.get('source_branch') or 'n/a'} "
            f"jira_ticket={context.get('jira_ticket_id') or 'n/a'}"
        )
        _log(f"[webhook:{delivery_id}] scanning python files and commit diff...")
        repo_scripts = get_repository_python_files(
            owner=context["owner"],
            repo=context["repo"],
            base_sha=context["before"],
            head_sha=context["after"],
        )

        if not repo_scripts:
            total_ms = (time.perf_counter() - webhook_start) * 1000
            _log(f"[webhook:{delivery_id}] no changed python files repo={repo_name} total_ms={total_ms:.0f}")
            return

        total_scripts = len(repo_scripts)
        _log(f"[webhook:{delivery_id}] discovered_scripts={total_scripts}; starting documentation pipeline")

        for idx, file_change in enumerate(repo_scripts, start=1):
            script_start = time.perf_counter()
            script_name = file_change.get("script_name", "")
            status = file_change.get("status", "unchanged")
            _log(
                f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} status={status} "
                "step=checking_existing_page"
            )
            existing_page = get_script_page(script_name)

            if status == "unchanged" and existing_page:
                elapsed_ms = (time.perf_counter() - script_start) * 1000
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} deepseek=skipped")
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} confluence=already_synced")
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} script_ms={elapsed_ms:.0f}")
                continue

            if status == "removed":
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} step=deleting_confluence_page")
                confluence_result = upsert_script_page(summary="", context=context, file_change=file_change)
                elapsed_ms = (time.perf_counter() - script_start) * 1000
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} deepseek=skipped")
                _log(
                    f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} "
                    f"confluence={confluence_result.get('status')}"
                )
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} script_ms={elapsed_ms:.0f}")
                continue

            _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} step=deepseek_summary")
            deepseek_start = time.perf_counter()
            summary = generate_script_summary(file_change=file_change, context=context)
            deepseek_ms = (time.perf_counter() - deepseek_start) * 1000
            deepseek_ok = not summary.startswith("[DeepSeek disabled]") and not summary.startswith("DeepSeek ")
            if not deepseek_ok:
                _log(
                    f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} "
                    f"deepseek=failed deepseek_ms={deepseek_ms:.0f} error={summary[:300]}"
                )

            confluence_start = time.perf_counter()
            if Config.ENABLE_CONFLUENCE and deepseek_ok:
                _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} step=confluence_upsert")
                confluence_result = upsert_script_page(summary=summary, context=context, file_change=file_change)
            elif not Config.ENABLE_CONFLUENCE:
                confluence_result = {"status": "skipped", "reason": "Confluence disabled (set ENABLE_CONFLUENCE=true)"}
            else:
                confluence_result = {"status": "skipped", "reason": "DeepSeek summary failed"}
            confluence_ms = (time.perf_counter() - confluence_start) * 1000
            script_ms = (time.perf_counter() - script_start) * 1000

            _log(
                f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} "
                f"deepseek={'ok' if deepseek_ok else 'failed'} deepseek_ms={deepseek_ms:.0f}"
            )
            _log(
                f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} "
                f"confluence={confluence_result.get('status')} confluence_ms={confluence_ms:.0f}"
            )
            _log(f"[webhook:{delivery_id}] [{idx}/{total_scripts}] script={script_name} script_ms={script_ms:.0f}")
    except Exception as exc:
        _log(f"[webhook:{delivery_id}] processing_error={exc}")
    finally:
        total_ms = (time.perf_counter() - webhook_start) * 1000
        _log(f"[webhook:{delivery_id}] completed repo={repo_name} total_ms={total_ms:.0f}")


def is_valid_signature(raw_body: bytes, signature_header: str) -> bool:
    if Config.ALLOW_UNSIGNED_WEBHOOKS:
        return True

    if not Config.GITHUB_WEBHOOK_SECRET:
        return True

    if not signature_header or not signature_header.startswith("sha256="):
        return False

    provided = signature_header.split("=", 1)[1]
    expected = hmac.new(
        Config.GITHUB_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(provided, expected)


def parse_github_payload(raw_body: bytes) -> dict | None:
    # GitHub may send either application/json or application/x-www-form-urlencoded
    # (with the JSON under "payload").
    payload = request.get_json(silent=True)
    if isinstance(payload, dict):
        return payload

    form_payload = request.form.get("payload")
    if form_payload:
        try:
            parsed = json.loads(form_payload)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            return None

    try:
        parsed = json.loads(raw_body.decode("utf-8"))
        if isinstance(parsed, dict):
            return parsed
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None

    return None


@webhook_bp.get("/health")
def health_check():
    return jsonify({"status": "ok"})


@webhook_bp.post("/webhook/github")
def github_webhook():
    event_type = request.headers.get("X-GitHub-Event", "")
    delivery_id = request.headers.get("X-GitHub-Delivery", "")
    signature = request.headers.get("X-Hub-Signature-256", "")
    raw_body = request.get_data()

    if not is_valid_signature(raw_body, signature):
        return jsonify({"error": "invalid signature"}), 401

    if event_type != "push":
        return jsonify({"message": "ignored: not a push event"}), 200

    payload = parse_github_payload(raw_body)
    if payload is None:
        return jsonify({"error": "invalid payload"}), 400

    context = extract_push_context(payload)
    context["delivery_id"] = delivery_id

    if not context["is_main_branch"]:
        return jsonify({"message": "ignored: not main branch"}), 200

    if not context["before"] or not context["after"]:
        return jsonify({"message": "ignored: missing commit range"}), 200

    worker = threading.Thread(target=process_push_event, args=(context,), daemon=True)
    worker.start()

    return jsonify(
        {
            "message": "accepted",
            "delivery_id": delivery_id,
            "repo": context["repo_full_name"],
            "base": context["before"],
            "head": context["after"],
        }
    ), 202
