import requests
from app.config import Config


def get_commit_diff_text(owner: str, repo: str, base_sha: str, head_sha: str) -> str:
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    headers = {"Accept": "application/vnd.github.v3.diff"}
    if Config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {Config.GITHUB_TOKEN}"

    try:
        response = requests.get(url, headers=headers, timeout=30)
    except requests.RequestException:
        return ""

    if response.status_code != 200:
        return ""
    return response.text
