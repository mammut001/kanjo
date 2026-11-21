"""Validation and privacy backstop checks for incoming family reports."""

from datetime import datetime
import json
import math
import re
from typing import Any, Dict, List, Optional, Set, Tuple

FORBIDDEN_SUBSTRINGS = ("/Users/", "/home/")
# Home folders without the leading slash, with backslashes, or as Windows drive paths.
FORBIDDEN_PATH_REGEX = re.compile(r'(?:^|["/\\])(?:Users|home)[/\\]|\b[A-Za-z]:\\')
FORBIDDEN_KEYS = frozenset({"sessions_detail", "account", "paths", "title", "sessions"})
EMAIL_REGEX = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
DEVICE_ID_REGEX = re.compile(r"[0-9a-f]{16}")
VALID_DEVICE_OS = frozenset({"macos", "linux", "windows"})


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
            if FORBIDDEN_PATH_REGEX.search(k_str):
                return "Privacy violation: key contains a local path"
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
        if FORBIDDEN_PATH_REGEX.search(obj):
            return "Privacy violation: value contains a local path"
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


def _validate_values(value: Any, depth: int = 0) -> Optional[str]:
    """Bound untrusted values before any dashboard code consumes them."""
    if depth > 40:
        return "Payload nesting is too deep"
    if isinstance(value, str):
        if len(value) > 4096:
            return "Payload string is too long"
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if value < 0 or value > 10 ** 15 or (isinstance(value, float) and not math.isfinite(value)):
            return "Payload contains an invalid number"
    elif isinstance(value, dict):
        for key, item in value.items():
            err = _validate_values(key, depth + 1) or _validate_values(item, depth + 1)
            if err:
                return err
    elif isinstance(value, list):
        for item in value:
            err = _validate_values(item, depth + 1)
            if err:
                return err
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

    if isinstance(period_data["cost_usd"], bool) or not isinstance(period_data["cost_usd"], (int, float)):
        return f"{context}.cost_usd must be a number"

    for key in ("start", "first_day", "last_day"):
        if key in period_data and period_data[key] is not None and not isinstance(period_data[key], str):
            return f"{context}.{key} must be a string or null"

    def valid_numbers(obj):
        if not isinstance(obj, dict):
            return False
        for key, value in obj.items():
            if key == "tokens":
                if not valid_numbers(value):
                    return False
            elif key in ("input", "output", "cache_read", "cache_write", "total", "tokens_total", "cost_usd"):
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return False
        return True

    if not valid_numbers(period_data):
        return f"{context} contains invalid numeric fields"
    for key in ("by_provider", "by_agent", "top_models", "models_used"):
        if key in period_data and not isinstance(period_data[key], list):
            return f"{context}.{key} must be an array"
    for provider in period_data.get("by_provider", []):
        if not valid_numbers(provider) or not isinstance(provider.get("models", []), list):
            return f"{context}.by_provider contains an invalid provider"
        if any(not valid_numbers(model) for model in provider.get("models", [])):
            return f"{context}.by_provider contains invalid models"
    for key in ("by_agent", "top_models"):
        if any(not valid_numbers(item) for item in period_data.get(key, [])):
            return f"{context}.{key} contains invalid entries"
    if any(not isinstance(model, str) for model in period_data.get("models_used", [])):
        return f"{context}.models_used must contain strings"
    for key, fields in (("by_provider", ("provider", "label")),
                        ("by_agent", ("agent", "label")),
                        ("top_models", ("model", "provider"))):
        for item in period_data.get(key, []):
            if any(field in item and not isinstance(item[field], str) for field in fields):
                return f"{context}.{key} contains invalid strings"
            if key == "by_provider":
                for model in item.get("models", []):
                    if "model" in model and not isinstance(model["model"], str):
                        return f"{context}.by_provider contains an invalid model name"
    return None


def validate_report_payload(data: Any) -> Optional[str]:
    """Validate the schema and types of kanjo-family-report payload.
    Returns error message if invalid, None if valid.
    """
    if not isinstance(data, dict):
        return "Payload must be a JSON object"

    err = _validate_values(data)
    if err:
        return err

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

    for list_key in ("months", "weeks", "days"):
        for idx, period in enumerate(summary[list_key]):
            err = _validate_period(period, f"summary.{list_key}[{idx}]")
            if err:
                return err

    # quota_windows validation
    if "quota_windows" in data and not isinstance(data["quota_windows"], dict):
        return "quota_windows must be an object"

    # plans validation
    if "plans" in data and not isinstance(data["plans"], dict):
        return "plans must be an object"

    if "cost_note" in data and not isinstance(data["cost_note"], str):
        return "cost_note must be a string"
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in data.get("plans", {}).items()):
        return "plans must map strings to strings"
    for agent, quota in data.get("quota_windows", {}).items():
        if not isinstance(agent, str) or not isinstance(quota, dict):
            return "quota_windows must map strings to objects"
        for key in ("weekly_resets_at", "five_hour_resets_at", "source"):
            if key in quota and quota[key] is not None and not isinstance(quota[key], str):
                return f"quota_windows.{agent}.{key} must be a string or null"
        for key in ("weekly_used_percent", "five_hour_used_percent", "weekly_window_hours", "five_hour_window_hours"):
            value = quota.get(key)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                return f"quota_windows.{agent}.{key} must be a number or null"
        if "extra_windows" in quota:
            windows = quota["extra_windows"]
            if not isinstance(windows, list):
                return f"quota_windows.{agent}.extra_windows must be an array"
            for window in windows:
                if not isinstance(window, dict):
                    return f"quota_windows.{agent}.extra_windows must contain objects"
                for key in ("id", "label", "resets_at"):
                    if key in window and window[key] is not None and not isinstance(window[key], str):
                        return f"quota_windows.{agent}.extra_windows.{key} must be a string or null"
                value = window.get("used_percent")
                if value is not None and (isinstance(value, bool) or not isinstance(value, (int, float))):
                    return f"quota_windows.{agent}.extra_windows.used_percent must be a number or null"

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

    # device validation (optional)
    if "device" in data and data["device"] is not None:
        dev = data["device"]
        if not isinstance(dev, dict):
            return "device must be an object"
        dev_id = dev.get("id")
        if not isinstance(dev_id, str) or not DEVICE_ID_REGEX.fullmatch(dev_id):
            return "device.id must be 16 lowercase hexadecimal characters"
        dev_name = dev.get("name")
        if (
            not isinstance(dev_name, str)
            or not dev_name.strip()
            or len(dev_name) > 40
            or not dev_name.isprintable()
        ):
            return "device.name must be 1 to 40 printable characters"
        if not isinstance(dev.get("os"), str) or dev.get("os") not in VALID_DEVICE_OS:
            return "device.os must be one of 'macos', 'linux', 'windows'"

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
