import time
import requests
from app.config import Config


def _related_files_context(file_change: dict) -> str:
    related_files = file_change.get("related_files", [])
    if not related_files:
        return "None"

    blocks = []
    for item in related_files[: Config.DEEPSEEK_MAX_RELATED_FILES]:
        path = item.get("path", "")
        content = item.get("content", "")
        if not path or not content:
            continue
        blocks.append(f"Related File: {path}\n{content[: Config.DEEPSEEK_RELATED_FILE_MAX_CHARS]}")

    return "\n\n".join(blocks) if blocks else "None"


def generate_script_summary(file_change: dict, context: dict) -> str:
    if not Config.DEEPSEEK_API_KEY:
        return "[DeepSeek disabled] Set DEEPSEEK_API_KEY to generate AI summary."

    is_new_file = file_change.get("status") == "added"
    is_bootstrap = file_change.get("status") == "unchanged"
    action_text = "new script added" if is_new_file else "existing script updated"
    if is_bootstrap:
        action_text = "script documentation sync"
    related_context = _related_files_context(file_change)
    prompt = (
        "You are generating enterprise engineering documentation for Confluence.\n"
        "Return ONLY valid HTML snippet (no markdown fences) using these tags only: "
        "h3, h4, p, ul, li, table, thead, tbody, tr, th, td, code, strong.\n"
        "Do NOT include full source code dumps, <pre> blocks, or complete function bodies.\n"
        "Use inline style attributes on table/th/td to apply a clean blue theme suitable for Confluence: "
        "light blue table background, darker blue header row, white header text, subtle borders, readable padding, and alternating row shading.\n"
        "Keep styling professional and lightweight (no scripts, no external CSS).\n"
        "Use this structure exactly:\n"
        "- <h3>Purpose</h3>\n"
        "- <h3>High-Level Flow</h3>\n"
        "- <h3>Cross-File Dependencies</h3> as an HTML table with columns: Referenced Script, Relation Type, Key Usage, Impact\n"
        "- <h3>Input/Output Behavior</h3>\n"
        "- <h3>Source to Target Mapping</h3> as an HTML table with columns: Source Object, Source Field/Expression, Transformation/Rule, Target Object, Target Field\n"
        "- <h3>Recent Change Summary</h3>\n"
        "- <h3>Risks / Follow-ups</h3>\n"
        "Be concrete and technical. Mention exact function names and return behavior.\n"
        "For dependency analysis, inspect the main script and all related files provided below.\n"
        "Do not duplicate rows in Cross-File Dependencies; keep one row per unique dependency and relation.\n"
        "For Risks / Follow-ups, include only issues directly supported by the provided code and patch context.\n"
        "Do not speculate, do not invent missing dependencies, and do not add generic risks.\n"
        "If no concrete risk is visible in the provided code, output exactly: <p>No concrete risks identified from the provided code.</p>\n"
        "For Source to Target Mapping, include SQL SELECT fields, dataframe/variable assignments, and final writes/outputs.\n"
        "If no mapping exists, include one row with N/A values and note why.\n\n"
        f"Repository: {context.get('repo_full_name')}\n"
        f"Branch: {context.get('ref')}\n"
        f"Commit Range: {context.get('before')} -> {context.get('after')}\n\n"
        f"File Path: {file_change.get('path')}\n"
        f"Change Type: {action_text}\n\n"
        f"Main File Content:\n{file_change.get('content', '')[: Config.DEEPSEEK_MAIN_CONTENT_MAX_CHARS]}\n\n"
        f"Related File Contents (for cross-file tracing):\n{related_context}\n\n"
        f"Patch (if available):\n{file_change.get('patch', '')[: Config.DEEPSEEK_PATCH_MAX_CHARS]}"
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

    timeout = (Config.DEEPSEEK_CONNECT_TIMEOUT_SEC, Config.DEEPSEEK_READ_TIMEOUT_SEC)
    max_attempts = max(1, Config.DEEPSEEK_MAX_RETRIES + 1)
    last_error = ""
    retryable_statuses = {429, 500, 502, 503, 504}

    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.post(url, json=payload, headers=headers, timeout=timeout)
        except requests.exceptions.ReadTimeout as exc:
            last_error = f"DeepSeek network error: read timeout after {Config.DEEPSEEK_READ_TIMEOUT_SEC}s ({exc})"
            if attempt < max_attempts:
                sleep_sec = Config.DEEPSEEK_BACKOFF_BASE_SEC * attempt
                time.sleep(sleep_sec)
                continue
            return last_error
        except requests.RequestException as exc:
            return f"DeepSeek network error: {exc}"

        if response.status_code == 200:
            try:
                data = response.json()
            except ValueError:
                return "DeepSeek request failed: invalid JSON response"
            return data.get("choices", [{}])[0].get("message", {}).get("content", "No summary returned.")

        if response.status_code in retryable_statuses and attempt < max_attempts:
            sleep_sec = Config.DEEPSEEK_BACKOFF_BASE_SEC * attempt
            time.sleep(sleep_sec)
            continue

        return f"DeepSeek request failed: {response.status_code} {response.text}"

    return last_error or "DeepSeek request failed: exhausted retries"
