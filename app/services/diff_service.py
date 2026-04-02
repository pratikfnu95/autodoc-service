import base64
import logging
import re
from urllib.parse import quote
import requests

from app.config import Config

logger = logging.getLogger(__name__)


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
        logger.warning("github_compare_failed base=%s head=%s status=%s", base_sha, head_sha, response.status_code)
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
    logger.info("github_compare_parsed base=%s head=%s python_changed=%s", base_sha, head_sha, len(file_map))
    return file_map


def _list_python_files_at_ref(owner: str, repo: str, ref: str) -> list[str]:
    url = f"https://api.github.com/repos/{owner}/{repo}/git/trees/{ref}"
    params = {"recursive": "1"}
    try:
        response = requests.get(url, headers=_github_headers(), params=params, timeout=30)
    except requests.RequestException:
        return []

    if response.status_code != 200:
        logger.warning("github_tree_failed ref=%s status=%s", ref, response.status_code)
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
    logger.info("github_tree_parsed ref=%s python_total=%s", ref, len(paths))
    return paths


def _extract_imported_modules(content: str) -> set[str]:
    modules = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        from_match = re.match(r"^from\s+([A-Za-z0-9_\.]+|\.+[A-Za-z0-9_\.]*)\s+import\s+", line)
        if from_match:
            modules.add(from_match.group(1))
            continue

        import_match = re.match(r"^import\s+(.+)$", line)
        if not import_match:
            continue

        for part in import_match.group(1).split(","):
            name = part.strip().split(" as ", 1)[0].strip()
            if name:
                modules.add(name)

    return modules


def _extract_run_references(content: str) -> set[str]:
    refs = set()
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        # Support plain `%run ./x` and Databricks-exported `# MAGIC %run ./x`.
        magic_line = line
        if line.lower().startswith("# magic"):
            magic_line = line[len("# magic") :].strip()

        run_match = re.match(r"^%run\s+([^\s#]+)", magic_line, flags=re.IGNORECASE)
        if not run_match:
            continue
        refs.add(run_match.group(1).strip().strip("'\""))

    return refs


def _module_candidate_paths(module: str, current_path: str) -> list[str]:
    candidates = []
    current_dir_parts = current_path.rsplit("/", 1)[0].split("/") if "/" in current_path else []

    if module.startswith("."):
        dots = len(module) - len(module.lstrip("."))
        stripped = module[dots:]
        up_levels = max(dots - 1, 0)
        if up_levels and up_levels <= len(current_dir_parts):
            base_parts = current_dir_parts[:-up_levels]
        else:
            base_parts = current_dir_parts
        if stripped:
            base_parts = base_parts + stripped.split(".")
        rel_path = "/".join(base_parts)
        if rel_path:
            candidates.append(f"{rel_path}.py")
            candidates.append(f"{rel_path}/__init__.py")
        return candidates

    abs_path = module.replace(".", "/")
    candidates.append(f"{abs_path}.py")
    candidates.append(f"{abs_path}/__init__.py")
    if module.startswith("app."):
        trimmed = module[len("app.") :].replace(".", "/")
        candidates.append(f"{trimmed}.py")
        candidates.append(f"{trimmed}/__init__.py")
    else:
        candidates.append(f"app/{abs_path}.py")
        candidates.append(f"app/{abs_path}/__init__.py")
    return candidates


def _run_ref_candidate_paths(run_ref: str, current_path: str) -> list[str]:
    ref = (run_ref or "").strip()
    if not ref:
        return []

    current_dir = current_path.rsplit("/", 1)[0] if "/" in current_path else ""
    candidates = []

    def _with_py(path: str) -> list[str]:
        path = path.strip("/")
        if not path:
            return []
        if path.endswith(".py"):
            return [path]
        return [path, f"{path}.py"]

    if ref.startswith("./"):
        rel = ref[2:]
        base = f"{current_dir}/{rel}" if current_dir else rel
        candidates.extend(_with_py(base))
    elif ref.startswith("../"):
        up_count = 0
        temp = ref
        while temp.startswith("../"):
            up_count += 1
            temp = temp[3:]
        current_parts = current_dir.split("/") if current_dir else []
        base_parts = current_parts[:-up_count] if up_count <= len(current_parts) else []
        base = "/".join(base_parts + ([temp] if temp else []))
        candidates.extend(_with_py(base))
    else:
        candidates.extend(_with_py(ref))
        if not ref.startswith("app/"):
            candidates.extend(_with_py(f"app/{ref}"))

    return [path for path in candidates if path]


def _resolve_related_python_files(current_path: str, content: str, all_paths: list[str]) -> list[str]:
    path_set = set(all_paths)
    basenames = {path.rsplit("/", 1)[-1]: path for path in all_paths}
    related = []
    seen = set()

    for module in sorted(_extract_imported_modules(content)):
        resolved = None
        for candidate in _module_candidate_paths(module, current_path):
            if candidate in path_set:
                resolved = candidate
                break

        if not resolved:
            module_tail = module.lstrip(".").split(".")[-1]
            if module_tail:
                resolved = basenames.get(f"{module_tail}.py")

        if resolved and resolved != current_path and resolved not in seen:
            related.append(resolved)
            seen.add(resolved)

    for run_ref in sorted(_extract_run_references(content)):
        resolved = None
        for candidate in _run_ref_candidate_paths(run_ref, current_path):
            if candidate in path_set:
                resolved = candidate
                break

        if not resolved:
            run_tail = run_ref.strip("./").split("/")[-1]
            if run_tail:
                resolved = basenames.get(run_tail if run_tail.endswith(".py") else f"{run_tail}.py")

        if resolved and resolved != current_path and resolved not in seen:
            related.append(resolved)
            seen.add(resolved)

    logger.info("related_files_detected path=%s related=%s", current_path, related)
    return related


def get_repository_python_files(owner: str, repo: str, base_sha: str, head_sha: str) -> list[dict]:
    compare_map = _get_compare_files(owner=owner, repo=repo, base_sha=base_sha, head_sha=head_sha)
    current_files = _list_python_files_at_ref(owner=owner, repo=repo, ref=head_sha)
    logger.info(
        "repo_files_start repo=%s/%s base=%s head=%s compare_map=%s current_files=%s",
        owner,
        repo,
        base_sha,
        head_sha,
        len(compare_map),
        len(current_files),
    )
    results = []
    file_contents = {}

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

        file_contents[filename] = content

    for filename in sorted(file_contents):
        change_info = compare_map.get(filename, {})
        script_name = filename.rsplit("/", 1)[-1].rsplit(".py", 1)[0]
        related_paths = _resolve_related_python_files(
            current_path=filename,
            content=file_contents[filename],
            all_paths=sorted(file_contents.keys()),
        )

        related_files = [
            {"path": path, "content": file_contents.get(path, "")[:20000]}
            for path in related_paths[:8]
            if file_contents.get(path, "").strip()
        ]

        results.append(
            {
                "path": filename,
                "script_name": script_name,
                "status": change_info.get("status", "unchanged"),
                "patch": change_info.get("patch", ""),
                "content": file_contents[filename],
                "related_files": related_files,
            }
        )
        logger.info(
            "file_change path=%s status=%s content_len=%s patch_len=%s related_count=%s",
            filename,
            change_info.get("status", "unchanged"),
            len(file_contents[filename]),
            len(change_info.get("patch", "")),
            len(related_files),
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
                "related_files": [],
            }
        )
        logger.info("file_change path=%s status=removed", filename)

    logger.info("repo_files_done total=%s", len(results))
    return results
