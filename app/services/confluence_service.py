import base64
import datetime as dt
import requests

from app.config import Config


def publish_summary(summary: str, context: dict) -> dict:
    if not (Config.CONFLUENCE_BASE_URL and Config.CONFLUENCE_EMAIL and Config.CONFLUENCE_API_TOKEN and Config.CONFLUENCE_SPACE_KEY):
        return {"status": "skipped", "reason": "Confluence config missing"}

    title = f"Code Summary - {context.get('repo_full_name')} - {context.get('after', '')[:7]}"
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")

    body = (
        f"<h2>Automated Code Summary</h2>"
        f"<p><b>Repository:</b> {context.get('repo_full_name')}</p>"
        f"<p><b>Branch:</b> {context.get('ref')}</p>"
        f"<p><b>Commit Range:</b> {context.get('before')} -> {context.get('after')}</p>"
        f"<p><b>Generated At:</b> {timestamp}</p>"
        f"<h3>Summary</h3>"
        f"<pre>{summary}</pre>"
    )

    url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content"
    auth_token = base64.b64encode(
        f"{Config.CONFLUENCE_EMAIL}:{Config.CONFLUENCE_API_TOKEN}".encode("utf-8")
    ).decode("utf-8")

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": Config.CONFLUENCE_SPACE_KEY},
        "body": {
            "storage": {
                "value": body,
                "representation": "storage",
            }
        },
    }

    if Config.CONFLUENCE_PARENT_PAGE_ID:
        payload["ancestors"] = [{"id": str(Config.CONFLUENCE_PARENT_PAGE_ID)}]

    headers = {
        "Authorization": f"Basic {auth_token}",
        "Content-Type": "application/json",
    }

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code not in (200, 201):
        return {
            "status": "failed",
            "status_code": response.status_code,
            "body": response.text,
        }

    data = response.json()
    return {
        "status": "published",
        "page_id": data.get("id"),
        "title": data.get("title"),
    }
