import hashlib
import hmac
import json
import threading
import time
from flask import Blueprint, request, jsonify

from app.config import Config
from app.services.github_service import extract_push_context
from app.services.diff_service import get_repository_python_files
from app.services.deepseek_service import generate_script_summary
from app.services.confluence_service import get_script_page, upsert_script_page


webhook_bp = Blueprint("webhook", __name__)


def _log(message: str) -> None:
    print(message, flush=True)


def _ms_to_s(ms: float) -> str:
    return f"{(ms / 1000):.2f}s"


def process_push_event(context: dict) -> None:
    repo_name = context.get("repo_full_name", "unknown")
    webhook_start = time.perf_counter()
    summary_counts = {"updated": 0, "skipped": 0, "failed": 0, "pending_review": 0, "deleted": 0}
    review_links = []
    try:
        _log("")
        _log("=== Autodoc Run Start ===")
        _log(f"Repo: {repo_name}")
        _log(f"Branch: {context.get('ref')}")
        _log(f"Source branch: {context.get('source_branch') or 'n/a'}")
        _log(f"Jira ticket: {context.get('jira_ticket_id') or 'n/a'}")
        _log("Scanning python files and commit diff...")
        repo_scripts = get_repository_python_files(
            owner=context["owner"],
            repo=context["repo"],
            base_sha=context["before"],
            head_sha=context["after"],
        )

        if not repo_scripts:
            total_ms = (time.perf_counter() - webhook_start) * 1000
            _log(f"No changed python files. Total time: {_ms_to_s(total_ms)}")
            _log("=== Autodoc Run Complete ===")
            return

        total_scripts = len(repo_scripts)
        _log(f"Discovered scripts: {total_scripts}")
        _log("Starting documentation pipeline...")

        for idx, file_change in enumerate(repo_scripts, start=1):
            script_start = time.perf_counter()
            script_name = file_change.get("script_name", "")
            status = file_change.get("status", "unchanged")
            _log(f"Processing [{idx}/{total_scripts}] {script_name} (status={status})")
            existing_page = get_script_page(script_name)

            if status == "unchanged" and existing_page:
                elapsed_ms = (time.perf_counter() - script_start) * 1000
                summary_counts["skipped"] += 1
                _log(
                    f"RESULT | script={script_name} | status=SKIPPED | reason=already_synced | time={_ms_to_s(elapsed_ms)}"
                )
                continue

            if status == "removed":
                _log(f"Running | script={script_name} | stage=deleting_confluence_page")
                confluence_result = upsert_script_page(summary="", context=context, file_change=file_change)
                elapsed_ms = (time.perf_counter() - script_start) * 1000
                result_status = (confluence_result.get("status") or "").lower()
                if result_status == "deleted":
                    summary_counts["deleted"] += 1
                    _log(f"RESULT | script={script_name} | status=DELETED | time={_ms_to_s(elapsed_ms)}")
                elif result_status == "pending_review":
                    summary_counts["pending_review"] += 1
                    review_url = confluence_result.get("review_url", "")
                    if review_url:
                        review_links.append({"script": script_name, "url": review_url})
                    _log(
                        f"RESULT | script={script_name} | status=PENDING_REVIEW | reason=delete_request | "
                        f"time={_ms_to_s(elapsed_ms)}"
                    )
                elif result_status == "skipped":
                    summary_counts["skipped"] += 1
                    _log(
                        f"RESULT | script={script_name} | status=SKIPPED | "
                        f"reason={confluence_result.get('reason', 'n/a')} | time={_ms_to_s(elapsed_ms)}"
                    )
                else:
                    summary_counts["failed"] += 1
                    _log(
                        f"RESULT | script={script_name} | status=FAILED | "
                        f"reason={confluence_result.get('reason', result_status or 'delete_failed')} | "
                        f"time={_ms_to_s(elapsed_ms)}"
                    )
                continue

            _log(f"Running | script={script_name} | stage=summarizing")
            deepseek_start = time.perf_counter()
            summary = generate_script_summary(file_change=file_change, context=context)
            deepseek_ms = (time.perf_counter() - deepseek_start) * 1000
            deepseek_ok = not summary.startswith("[DeepSeek disabled]") and not summary.startswith("DeepSeek ")

            confluence_start = time.perf_counter()
            if Config.ENABLE_CONFLUENCE and deepseek_ok:
                _log(f"Running | script={script_name} | stage=confluence_publish")
                confluence_result = upsert_script_page(summary=summary, context=context, file_change=file_change)
            elif not Config.ENABLE_CONFLUENCE:
                confluence_result = {"status": "skipped", "reason": "Confluence disabled (set ENABLE_CONFLUENCE=true)"}
            else:
                confluence_result = {"status": "skipped", "reason": "DeepSeek summary failed"}
            confluence_ms = (time.perf_counter() - confluence_start) * 1000
            script_ms = (time.perf_counter() - script_start) * 1000

            if not deepseek_ok:
                summary_counts["failed"] += 1
                _log(
                    f"RESULT | script={script_name} | status=FAILED | reason=deepseek_error | "
                    f"deepseek={_ms_to_s(deepseek_ms)} | total={_ms_to_s(script_ms)}"
                )
                continue

            result_status = (confluence_result.get("status") or "").lower()
            if result_status == "pending_review":
                summary_counts["pending_review"] += 1
                review_url = confluence_result.get("review_url", "")
                if review_url:
                    review_links.append({"script": script_name, "url": review_url})
                _log(
                    f"RESULT | script={script_name} | status=PENDING_REVIEW | "
                    f"deepseek={_ms_to_s(deepseek_ms)} | review_draft={_ms_to_s(confluence_ms)} | total={_ms_to_s(script_ms)}"
                )
            elif result_status in ("updated", "published"):
                summary_counts["updated"] += 1
                _log(
                    f"RESULT | script={script_name} | status=UPDATED | "
                    f"deepseek={_ms_to_s(deepseek_ms)} | publish={_ms_to_s(confluence_ms)} | total={_ms_to_s(script_ms)}"
                )
            elif result_status == "skipped":
                summary_counts["skipped"] += 1
                _log(
                    f"RESULT | script={script_name} | status=SKIPPED | "
                    f"reason={confluence_result.get('reason', 'n/a')} | total={_ms_to_s(script_ms)}"
                )
            else:
                summary_counts["failed"] += 1
                _log(
                    f"RESULT | script={script_name} | status=FAILED | "
                    f"reason={confluence_result.get('reason', result_status or 'unknown')} | total={_ms_to_s(script_ms)}"
                )
    except Exception as exc:
        summary_counts["failed"] += 1
        _log(f"RUN ERROR | {exc}")
    finally:
        total_ms = (time.perf_counter() - webhook_start) * 1000
        if review_links:
            _log("")
            _log("Review documents:")
            for item in review_links:
                _log(f"- {item['script']}: {item['url']}")
        _log("")
        _log(
            "RUN SUMMARY | "
            f"pending_review={summary_counts['pending_review']} | "
            f"updated={summary_counts['updated']} | "
            f"deleted={summary_counts['deleted']} | "
            f"skipped={summary_counts['skipped']} | "
            f"failed={summary_counts['failed']} | "
            f"total_time={_ms_to_s(total_ms)}"
        )
        _log("=== Autodoc Run Complete ===")


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
