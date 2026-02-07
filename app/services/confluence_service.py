import base64
import datetime as dt
import html
import requests

from app.config import Config


def _auth_headers() -> dict:
    auth_token = base64.b64encode(
        f"{Config.CONFLUENCE_EMAIL}:{Config.CONFLUENCE_API_TOKEN}".encode("utf-8")
    ).decode("utf-8")
    return {
        "Authorization": f"Basic {auth_token}",
        "Content-Type": "application/json",
    }


def _find_existing_page(title: str, headers: dict) -> dict | None:
    url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content"
    params = {
        "title": title,
        "spaceKey": Config.CONFLUENCE_SPACE_KEY,
        "expand": "space",
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    data = response.json()
    results = data.get("results", [])
    if not results:
        return None
    return results[0]


def _build_page_body(summary_html: str, context: dict, file_change: dict) -> str:
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    safe_code = html.escape(file_change.get("content", ""))
    safe_change_type = html.escape(file_change.get("status", "unknown"))
    safe_file_path = html.escape(file_change.get("path", ""))
    safe_repo = html.escape(context.get("repo_full_name", ""))
    safe_ref = html.escape(context.get("ref", ""))
    safe_base = html.escape(context.get("before", ""))
    safe_head = html.escape(context.get("after", ""))

    if not summary_html.strip().startswith("<"):
        summary_html = f"<p>{html.escape(summary_html)}</p>"

    return (
        "<h2><strong>📘 Script Documentation</strong></h2>"
        "<table><tbody>"
        f"<tr><th><strong>Repository</strong></th><td>{safe_repo}</td></tr>"
        f"<tr><th><strong>Script Path</strong></th><td><code>{safe_file_path}</code></td></tr>"
        f"<tr><th><strong>Branch</strong></th><td>{safe_ref}</td></tr>"
        f"<tr><th><strong>Commit Range</strong></th><td><code>{safe_base}</code> → <code>{safe_head}</code></td></tr>"
        f"<tr><th><strong>Change Type</strong></th><td>{safe_change_type}</td></tr>"
        f"<tr><th><strong>Last Updated</strong></th><td>{timestamp}</td></tr>"
        "</tbody></table>"
        "<h2><strong>🧠 AI Technical Summary</strong></h2>"
        f"{summary_html}"
        "<h2><strong>💻 Current Source Snapshot</strong></h2>"
        f"<pre>{safe_code}</pre>"
    )


def _create_page(title: str, body: str, headers: dict) -> dict:
    url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content"
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

    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if response.status_code not in (200, 201):
        return {
            "status": "failed",
            "status_code": response.status_code,
            "body": response.text,
        }
    data = response.json()
    return {"status": "published", "page_id": data.get("id"), "title": data.get("title")}


def _update_page(existing: dict, title: str, body: str, headers: dict) -> dict:
    page_id = existing.get("id")
    if not page_id:
        return {"status": "failed", "reason": "existing page id missing"}

    get_url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
    params = {"expand": "version"}
    try:
        get_response = requests.get(get_url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        return {"status": "failed", "reason": f"version fetch error: {exc}"}

    if get_response.status_code != 200:
        return {"status": "failed", "status_code": get_response.status_code, "body": get_response.text}

    page_data = get_response.json()
    current_version = page_data.get("version", {}).get("number", 1)

    update_payload = {
        "id": str(page_id),
        "type": "page",
        "title": title,
        "space": {"key": Config.CONFLUENCE_SPACE_KEY},
        "version": {"number": current_version + 1},
        "body": {
            "storage": {
                "value": body,
                "representation": "storage",
            }
        },
    }

    update_url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
    try:
        update_response = requests.put(update_url, headers=headers, json=update_payload, timeout=30)
    except requests.RequestException as exc:
        return {"status": "failed", "reason": f"update error: {exc}"}

    if update_response.status_code != 200:
        return {"status": "failed", "status_code": update_response.status_code, "body": update_response.text}

    return {"status": "updated", "page_id": page_id, "title": title}


def _delete_page(existing: dict, headers: dict) -> dict:
    page_id = existing.get("id")
    if not page_id:
        return {"status": "failed", "reason": "existing page id missing"}

    delete_url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
    params = {"status": "current"}
    try:
        delete_response = requests.delete(delete_url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        return {"status": "failed", "reason": f"delete error: {exc}"}

    if delete_response.status_code not in (200, 204):
        return {"status": "failed", "status_code": delete_response.status_code, "body": delete_response.text}

    return {"status": "deleted", "page_id": page_id, "title": existing.get("title")}


def get_script_page(script_name: str) -> dict | None:
    if not (Config.CONFLUENCE_BASE_URL and Config.CONFLUENCE_EMAIL and Config.CONFLUENCE_API_TOKEN and Config.CONFLUENCE_SPACE_KEY):
        return None
    return _find_existing_page(title=script_name, headers=_auth_headers())


def upsert_script_page(summary: str, context: dict, file_change: dict) -> dict:
    if not (Config.CONFLUENCE_BASE_URL and Config.CONFLUENCE_EMAIL and Config.CONFLUENCE_API_TOKEN and Config.CONFLUENCE_SPACE_KEY):
        return {"status": "skipped", "reason": "Confluence config missing"}

    title = file_change.get("script_name", "script")
    headers = _auth_headers()
    existing = _find_existing_page(title=title, headers=headers)

    if file_change.get("status") == "removed":
        if not existing:
            return {"status": "skipped", "reason": "page not found for removed script"}
        return _delete_page(existing=existing, headers=headers)

    body = _build_page_body(summary_html=summary, context=context, file_change=file_change)
    if existing:
        return _update_page(existing=existing, title=title, body=body, headers=headers)

    return _create_page(title=title, body=body, headers=headers)
