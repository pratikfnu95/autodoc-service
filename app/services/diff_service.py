import base64
from urllib.parse import quote
import requests

from app.config import Config


def _github_headers() -> dict:
    headers = {"Accept": "application/vnd.github+json"}
    if Config.GITHUB_TOKEN:
        headers["Authorization"] = f"Bearer {Config.GITHUB_TOKEN}"
    return headers


def _fetch_file_content(owner: str, repo: str, path: str, ref: str) -> str:
    encoded_path = quote(path)
    url = f"https://api.github.com/repos/{owner}/{repo}/contents/{encoded_path}"
    params = {"ref": ref}
    try:
        response = requests.get(url, headers=_github_headers(), params=params, timeout=30)
    except requests.RequestException:
        return ""

    if response.status_code != 200:
        return ""

    data = response.json()
    content = data.get("content", "")
    encoding = data.get("encoding", "")
    if encoding != "base64" or not content:
        return ""

    try:
        return base64.b64decode(content).decode("utf-8", errors="replace")
    except (ValueError, UnicodeDecodeError):
        return ""


def _get_compare_files(owner: str, repo: str, base_sha: str, head_sha: str) -> dict:
    url = f"https://api.github.com/repos/{owner}/{repo}/compare/{base_sha}...{head_sha}"
    try:
        response = requests.get(url, headers=_github_headers(), timeout=30)
    except requests.RequestException:
        return {}

    if response.status_code != 200:
        return {}

    data = response.json()
    files = data.get("files", [])
    file_map = {}
    for file_info in files:
        filename = file_info.get("filename", "")
        if not filename.endswith(".py"):
            continue
        file_map[filename] = {
            "status": file_info.get("status", "modified"),
            "patch": file_info.get("patch", ""),
        }
    return file_map


def _list_python_files_at_ref(owner: str, repo: str, ref: str) -> list[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}"
    params = {"recursive": "1"}
    try:
        response = requests.get(url, headers=_github_headers(), params=params, timeout=30)
    except requests.RequestException:
        return []

    if response.status_code != 200:
        return []

    data = response.json()
    tree = data.get("tree", [])
    paths = []
    for entry in tree:
        if entry.get("type") != "blob":
            continue
        path = entry.get("path", "")
        if path.endswith(".py"):
            paths.append(path)
    return paths


def get_repository_python_files(owner: str, repo: str, base_sha: str, head_sha: str) -> list[dict]:
    compare_map = _get_compare_files(owner=owner, repo=repo, base_sha=base_sha, head_sha=head_sha)
    current_files = _list_python_files_at_ref(owner=owner, repo=repo, ref=head_sha)
    results = []

    for filename in sorted(current_files):
        change_info = compare_map.get(filename, {})
        status = change_info.get("status", "unchanged")
        content = _fetch_file_content(
            owner=owner,
            repo=repo,
            path=filename,
            ref=head_sha,
        )
        if not content.strip() and status != "removed":
            continue

        script_name = filename.rsplit("/", 1)[-1].rsplit(".py", 1)[0]
        results.append(
            {
                "path": filename,
                "script_name": script_name,
                "status": status,
                "patch": change_info.get("patch", ""),
                "content": content,
            }
        )

    for filename, change_info in compare_map.items():
        if change_info.get("status") != "removed":
            continue
        script_name = filename.rsplit("/", 1)[-1].rsplit(".py", 1)[0]
        results.append(
            {
                "path": filename,
                "script_name": script_name,
                "status": "removed",
                "patch": change_info.get("patch", ""),
                "content": "",
            }
        )

    return results
