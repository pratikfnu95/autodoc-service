import hashlib
import hmac
import json
from flask import Blueprint, request, jsonify

from app.config import Config
from app.services.github_service import extract_push_context
from app.services.diff_service import get_commit_diff_text
from app.services.deepseek_service import generate_summary
from app.services.confluence_service import publish_summary


webhook_bp = Blueprint("webhook", __name__)


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

    if not context["is_main_branch"]:
        return jsonify({"message": "ignored: not main branch"}), 200

    if not context["before"] or not context["after"]:
        return jsonify({"message": "ignored: missing commit range"}), 200

    diff_text = get_commit_diff_text(
        owner=context["owner"],
        repo=context["repo"],
        base_sha=context["before"],
        head_sha=context["after"],
    )

    if not diff_text.strip():
        return jsonify({"message": "no diff found"}), 200

    summary = generate_summary(diff_text=diff_text, context=context)
    deepseek_ok = not summary.startswith("[DeepSeek disabled]") and not summary.startswith("DeepSeek ")

    if Config.ENABLE_CONFLUENCE and deepseek_ok:
        confluence_result = publish_summary(summary=summary, context=context)
    elif not Config.ENABLE_CONFLUENCE:
        confluence_result = {"status": "skipped", "reason": "Confluence disabled (set ENABLE_CONFLUENCE=true)"}
    else:
        confluence_result = {"status": "skipped", "reason": "DeepSeek summary failed"}

    return jsonify(
        {
            "message": "processed",
            "repo": context["repo_full_name"],
            "base": context["before"],
            "head": context["after"],
            "deepseek": {
                "status": "ok" if deepseek_ok else "failed",
                "summary": summary,
            },
            "confluence": confluence_result,
        }
    ), 200
