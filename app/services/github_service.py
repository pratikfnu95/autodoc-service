def extract_push_context(payload: dict) -> dict:
    ref = payload.get("ref", "")
    repo = payload.get("repository", {})
    owner_data = repo.get("owner", {})

    owner = owner_data.get("name") or owner_data.get("login") or ""
    repo_name = repo.get("name", "")

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
        "head_commit_message": payload.get("head_commit", {}).get("message", ""),
    }
