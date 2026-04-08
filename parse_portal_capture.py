#!/usr/bin/env python3
"""Parse captured Chrome DevTools request logs for CSU portal flows."""

from __future__ import annotations

import json
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

SENSITIVE_KEYS = {
    "password",
    "user_password",
    "upass",
    "old_password",
    "new_password",
    "user_old_password",
    "user_new_password",
}


def latest_session(root: Path) -> Path:
    latest = root / ".capture_runtime" / "latest_session"
    if latest.exists():
        return Path(latest.read_text(encoding="utf-8").strip())
    raise FileNotFoundError("No capture session metadata found")


def normalize_query(url: str) -> dict[str, str]:
    query = parse_qs(urlsplit(url).query, keep_blank_values=True)
    return {key: values[-1] if values else "" for key, values in query.items()}


def redact_value(key: str, value: Any) -> Any:
    if key.lower() in SENSITIVE_KEYS and value not in ("", None):
        return "***"
    return value


def redact_mapping(mapping: dict[str, Any]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in mapping.items():
        if isinstance(value, dict):
            result[key] = redact_mapping(value)
        elif isinstance(value, list):
            result[key] = [redact_value(key, item) for item in value]
        else:
            result[key] = redact_value(key, value)
    return result


def redact_url(url: str) -> str:
    parsed = urlsplit(url)
    if not parsed.query:
        return url
    query = parse_qs(parsed.query, keep_blank_values=True)
    redacted = {
        key: [redact_value(key, item) for item in values]
        for key, values in query.items()
    }
    safe_query = urlencode(redacted, doseq=True)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, safe_query, parsed.fragment))


def redact_form_encoded(text: str) -> str:
    if not text:
        return ""
    parsed = parse_qs(text, keep_blank_values=True)
    if not parsed:
        return text
    normalized = {key: values[-1] if values else "" for key, values in parsed.items()}
    return json.dumps(redact_mapping(normalized), ensure_ascii=False)


def parse_jsonp_payload(text: str) -> Any:
    if not text:
        return None
    normalized = text.strip()
    if normalized.endswith(";"):
        normalized = normalized[:-1]
    match = re.match(r"^[A-Za-z0-9_]+\((.*)\)$", normalized, flags=re.S)
    if match:
        normalized = match.group(1)
    try:
        return json.loads(normalized)
    except json.JSONDecodeError:
        return None


def classify_request(url: str) -> str:
    parsed = urlsplit(url)
    path = parsed.path
    query = normalize_query(url)

    if path == "/a79.htm":
        return "real_portal_page"
    if path == "/eportal/":
        if query.get("c") == "ACSetting" and query.get("a") == "Login":
            return "legacy_login"
        if query.get("c") == "ACSetting" and query.get("a") == "Logout":
            return "legacy_logout"
        return "admin_entry"
    if path == "/eportal/admin/login/login":
        return "admin_login"
    if path == "/eportal/portal/page/loadConfig":
        return "load_config"
    if path == "/eportal/portal/login":
        return "portal_login"
    if path == "/eportal/portal/logout":
        return "portal_logout"
    if path == "/eportal/portal/mac/unbind":
        return "mac_unbind"
    if path == "/eportal/portal/online_list":
        return "online_list"
    if path == "/eportal/portal/perceive":
        return "perceive"
    if path == "/eportal/portal/visitor/checkUserStateByIP":
        return "visitor_state"
    return "other"


def is_interesting(classification: str) -> bool:
    return classification != "other"


def preview_body(body: str, limit: int = 1200) -> str:
    if len(body) <= limit:
        return body
    return body[:limit] + "...<truncated>"


def summarize_payload(classification: str, payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload

    payload = redact_mapping(payload)
    if classification == "load_config":
        data = payload.get("data", {})
        if not isinstance(data, dict):
            return payload
        keys = (
            "program_index",
            "page_index",
            "login_method",
            "account_suffix",
            "account_prefix",
            "register_mode",
            "ac_logout",
            "cvlan_id",
            "redirect_link",
            "reback_link",
            "ep_http_port",
            "ep_https_port",
            "check_online_method",
        )
        subset = {key: data.get(key) for key in keys if key in data}
        return {
            "code": payload.get("code"),
            "msg": payload.get("msg"),
            "data": subset,
        }
    return payload


def iter_json_records(text: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    decoder = json.JSONDecoder()
    idx = 0
    length = len(text)
    while idx < length:
        while idx < length and text[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            next_newline = text.find("\n", idx)
            if next_newline == -1:
                break
            idx = next_newline + 1
            continue
        if isinstance(obj, dict):
            records.append(obj)
        idx = end
    return records


def build_record(item: dict[str, Any]) -> dict[str, Any]:
    request = item.get("request", {})
    response = item.get("response", {})
    body = item.get("body", {})

    url = str(request.get("url", ""))
    classification = classify_request(url)
    query = redact_mapping(dict(request.get("query", {})))
    post_data = str(request.get("postData", "") or "")

    body_text = str(body.get("body", "") or "")
    payload = parse_jsonp_payload(body_text)

    result = {
        "classification": classification,
        "method": request.get("method"),
        "path": urlsplit(url).path,
        "url": redact_url(url),
        "status": response.get("status"),
        "query": query,
    }

    if post_data:
        result["postData"] = redact_form_encoded(post_data)

    request_headers = request.get("requestHeaders", {})
    if request_headers:
        result["requestHeaders"] = redact_mapping(dict(request_headers))

    if payload is not None:
        result["responsePayload"] = summarize_payload(classification, payload)
    elif body_text:
        result["responseBodyPreview"] = preview_body(body_text)

    return result


def main() -> int:
    root = Path(__file__).resolve().parent
    session = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else latest_session(root)
    request_log = session / "requests.jsonl"
    if not request_log.exists():
        print(f"Capture log not found: {request_log}", file=sys.stderr)
        return 1

    grouped: dict[str, dict[str, Any]] = defaultdict(dict)
    records = iter_json_records(request_log.read_text(encoding="utf-8", errors="replace"))
    for record in records:
        request_id = record.get("requestId")
        if not request_id:
            continue
        grouped[str(request_id)][record["event"]] = record

    interesting: list[dict[str, Any]] = []
    for item in grouped.values():
        request = item.get("request")
        if not request:
            continue
        url = str(request.get("url", ""))
        if "portal.csu.edu.cn" not in url:
            continue
        classification = classify_request(url)
        if not is_interesting(classification):
            continue
        interesting.append(build_record(item))

    order = {
        "real_portal_page": 0,
        "load_config": 1,
        "portal_login": 2,
        "portal_logout": 3,
        "mac_unbind": 4,
        "legacy_login": 5,
        "legacy_logout": 6,
        "online_list": 7,
        "perceive": 8,
        "visitor_state": 9,
        "admin_entry": 10,
        "admin_login": 11,
    }
    interesting.sort(key=lambda item: (order.get(str(item.get("classification")), 99), str(item.get("url", ""))))

    output = {
        "session": str(session),
        "record_count": len(records),
        "interesting_count": len(interesting),
        "records": interesting,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
