import re

from app.config import Config


def _extract_merged_branch_name(head_commit_message: str) -> str:
    if not head_commit_message:
        return ""

    # Example: "Merge pull request #123 from user/PAN123-feature"
    from_match = re.search(r"\bfrom\s+([^\s]+)", head_commit_message, flags=re.IGNORECASE)
    if from_match:
        branch_ref = from_match.group(1).strip()
        if "/" in branch_ref:
            return branch_ref.rsplit("/", 1)[-1]
        return branch_ref

    # Example: "Merge branch 'PAN123-feature' into main"
    branch_match = re.search(r"\bbranch\s+['\"]([^'\"]+)['\"]", head_commit_message, flags=re.IGNORECASE)
    if branch_match:
        branch_ref = branch_match.group(1).strip()
        if "/" in branch_ref:
            return branch_ref.rsplit("/", 1)[-1]
        return branch_ref

    return ""


def _extract_jira_ticket_from_branch(branch_name: str) -> str:
    if not branch_name:
        return ""
    # Generic ticket pattern: letters + optional separator + digits (case-insensitive), e.g. PAN123 / PAN-123
    match = re.search(r"\b([A-Za-z][A-Za-z0-9]+(?:[-_][0-9]+|[0-9]+))\b", branch_name)
    if not match:
        return ""
    ticket = match.group(1).upper().replace("_", "-")
    return ticket


def extract_push_context(payload: dict) -> dict:
    ref = payload.get("ref", "")
    repo = payload.get("repository", {})
    owner_data = repo.get("owner", {})

    owner = owner_data.get("name") or owner_data.get("login") or ""
    repo_name = repo.get("name", "")
    head_commit_message = payload.get("head_commit", {}).get("message", "")
    source_branch = _extract_merged_branch_name(head_commit_message)
    jira_ticket_id = _extract_jira_ticket_from_branch(source_branch)
    jira_ticket_url = f"{Config.JIRA_BASE_URL.rstrip('/')}/browse/{jira_ticket_id}" if jira_ticket_id else ""

    return {
        "is_main_branch": ref == "refs/heads/main",
        "ref": ref,
        "before": payload.get("before", ""),
        "after": payload.get("after", ""),
        "owner": owner,
        "repo": repo_name,
        "repo_full_name": repo.get("full_name", ""),
        "pusher": payload.get("pusher", {}).get("name", ""),
        "compare_url": payload.get("compare", ""),
        "head_commit_message": head_commit_message,
        "source_branch": source_branch,
        "jira_ticket_id": jira_ticket_id,
        "jira_ticket_url": jira_ticket_url,
    }
