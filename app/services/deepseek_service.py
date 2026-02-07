import requests
from app.config import Config


def generate_summary(diff_text: str, context: dict) -> str:
    if not Config.DEEPSEEK_API_KEY:
        return "[DeepSeek disabled] Set DEEPSEEK_API_KEY to generate AI summary."

    prompt = (
        "You are a senior engineer writing release notes. "
        "Summarize this code diff in concise bullet points with: "
        "1) what changed, 2) impact, 3) possible risks.\n\n"
        f"Repository: {context.get('repo_full_name')}\n"
        f"Branch: {context.get('ref')}\n"
        f"Commit Range: {context.get('before')} -> {context.get('after')}\n\n"
        f"Diff:\n{diff_text[:120000]}"
    )

    url = f"{Config.DEEPSEEK_API_BASE}/chat/completions"
    headers = {
        "Authorization": f"Bearer {Config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": Config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": "You are a concise technical summarizer."},
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
