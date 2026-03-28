import base64
import datetime as dt
import html
import os
import re
import requests

from app.config import Config

AI_SUMMARY_HEADER = "<h2><strong>Technical Summary</strong></h2>"
SECTION_ORDER = [
    "Purpose",
    "High-Level Flow",
    "Cross-File Dependencies",
    "Input/Output Behavior",
    "Source to Target Mapping",
    "Recent Change Summary",
    "Jira Story Traceability",
    "Risks / Follow-ups",
]

SECTION_ALIASES = {
    "purpose": "Purpose",
    "high-level flow": "High-Level Flow",
    "cross-file dependencies": "Cross-File Dependencies",
    "cross file dependencies": "Cross-File Dependencies",
    "input/output behavior": "Input/Output Behavior",
    "input output behavior": "Input/Output Behavior",
    "source to target mapping": "Source to Target Mapping",
    "recent change summary": "Recent Change Summary",
    "jira story traceability": "Jira Story Traceability",
    "jira traceability": "Jira Story Traceability",
    "risks / follow-ups": "Risks / Follow-ups",
    "risks/follow-ups": "Risks / Follow-ups",
}

DEFAULT_TABLE_STYLE = (
    'style="width:100%;border-collapse:collapse;background:#f5f9ff;border:1px solid #c8d9f1;"'
)
DEFAULT_TH_STYLE = (
    'style="background:#2f6ea5;color:#ffffff;border:1px solid #c8d9f1;padding:8px;text-align:left;"'
)
TABLE_STYLE_FRAGMENT = (
    "width:100%;max-width:100%;table-layout:fixed;border-collapse:collapse;"
    "background:#eef4ff;border:1px solid #9db9df;margin:10px 0;font-size:13px;line-height:1.4;"
)
TH_STYLE_FRAGMENT = (
    "background:#1f5f99;color:#ffffff;border:1px solid #9db9df;"
    "padding:8px;text-align:left;vertical-align:top;overflow-wrap:anywhere;word-break:break-word;"
)
TD_STYLE_FRAGMENT = (
    "border:1px solid #c7daf2;padding:8px;background:#ffffff;vertical-align:top;"
    "overflow-wrap:anywhere;word-break:break-word;"
)


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


def _normalize_section_name(name: str) -> str:
    compact = re.sub(r"\s+", " ", name.strip().lower())
    return SECTION_ALIASES.get(compact, name.strip())


def _split_token_words(token: str) -> list[str]:
    if not token:
        return []
    token = re.sub(r"[^A-Za-z0-9]+", " ", token).strip()
    if not token:
        return []
    token = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", token)
    token = re.sub(r"([A-Za-z])([0-9])", r"\1 \2", token)
    token = re.sub(r"([0-9])([A-Za-z])", r"\1 \2", token)
    parts = token.split()

    # Fallback splitter for single all-lowercase compound words.
    common_words = [
        "policy", "transaction", "account", "manager", "service", "config", "route",
        "summary", "source", "target", "mapping", "temp", "view", "calculator",
        "todo", "github", "confluence", "deepseek", "script", "notebook", "diff",
    ]
    if len(parts) == 1 and re.fullmatch(r"[a-z]+", parts[0] or ""):
        raw = parts[0]
        segmented = []
        i = 0
        while i < len(raw):
            match = ""
            for word in common_words:
                if raw.startswith(word, i) and len(word) > len(match):
                    match = word
            if match:
                segmented.append(match)
                i += len(match)
            else:
                segmented.append(raw[i:])
                break
        if len(segmented) > 1:
            parts = segmented

    return parts


def _humanize_script_title(file_change: dict) -> str:
    script_name = (file_change.get("script_name") or "").strip()
    path = (file_change.get("path") or "").strip()
    candidate = script_name or os.path.splitext(os.path.basename(path))[0]
    if not candidate:
        return "Script"
    words = _split_token_words(candidate.replace("_", " ").replace("-", " "))
    if not words:
        return candidate.title()
    return " ".join(word.capitalize() for word in words)


def _extract_ai_summary_from_page_body(body: str) -> str:
    if not body:
        return ""
    marker_index = body.find(AI_SUMMARY_HEADER)
    if marker_index == -1:
        return ""
    return body[marker_index + len(AI_SUMMARY_HEADER) :].strip()


def _inject_style_into_opening_tag(opening_tag: str, style_fragment: str) -> str:
    style_fragment = style_fragment.strip().rstrip(";") + ";"
    style_match_double = re.search(r'style\s*=\s*"([^"]*)"', opening_tag, flags=re.IGNORECASE)
    if style_match_double:
        current = style_match_double.group(1).strip().rstrip(";")
        merged = f"{current};{style_fragment}" if current else style_fragment
        return (
            opening_tag[: style_match_double.start(1)]
            + merged
            + opening_tag[style_match_double.end(1) :]
        )

    style_match_single = re.search(r"style\s*=\s*'([^']*)'", opening_tag, flags=re.IGNORECASE)
    if style_match_single:
        current = style_match_single.group(1).strip().rstrip(";")
        merged = f"{current};{style_fragment}" if current else style_fragment
        return (
            opening_tag[: style_match_single.start(1)]
            + merged
            + opening_tag[style_match_single.end(1) :]
        )

    return opening_tag[:-1] + f' style="{style_fragment}">'


def _inject_attr_into_opening_tag(opening_tag: str, attr_name: str, attr_value: str) -> str:
    attr_pattern = rf"\b{re.escape(attr_name)}\s*="
    if re.search(attr_pattern, opening_tag, flags=re.IGNORECASE):
        return opening_tag
    return opening_tag[:-1] + f' {attr_name}="{attr_value}">'


def _enforce_table_styles(summary_html: str) -> str:
    if not summary_html:
        return summary_html

    summary_html = re.sub(
        r"<table\b[^>]*>",
        lambda m: _inject_style_into_opening_tag(
            _inject_attr_into_opening_tag(m.group(0), "data-layout", "default"),
            TABLE_STYLE_FRAGMENT,
        ),
        summary_html,
        flags=re.IGNORECASE,
    )
    summary_html = re.sub(
        r"<th\b[^>]*>",
        lambda m: _inject_style_into_opening_tag(
            _inject_attr_into_opening_tag(m.group(0), "bgcolor", "#1f5f99"),
            TH_STYLE_FRAGMENT,
        ),
        summary_html,
        flags=re.IGNORECASE,
    )
    summary_html = re.sub(
        r"<td\b[^>]*>",
        lambda m: _inject_style_into_opening_tag(
            _inject_attr_into_opening_tag(m.group(0), "bgcolor", "#ffffff"),
            TD_STYLE_FRAGMENT,
        ),
        summary_html,
        flags=re.IGNORECASE,
    )
    return summary_html


def _split_h3_sections(summary_html: str) -> dict:
    matches = list(re.finditer(r"<h3>\s*(.*?)\s*</h3>", summary_html, flags=re.IGNORECASE | re.DOTALL))
    sections = {}
    for index, match in enumerate(matches):
        title = _normalize_section_name(html.unescape(re.sub(r"<.*?>", "", match.group(1))).strip())
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(summary_html)
        sections[title] = summary_html[start:end].strip()
    return sections


def _strip_html_tags(text: str) -> str:
    if not text:
        return ""
    without_tags = re.sub(r"<.*?>", " ", text, flags=re.DOTALL)
    return re.sub(r"\s+", " ", html.unescape(without_tags)).strip()


def _extract_table_rows(section_html: str) -> tuple[list[str], list[dict]]:
    table_match = re.search(r"<table\b.*?</table>", section_html, flags=re.IGNORECASE | re.DOTALL)
    if not table_match:
        return [], []

    table_html = table_match.group(0)
    tr_matches = re.findall(r"<tr\b.*?</tr>", table_html, flags=re.IGNORECASE | re.DOTALL)
    headers = []
    rows = []

    for tr_html in tr_matches:
        th_cells = re.findall(r"<th\b[^>]*>(.*?)</th>", tr_html, flags=re.IGNORECASE | re.DOTALL)
        td_cells = re.findall(r"<td\b[^>]*>(.*?)</td>", tr_html, flags=re.IGNORECASE | re.DOTALL)

        if th_cells and not headers:
            headers = [_strip_html_tags(cell) for cell in th_cells]
            continue

        if not td_cells:
            continue

        clean_cells = [_strip_html_tags(cell) for cell in td_cells]
        if not headers:
            headers = [f"Column {i + 1}" for i in range(len(clean_cells))]

        row = {}
        for idx, header_name in enumerate(headers):
            row[header_name] = clean_cells[idx] if idx < len(clean_cells) else ""
        rows.append(row)

    return headers, rows


def _row_value(row: dict, column_name: str) -> str:
    target = column_name.strip().lower()
    for key, value in row.items():
        if key.strip().lower() == target:
            return (value or "").strip()
    return ""


def _normalize_for_key(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", (value or "").strip().lower())
    return cleaned


def _normalize_dependency_ref(value: str) -> str:
    cleaned = _normalize_for_key(value).replace("\\", "/")
    cleaned = re.sub(r"^\./+", "", cleaned)
    cleaned = re.sub(r"^app/", "", cleaned)
    return cleaned


def _normalize_cell_value(value: str) -> str:
    return _normalize_for_key(re.sub(r"\([^)]*\)", " ", value or ""))


def _pick_preferred_text(existing: str, incoming: str) -> str:
    a = (existing or "").strip()
    b = (incoming or "").strip()
    if not a:
        return b
    if not b:
        return a
    if _normalize_cell_value(a) == _normalize_cell_value(b):
        return a
    if b.lower() in a.lower():
        return a
    if a.lower() in b.lower():
        return b
    return b if len(b) >= len(a) else a


def _combine_detail_text(existing: str, incoming: str) -> str:
    a = (existing or "").strip()
    b = (incoming or "").strip()
    if not a:
        return b
    if not b:
        return a
    if _normalize_cell_value(a) == _normalize_cell_value(b):
        return a
    if b.lower() in a.lower():
        return a
    if a.lower() in b.lower():
        return b
    return f"{a} {b}"


def _dedupe_dependency_rows_by_reference(headers: list[str], rows: list[dict]) -> list[dict]:
    if not rows:
        return rows

    ref_header = None
    for header in headers:
        if "referenced" in header.lower() or "dependency" in header.lower():
            ref_header = header
            break
    if not ref_header:
        ref_header = headers[0]

    merged_by_ref = {}
    order = []
    for row in rows:
        ref_value = (row.get(ref_header) or "").strip()
        ref_key = _normalize_dependency_ref(ref_value)
        if not ref_key:
            ref_key = _normalize_for_key(ref_value)
        if not ref_key:
            ref_key = f"__row_{len(order)}"

        if ref_key not in merged_by_ref:
            merged_by_ref[ref_key] = {header: (row.get(header) or "").strip() for header in headers}
            order.append(ref_key)
            continue

        merged_row = merged_by_ref[ref_key]
        for header in headers:
            current = (merged_row.get(header) or "").strip()
            incoming = (row.get(header) or "").strip()
            lower_header = header.lower()
            if "usage" in lower_header or "impact" in lower_header or "note" in lower_header:
                merged_row[header] = _combine_detail_text(current, incoming)
            else:
                merged_row[header] = _pick_preferred_text(current, incoming)

    return [merged_by_ref[key] for key in order]


def _merge_table_rows(existing_rows: list[dict], new_rows: list[dict], key_builder) -> list[dict]:
    merged_rows = []
    key_order = []
    key_to_row = {}

    for row in existing_rows:
        key = key_builder(row)
        if key and key not in key_to_row:
            key_order.append(key)
            key_to_row[key] = row
        elif not key:
            merged_rows.append(row)

    for row in new_rows:
        key = key_builder(row)
        if key:
            if key not in key_to_row:
                key_order.append(key)
            key_to_row[key] = row
        else:
            merged_rows.append(row)

    for key in key_order:
        merged_rows.append(key_to_row[key])
    return merged_rows


def _build_table_html(headers: list[str], rows: list[dict]) -> str:
    if not headers:
        return "<p>N/A</p>"

    thead_html = "".join(f'<th bgcolor="#1f5f99" {DEFAULT_TH_STYLE}>{html.escape(header)}</th>' for header in headers)
    body_parts = []
    for idx, row in enumerate(rows):
        row_bg = "#ffffff" if idx % 2 == 0 else "#edf4ff"
        tds = "".join(
            f'<td bgcolor="{row_bg}" style="border:1px solid #c7daf2;padding:8px;background:{row_bg};'
            f'vertical-align:top;overflow-wrap:anywhere;word-break:break-word;">'
            f"{html.escape((row.get(header) or '').strip())}</td>"
            for header in headers
        )
        body_parts.append(f"<tr>{tds}</tr>")

    return (
        f'<table data-layout="default" {DEFAULT_TABLE_STYLE}>'
        f"<thead><tr>{thead_html}</tr></thead>"
        f"<tbody>{''.join(body_parts)}</tbody>"
        "</table>"
    )


def _merge_cross_dependency_section(existing_html: str, new_html: str) -> str:
    headers_old, rows_old = _extract_table_rows(existing_html)
    headers_new, rows_new = _extract_table_rows(new_html)
    headers = headers_new or headers_old
    if not headers:
        return new_html or existing_html or "<p>N/A</p>"

    merged_rows = _merge_table_rows(
        existing_rows=rows_old,
        new_rows=rows_new,
        key_builder=lambda row: "||".join(
            [
                _normalize_dependency_ref(_row_value(row, "Referenced Script")),
                _normalize_for_key(_row_value(row, "Relation Type")),
            ]
        ).strip("|")
        or _normalize_dependency_ref(_row_value(row, "Referenced Script")),
    )
    deduped_rows = _dedupe_dependency_rows_by_reference(headers=headers, rows=merged_rows)
    return _build_table_html(headers=headers, rows=deduped_rows)


def _merge_source_target_section(existing_html: str, new_html: str) -> str:
    headers_old, rows_old = _extract_table_rows(existing_html)
    headers_new, rows_new = _extract_table_rows(new_html)
    headers = headers_new or headers_old
    if not headers:
        return new_html or existing_html or "<p>N/A</p>"

    def _mapping_key(row: dict) -> str:
        target_object = _normalize_for_key(_row_value(row, "Target Object"))
        target_field = _normalize_for_key(_row_value(row, "Target Field"))
        source_object = _normalize_for_key(_row_value(row, "Source Object"))
        primary = f"{target_object}||{target_field}".strip("|")
        if primary:
            return primary
        return f"{source_object}||{target_field}".strip("|")

    merged_rows = _merge_table_rows(existing_rows=rows_old, new_rows=rows_new, key_builder=_mapping_key)
    return _build_table_html(headers=headers, rows=merged_rows)


def _extract_recent_items(section_html: str) -> list[str]:
    if not section_html:
        return []
    items = [
        _strip_html_tags(item)
        for item in re.findall(r"<li\b[^>]*>(.*?)</li>", section_html, flags=re.IGNORECASE | re.DOTALL)
    ]
    items = [item for item in items if item]
    if items:
        return items
    fallback = _strip_html_tags(section_html)
    return [fallback] if fallback else []


def _build_recent_change_audit(
    existing_html: str,
    new_html: str,
    context: dict,
    file_change: dict,
) -> str:
    new_items = _extract_recent_items(new_html)
    latest_change = new_items[0] if new_items else "Documentation updated."
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    short_sha = (context.get("after", "") or "")[:8]
    file_path = file_change.get("path", "")
    jira_ticket = (context.get("jira_ticket_id") or "").strip().upper()
    jira_suffix = f" [Jira: {jira_ticket}]" if jira_ticket else ""
    new_entry = f"{timestamp} [{short_sha}] {file_path}: {latest_change}{jira_suffix}"

    existing_items = _extract_recent_items(existing_html)
    deduped = []
    for item in [new_entry, *existing_items]:
        if item and item not in deduped:
            deduped.append(item)

    latest_three = deduped[:3]
    li_html = "".join(f"<li>{html.escape(item)}</li>" for item in latest_three)
    return f"<ul>{li_html}</ul>"


def _extract_jira_audit_items(section_html: str) -> list[dict]:
    items = []
    if not section_html:
        return items

    for li_html in re.findall(r"<li\b[^>]*>(.*?)</li>", section_html, flags=re.IGNORECASE | re.DOTALL):
        text = _strip_html_tags(li_html)
        if not text:
            continue
        ticket_match = re.search(r"\b([A-Z][A-Z0-9]+(?:-[0-9]+|[0-9]+))\b", text)
        url_match = re.search(r"https?://\S+", text)
        items.append(
            {
                "text": text,
                "ticket": ticket_match.group(1) if ticket_match else "",
                "url": url_match.group(0) if url_match else "",
            }
        )
    return items


def _build_jira_traceability_section(existing_html: str, context: dict, file_change: dict) -> str:
    jira_ticket = (context.get("jira_ticket_id") or "").strip().upper()
    jira_url = (context.get("jira_ticket_url") or "").strip()
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    short_sha = (context.get("after", "") or "")[:8]
    file_path = file_change.get("path", "")

    existing_items = _extract_jira_audit_items(existing_html)
    merged = []

    if jira_ticket and jira_url:
        entry_text = f"{timestamp} [{short_sha}] {file_path} updated via {jira_ticket} ({jira_url})"
        merged.append({"text": entry_text, "ticket": jira_ticket, "url": jira_url})

    for item in existing_items:
        if item.get("text") and item not in merged:
            merged.append(item)

    if not merged:
        return "<p>No Jira-linked change detected from branch name in this update.</p>"

    latest = merged[: max(1, Config.JIRA_AUDIT_LIMIT)]
    li_parts = []
    for item in latest:
        text = item.get("text", "")
        ticket = item.get("ticket", "")
        url = item.get("url", "")
        if ticket and url:
            text = text.replace(f"{ticket} ({url})", "").strip()
            li_parts.append(
                f"<li>{html.escape(text)} "
                f'<a href="{html.escape(url)}"><strong>{html.escape(ticket)}</strong></a></li>'
            )
        else:
            li_parts.append(f"<li>{html.escape(text)}</li>")

    return "<ul>" + "".join(li_parts) + "</ul>"


def _merge_summary_html(existing_summary_html: str, new_summary_html: str, context: dict, file_change: dict) -> str:
    existing_sections = _split_h3_sections(existing_summary_html)
    new_sections = _split_h3_sections(new_summary_html)

    merged_parts = []
    for section_name in SECTION_ORDER:
        old_content = existing_sections.get(section_name, "").strip()
        new_content = new_sections.get(section_name, "").strip()

        if section_name == "Cross-File Dependencies":
            merged_content = _merge_cross_dependency_section(old_content, new_content)
        elif section_name == "Source to Target Mapping":
            merged_content = _merge_source_target_section(old_content, new_content)
        elif section_name == "Recent Change Summary":
            merged_content = _build_recent_change_audit(
                existing_html=old_content,
                new_html=new_content,
                context=context,
                file_change=file_change,
            )
        elif section_name == "Jira Story Traceability":
            merged_content = _build_jira_traceability_section(
                existing_html=old_content,
                context=context,
                file_change=file_change,
            )
        else:
            merged_content = new_content or old_content or "<p>N/A</p>"

        merged_parts.append(f"<h3>{section_name}</h3>{merged_content}")

    return "".join(merged_parts)


def _build_page_body(summary_html: str, context: dict, file_change: dict) -> str:
    timestamp = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    safe_change_type = html.escape(file_change.get("status", "unknown"))
    safe_file_path = html.escape(file_change.get("path", ""))
    safe_repo = html.escape(context.get("repo_full_name", ""))
    safe_ref = html.escape(context.get("ref", ""))
    safe_base = html.escape(context.get("before", ""))
    safe_head = html.escape(context.get("after", ""))

    if not summary_html.strip().startswith("<"):
        summary_html = f"<p>{html.escape(summary_html)}</p>"
    summary_html = _enforce_table_styles(summary_html)

    return (
        "<h2><strong>Script Documentation</strong></h2>"
        "<table><tbody>"
        f"<tr><th><strong>Repository</strong></th><td>{safe_repo}</td></tr>"
        f"<tr><th><strong>Script Path</strong></th><td><code>{safe_file_path}</code></td></tr>"
        f"<tr><th><strong>Branch</strong></th><td>{safe_ref}</td></tr>"
        f"<tr><th><strong>Commit Range</strong></th><td><code>{safe_base}</code> → <code>{safe_head}</code></td></tr>"
        f"<tr><th><strong>Change Type</strong></th><td>{safe_change_type}</td></tr>"
        f"<tr><th><strong>Last Updated</strong></th><td>{timestamp}</td></tr>"
        "</tbody></table>"
        "<h2><strong>Technical Summary</strong></h2>"
        f"{summary_html}"
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


def _update_page(existing: dict, title: str, summary_html: str, context: dict, file_change: dict, headers: dict) -> dict:
    page_id = existing.get("id")
    if not page_id:
        return {"status": "failed", "reason": "existing page id missing"}

    get_url = f"{Config.CONFLUENCE_BASE_URL}/rest/api/content/{page_id}"
    params = {"expand": "version,body.storage"}
    try:
        get_response = requests.get(get_url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        return {"status": "failed", "reason": f"page fetch error: {exc}"}

    if get_response.status_code != 200:
        return {"status": "failed", "status_code": get_response.status_code, "body": get_response.text}

    page_data = get_response.json()
    current_version = page_data.get("version", {}).get("number", 1)
    existing_page_body = page_data.get("body", {}).get("storage", {}).get("value", "")
    existing_summary = _extract_ai_summary_from_page_body(existing_page_body)
    merged_summary = _merge_summary_html(
        existing_summary_html=existing_summary,
        new_summary_html=summary_html,
        context=context,
        file_change=file_change,
    )
    body = _build_page_body(summary_html=merged_summary, context=context, file_change=file_change)

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

    title = _humanize_script_title(file_change)
    headers = _auth_headers()
    existing = _find_existing_page(title=title, headers=headers)

    if file_change.get("status") == "removed":
        if not existing:
            return {"status": "skipped", "reason": "page not found for removed script"}
        return _delete_page(existing=existing, headers=headers)

    if existing:
        return _update_page(
            existing=existing,
            title=title,
            summary_html=summary,
            context=context,
            file_change=file_change,
            headers=headers,
        )

    body = _build_page_body(summary_html=summary, context=context, file_change=file_change)
    return _create_page(title=title, body=body, headers=headers)
