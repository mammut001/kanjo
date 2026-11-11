"""Validation and privacy backstop checks for incoming family reports."""

from datetime import datetime
import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

FORBIDDEN_SUBSTRINGS = ("/Users/", "/home/")
FORBIDDEN_KEYS = frozenset({"sessions_detail", "account", "paths", "title", "sessions"})
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def _check_privacy_violations(obj: Any) -> Optional[str]:
    """Recursively search for forbidden keys, email patterns in keys/values, or forbidden substrings."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            k_str = str(k)
            if k_str in FORBIDDEN_KEYS:
                return f"Privacy violation: payload contains forbidden key '{k_str}'"
            if EMAIL_REGEX.search(k_str):
                return f"Privacy violation: payload contains email pattern in key '{k_str}'"
            for pattern in FORBIDDEN_SUBSTRINGS:
                if pattern in k_str:
                    return f"Privacy violation: key contains forbidden pattern '{pattern}'"
            found = _check_privacy_violations(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _check_privacy_violations(item)
            if found:
                return found
    elif isinstance(obj, str):
        if EMAIL_REGEX.search(obj):
            return "Privacy violation: payload contains email pattern in value"
        for pattern in FORBIDDEN_SUBSTRINGS:
            if pattern in obj:
                return f"Privacy violation: value contains forbidden pattern '{pattern}'"
    return None


def check_privacy_backstop(raw_body_bytes: bytes) -> Optional[str]:
    r"""Check for privacy leaks in raw body. Returns error message if forbidden, None if clean.
    
    Checks:
    - Raw substring presence of "/Users/", "/home/"
    - Email regex pattern ([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}) anywhere in string values or keys
    - Keys named: sessions_detail, account, paths, title, sessions
    """
    try:
        body_text = raw_body_bytes.decode("utf-8", errors="replace")
    except Exception:
        return "Unable to decode request body as UTF-8"

    for pattern in FORBIDDEN_SUBSTRINGS:
        if pattern in body_text:
            return f"Privacy violation: raw payload contains forbidden pattern '{pattern}'"

    # Parse JSON to inspect dict keys and string values recursively
    try:
        data = json.loads(body_text)
        found_violation = _check_privacy_violations(data)
        if found_violation:
            return found_violation
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

    # scope validation
    if "scope" in data and data["scope"] is not None:
        if not isinstance(data["scope"], dict):
            return "scope must be an object"
        scope = data["scope"]
        if "agents" in scope:
            agents = scope["agents"]
            if not isinstance(agents, list):
                return "scope.agents must be a list"
            for a in agents:
                if not isinstance(a, str) or len(a) > 64:
                    return "scope.agents must contain short strings"
        if "since" in scope and scope["since"] is not None:
            if not isinstance(scope["since"], str) or len(scope["since"]) > 64:
                return "scope.since must be a string or null"

    return None


_HOSTNAME_REGEX = re.compile(
    r"^(?:(?:[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?\.)+[a-zA-Z]{2,}|localhost)$"
)


def validate_auth_domain(auth_domain: str) -> bool:
    """Validate that authDomain is a bare hostname to avoid header injection."""
    if not isinstance(auth_domain, str):
        return False
    clean = auth_domain.strip()
    if not clean or len(clean) > 253:
        return False
    if any(c in clean for c in ("\r", "\n", ";", " ", "\t", "/", ":", "'", '"', "\\")):
        return False
    return bool(_HOSTNAME_REGEX.match(clean))


def validate_serve_env(
    public_origin: Optional[str] = None,
    firebase_config_raw: Optional[str] = None,
    admin_emails: Optional[str] = None,
) -> Tuple[List[str], dict]:
    """Validate required environment variables for serve command.

    Returns (errors, parsed_firebase_config).
    """
    errors: List[str] = []
    firebase_config: Dict[str, Any] = {}

    # 1. FAMILY_PUBLIC_ORIGIN
    if not public_origin or not public_origin.strip():
        errors.append("Missing required environment variable: FAMILY_PUBLIC_ORIGIN (e.g. https://usage.example.com)")
    else:
        origin_clean = public_origin.strip()
        if not (origin_clean.startswith("https://") or origin_clean.startswith("http://")):
            errors.append(f"Invalid FAMILY_PUBLIC_ORIGIN: must start with https:// (or http:// for local development), got: {origin_clean}")

    # 2. FIREBASE_WEB_CONFIG_JSON
    if not firebase_config_raw or not firebase_config_raw.strip():
        errors.append("Missing required environment variable: FIREBASE_WEB_CONFIG_JSON")
    else:
        try:
            parsed = json.loads(firebase_config_raw.strip())
            if not isinstance(parsed, dict):
                errors.append("Invalid FIREBASE_WEB_CONFIG_JSON: must be a JSON object")
            else:
                firebase_config = parsed
                for field in ("apiKey", "authDomain", "projectId"):
                    val = parsed.get(field)
                    if not val or not isinstance(val, str) or not val.strip():
                        errors.append(f"Invalid FIREBASE_WEB_CONFIG_JSON: missing or empty required field '{field}'")

                auth_dom = parsed.get("authDomain")
                if auth_dom and isinstance(auth_dom, str) and auth_dom.strip():
                    if not validate_auth_domain(auth_dom):
                        errors.append(f"Invalid FIREBASE_WEB_CONFIG_JSON: 'authDomain' must be a valid bare hostname, got: {auth_dom}")
        except Exception as e:
            errors.append(f"Invalid FIREBASE_WEB_CONFIG_JSON: must be valid JSON ({e})")

    # 3. FAMILY_ADMIN_EMAILS
    if not admin_emails or not admin_emails.strip():
        errors.append("Missing required environment variable: FAMILY_ADMIN_EMAILS (comma-separated list of admin emails)")
    else:
        emails = {e.strip().lower() for e in admin_emails.split(",") if e.strip()}
        if not emails:
            errors.append("Invalid FAMILY_ADMIN_EMAILS: must contain at least one valid email address")

    return errors, firebase_config
