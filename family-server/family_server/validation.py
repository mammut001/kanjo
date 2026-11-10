"""Validation and privacy backstop checks for incoming family reports."""

from datetime import datetime
import json
from typing import Any, Optional, Set

FORBIDDEN_SUBSTRINGS = ("/Users/", "/home/", "@")
FORBIDDEN_KEYS = frozenset({"sessions_detail", "account", "paths", "title", "sessions"})


def _contains_forbidden_keys(obj: Any, forbidden: Set[str]) -> Optional[str]:
    """Recursively search for any forbidden dictionary keys."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in forbidden:
                return str(k)
            found = _contains_forbidden_keys(v, forbidden)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _contains_forbidden_keys(item, forbidden)
            if found:
                return found
    return None


def check_privacy_backstop(raw_body_bytes: bytes) -> Optional[str]:
    """Check for privacy leaks in raw body. Returns error message if forbidden, None if clean.
    
    Checks:
    - Raw substring presence of "/Users/", "/home/", "@"
    - Keys named: sessions_detail, account, paths, title, sessions
    """
    try:
        body_text = raw_body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return "Unable to decode request body as UTF-8"

    for pattern in FORBIDDEN_SUBSTRINGS:
        if pattern in body_text:
            return f"Privacy violation: raw payload contains forbidden pattern '{pattern}'"

    # Also parse JSON to inspect dict keys recursively
    try:
        data = json.loads(body_text)
        found_key = _contains_forbidden_keys(data, FORBIDDEN_KEYS)
        if found_key:
            return f"Privacy violation: payload contains forbidden key '{found_key}'"
    except Exception:
        # If it's not valid JSON, payload validation will reject it shortly
        pass

    return None


def _validate_period(period_data: Any, context: str) -> Optional[str]:
    """Validate a Period structure per CONTRACT.md section 12."""
    if not isinstance(period_data, dict):
        return f"{context} must be an object"

    for key in ("period", "tokens", "cost_usd"):
        if key not in period_data:
            return f"{context} missing required key '{key}'"

    if not isinstance(period_data["period"], str):
        return f"{context}.period must be a string"

    if not isinstance(period_data["tokens"], dict):
        return f"{context}.tokens must be an object"

    if not isinstance(period_data["cost_usd"], (int, float)):
        return f"{context}.cost_usd must be a number"

    return None


def validate_report_payload(data: Any) -> Optional[str]:
    """Validate the schema and types of kanjo-family-report payload.
    Returns error message if invalid, None if valid.
    """
    if not isinstance(data, dict):
        return "Payload must be a JSON object"

    # Required top-level keys
    required_keys = ("kind", "schema_version", "generated_at", "timezone", "generated_by", "summary")
    for key in required_keys:
        if key not in data:
            return f"Missing required top-level key '{key}'"

    if data["kind"] != "kanjo-family-report":
        return f"Invalid kind: expected 'kanjo-family-report', got '{data.get('kind')}'"

    if not isinstance(data["schema_version"], int):
        return "schema_version must be an integer"

    if not isinstance(data["generated_at"], str):
        return "generated_at must be an ISO timestamp string"

    # Validate ISO timestamp format
    try:
        gen_at = data["generated_at"]
        if gen_at.endswith("Z"):
            gen_at = gen_at[:-1] + "+00:00"
        datetime.fromisoformat(gen_at)
    except Exception:
        return "generated_at is not a valid ISO timestamp"

    if not isinstance(data["timezone"], str) or not data["timezone"].strip():
        return "timezone must be a non-empty string"

    if not isinstance(data["generated_by"], str) or not data["generated_by"].strip():
        return "generated_by must be a non-empty string"

    # summary validation
    summary = data.get("summary")
    if not isinstance(summary, dict):
        return "summary must be an object"

    for summary_key in ("all_time", "months", "weeks", "days"):
        if summary_key not in summary:
            return f"summary missing required key '{summary_key}'"

    err = _validate_period(summary["all_time"], "summary.all_time")
    if err:
        return err

    for list_key in ("months", "weeks", "days"):
        if not isinstance(summary[list_key], list):
            return f"summary.{list_key} must be an array"

    # Validate a sample of days if present
    for idx, day_period in enumerate(summary["days"][:5]):
        err = _validate_period(day_period, f"summary.days[{idx}]")
        if err:
            return err

    # quota_windows validation
    if "quota_windows" in data and not isinstance(data["quota_windows"], dict):
        return "quota_windows must be an object"

    # plans validation
    if "plans" in data and not isinstance(data["plans"], dict):
        return "plans must be an object"

    # member_label validation
    if "member_label" in data and data["member_label"] is not None and not isinstance(data["member_label"], str):
        return "member_label must be a string or null"

    return None
