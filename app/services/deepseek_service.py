import requests
from app.config import Config


def generate_script_summary(file_change: dict, context: dict) -> str:
    if not Config.DEEPSEEK_API_KEY:
        return "[DeepSeek disabled] Set DEEPSEEK_API_KEY to generate AI summary."

    is_new_file = file_change.get("status") == "added"
    is_bootstrap = file_change.get("status") == "unchanged"
    action_text = "new script added" if is_new_file else "existing script updated"
    if is_bootstrap:
        action_text = "script documentation sync"
    prompt = (
        "You are generating enterprise engineering documentation for Confluence.\n"
        "Return ONLY valid HTML snippet (no markdown fences) using these tags only: "
        "h3, h4, p, ul, li, table, thead, tbody, tr, th, td, code, strong.\n"
        "Use this structure:\n"
        "- <h3>Purpose</h3>\n"
        "- <h3>High-Level Flow</h3>\n"
        "- <h3>Functions and Return Values</h3> as an HTML table with columns: Function, Inputs, Return Value, Notes\n"
        "- <h3>Input/Output Behavior</h3>\n"
        "- <h3>Error Handling and Edge Cases</h3>\n"
        "- <h3>Recent Change Summary</h3>\n"
        "- <h3>Risks / Follow-ups</h3>\n"
        "Be concrete and technical. Mention exact function names and return behavior.\n\n"
        f"Repository: {context.get('repo_full_name')}\n"
        f"Branch: {context.get('ref')}\n"
        f"Commit Range: {context.get('before')} -> {context.get('after')}\n\n"
        f"File Path: {file_change.get('path')}\n"
        f"Change Type: {action_text}\n\n"
        f"Current File Content:\n{file_change.get('content', '')[:120000]}\n\n"
        f"Patch (if available):\n{file_change.get('patch', '')[:20000]}"
    )

    url = f"{Config.DEEPSEEK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You are a precise software documentation assistant."},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.2,
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return f"DeepSeek network error: {exc}"

    if response.status_code != 200:
        return f"DeepSeek request failed: {response.status_code} {response.text}"

    try:
        data = response.json()
    except ValueError:
        return "DeepSeek request failed: invalid JSON response"

    return data.get("choices", [{}])[0].get("message", {}).get("content", "No summary returned.")
