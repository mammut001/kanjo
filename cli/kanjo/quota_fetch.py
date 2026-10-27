"""Provider quota live fetchers (independent of Tokei).

Fetches quota directly from providers using user's local credentials.
Security rules:
1. NEVER log, print, or write tokens/secrets to disk.
2. Credentials kept in memory only; sent only to provider's HTTPS API
   (or 127.0.0.1 for Antigravity's local language server).
3. 10s timeout, never raise (return None on any error).
4. Results cached in ~/.local/share/kanjo/quota_cache.json with 5-minute TTL,
   storing only public window/percent/reset information (mode 0600).
5. KANJO_NO_NETWORK=1 disables all outbound requests.
6. KANJO_QUOTA_DEBUG=1 prints only provider name + failure category to stderr.
"""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

CACHE_VERSION = 1
CACHE_TTL = 300  # 5 minutes
REQUEST_TIMEOUT = 10
MAX_RESPONSE_BYTES = 256 * 1024


def is_network_disabled() -> bool:
    val = os.environ.get("KANJO_NO_NETWORK", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def quota_cache_path() -> str:
    from .ledger import data_dir
    return os.path.join(data_dir(), "quota_cache.json")


def _debug_log(provider: str, category: str) -> None:
    if os.environ.get("KANJO_QUOTA_DEBUG") == "1":
        sys.stderr.write(f"quota_debug: {provider} -> {category}\n")


def _pct(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return round(min(max(float(value), 0.0), 100.0), 1)


def _percentage(value) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    val = float(value)
    if not math.isfinite(val) or val < 0:
        return None
    if 0 < val <= 1.0:
        val = val * 100.0
    return _pct(val)


def _iso_utc(ts: Optional[float]) -> Optional[str]:
    if ts is None or not math.isfinite(ts):
        return None
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text: Optional[str]) -> Optional[float]:
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (ValueError, TypeError):
        return None


# -----------------------------------------------------------------------------
# Cache management
# -----------------------------------------------------------------------------

def load_quota_cache() -> Optional[dict]:
    path = quota_cache_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and data.get("version") == CACHE_VERSION:
            return data
    except (OSError, ValueError):
        pass
    return None


def save_quota_cache(data: dict) -> None:
    path = quota_cache_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = "%s.%d.%s.tmp" % (path, os.getpid(), uuid.uuid4().hex[:8])
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
            f.write("\n")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass


def get_cached_plan(agent: str) -> Optional[str]:
    cache = load_quota_cache()
    if not cache:
        return None
    provider_data = (cache.get("providers") or {}).get(agent)
    if isinstance(provider_data, dict):
        plan = provider_data.get("plan")
        if isinstance(plan, str) and plan.strip():
            return plan.strip()
    return None


# -----------------------------------------------------------------------------
# 1. Antigravity (Local Language Server on 127.0.0.1)
# -----------------------------------------------------------------------------

def _find_antigravity_processes() -> List[dict]:
    """Find local running Antigravity Language Server processes and their CSRF tokens."""
    # 1. Environment overrides
    env_token = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
    env_addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS")
    if env_token:
        port = None
        if env_addr and ":" in env_addr:
            try:
                port = int(env_addr.split(":")[-1])
            except ValueError:
                pass
        return [{"pid": 0, "csrf_token": env_token, "port": port}]

    # 2. Inspect running processes via /bin/ps
    try:
        out = subprocess.run(
            ["/bin/ps", "-ax", "-o", "pid=,command="],
            capture_output=True, text=True, timeout=3, check=False
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []

    procs = []
    for line in out.splitlines():
        line = line.strip()
        m = re.match(r"^(\d+)\s+(.+)$", line)
        if not m:
            continue
        pid, cmd = int(m.group(1)), m.group(2)
        lower = cmd.lower()
        if "language_server" not in lower and "language-server" not in lower:
            continue
        if "antigravity" not in lower and "gemini" not in lower and "codeium" not in lower:
            continue

        csrf_match = re.search(r"--csrf_token(?:=|\s+)([^\s]+)", cmd, re.I)
        port_match = re.search(r"--extension_server_port(?:=|\s+)(\d+)", cmd, re.I)
        csrf = csrf_match.group(1) if csrf_match else ""
        port = int(port_match.group(1)) if port_match else None
        if csrf or port:
            procs.append({"pid": pid, "csrf_token": csrf, "port": port})
    return procs


def _antigravity_ports(pid: int, known_port: Optional[int]) -> List[int]:
    ports = [known_port] if known_port else []
    if pid > 0:
        for lsof in ("/usr/sbin/lsof", "/usr/bin/lsof"):
            if os.path.isfile(lsof) and os.access(lsof, os.X_OK):
                try:
                    res = subprocess.run(
                        [lsof, "-nP", "-iTCP", "-sTCP:LISTEN", "-a", "-p", str(pid)],
                        capture_output=True, text=True, timeout=2, check=False
                    )
                    found = [int(v) for v in re.findall(r":(\d+)\s+\(LISTEN\)", res.stdout)]
                    for p in found:
                        if p not in ports:
                            ports.append(p)
                except Exception:
                    pass
                break
    return ports


def fetch_antigravity_quota(now: float, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    """Contact local Antigravity Language Server on 127.0.0.1 for quota summary and user status."""
    if is_network_disabled():
        return None
    processes = _find_antigravity_processes()
    if not processes:
        _debug_log("antigravity", "no_credentials")
        return None

    paths = {
        "summary": "/exa.language_server_pb.LanguageServerService/RetrieveUserQuotaSummary",
        "status": "/exa.language_server_pb.LanguageServerService/GetUserStatus",
    }
    meta_body = json.dumps({"metadata": {
        "ideName": "antigravity", "extensionName": "antigravity",
        "ideVersion": "unknown", "locale": "en",
    }}).encode("utf-8")
    summary_body = json.dumps({"forceRefresh": True}).encode("utf-8")

    last_error_cat = "parse_error"
    for proc in processes:
        csrf = proc.get("csrf_token") or ""
        ports = _antigravity_ports(proc["pid"], proc.get("port"))
        for port in ports:
            for scheme in ("http", "https"):
                url_summary = f"{scheme}://127.0.0.1:{port}{paths['summary']}"
                req = urllib.request.Request(url_summary, data=summary_body, method="POST")
                req.add_header("Connect-Protocol-Version", "1")
                req.add_header("Content-Type", "application/json")
                if csrf:
                    req.add_header("X-Codeium-Csrf-Token", csrf)
                try:
                    import ssl
                    ctx = ssl.create_default_context()
                    ctx.check_hostname = False
                    ctx.verify_mode = ssl.CERT_NONE
                    with urllib.request.urlopen(req, timeout=min(timeout, 3), context=ctx) as res:
                        data = json.loads(res.read(MAX_RESPONSE_BYTES).decode("utf-8"))
                except urllib.error.HTTPError as e:
                    last_error_cat = f"http_status {e.code}"
                    continue
                except (TimeoutError, urllib.error.URLError) as e:
                    if "timed out" in str(e).lower():
                        last_error_cat = "timeout"
                    else:
                        last_error_cat = "parse_error"
                    continue
                except Exception:
                    last_error_cat = "parse_error"
                    continue

                if not isinstance(data, dict):
                    continue

                plan_name = None
                try:
                    url_status = f"{scheme}://127.0.0.1:{port}{paths['status']}"
                    req_status = urllib.request.Request(url_status, data=meta_body, method="POST")
                    req_status.add_header("Connect-Protocol-Version", "1")
                    req_status.add_header("Content-Type", "application/json")
                    if csrf:
                        req_status.add_header("X-Codeium-Csrf-Token", csrf)
                    with urllib.request.urlopen(req_status, timeout=min(timeout, 3), context=ctx) as res:
                        st_data = json.loads(res.read(MAX_RESPONSE_BYTES).decode("utf-8"))
                        if isinstance(st_data, dict):
                            user_tier = st_data.get("userTier") or {}
                            plan_info = (st_data.get("planStatus") or {}).get("planInfo") or {}
                            plan_name = next((v.strip() for v in (
                                user_tier.get("name"), plan_info.get("planName"),
                                plan_info.get("planDisplayName"), plan_info.get("displayName")
                            ) if isinstance(v, str) and v.strip()), None)
                except Exception:
                    pass

                result = parse_antigravity_summary(data, now=now, plan_name=plan_name)
                if result:
                    return result
    _debug_log("antigravity", last_error_cat)
    return None


def parse_antigravity_summary(data: dict, now: float, plan_name: Optional[str] = None) -> Optional[dict]:
    """Parse RetrieveUserQuotaSummary JSON into standard quota_windows fields + extra_windows."""
    groups = data.get("groups")
    if not isinstance(groups, list):
        resp = data.get("response")
        groups = resp.get("groups") if isinstance(resp, dict) else None
    if not isinstance(groups, list):
        return None

    gemini_weekly = None
    gemini_5h = None
    extra_windows = []

    for group in groups:
        if not isinstance(group, dict):
            continue
        display = str(group.get("displayName") or "").lower()
        is_gemini = "gemini" in display
        is_3p = any(k in display for k in ("claude", "gpt", "third", "3p"))

        for bucket in group.get("buckets") or []:
            if not isinstance(bucket, dict) or bucket.get("disabled") is True:
                continue
            cadence = " ".join(str(bucket.get(k) or "") for k in ("window", "bucketId", "displayName")).lower()

            rem_val = bucket.get("remainingFraction")
            if rem_val is None and isinstance(bucket.get("remaining"), dict):
                rem_val = bucket["remaining"].get("remainingFraction")
            pct = None
            if rem_val is not None and isinstance(rem_val, (int, float)):
                pct = _pct((1.0 - float(rem_val)) * 100.0)

            reset_raw = bucket.get("resetTime")
            reset_ts = None
            if isinstance(reset_raw, (int, float)):
                reset_ts = float(reset_raw)
            elif isinstance(reset_raw, str):
                reset_ts = _parse_iso(reset_raw)

            mins = None
            for mk in ("windowMinutes", "window_minutes"):
                if isinstance(bucket.get(mk), (int, float)):
                    mins = float(bucket[mk])
                    break

            if is_gemini:
                if any(k in cadence for k in ("weekly", "week", "7d")):
                    gemini_weekly = {
                        "reset": reset_ts,
                        "hours": int(round(mins / 60)) if mins else 168,
                        "pct": pct,
                    }
                elif any(k in cadence for k in ("5h", "5-hour", "five hour", "five-hour")):
                    gemini_5h = {
                        "reset": reset_ts,
                        "hours": int(round(mins / 60)) if mins else 5,
                        "pct": pct,
                    }
            elif is_3p or not is_gemini:
                bid = str(bucket.get("bucketId") or bucket.get("id") or "extra")
                btitle = str(bucket.get("displayName") or bucket.get("title") or bid)
                extra_windows.append({
                    "id": bid,
                    "title": btitle,
                    "used_percent": pct,
                    "resets_at": _iso_utc(reset_ts) if reset_ts and reset_ts > now else None,
                    "window_hours": int(round(mins / 60)) if mins else None,
                })

    if not gemini_weekly and not gemini_5h and not extra_windows:
        return None

    weekly_reset = gemini_weekly["reset"] if gemini_weekly else now + 168 * 3600
    weekly_hours = gemini_weekly["hours"] if gemini_weekly else 168
    weekly_pct = gemini_weekly["pct"] if gemini_weekly else None

    # Rollover logic if weekly_reset has passed
    period = weekly_hours * 3600
    if weekly_reset <= now:
        weekly_reset += period * (math.floor((now - weekly_reset) / period) + 1)
        weekly_pct = None

    five_reset = gemini_5h["reset"] if gemini_5h else None
    five_hours = gemini_5h["hours"] if gemini_5h else None
    five_pct = gemini_5h["pct"] if gemini_5h else None
    if five_reset is not None and five_reset <= now:
        five_reset = None
        five_pct = None

    out = {
        "weekly_resets_at": _iso_utc(weekly_reset),
        "weekly_window_hours": weekly_hours,
        "weekly_used_percent": weekly_pct,
        "five_hour_resets_at": _iso_utc(five_reset),
        "five_hour_window_hours": five_hours,
        "five_hour_used_percent": five_pct,
        "source": "live",
    }
    if plan_name:
        out["plan"] = plan_name
    if extra_windows:
        out["extra_windows"] = extra_windows
    return out


# -----------------------------------------------------------------------------
# 2. Codex / ChatGPT (HTTPS chatgpt.com)
# -----------------------------------------------------------------------------

def _load_codex_auth() -> Optional[Tuple[str, Optional[str]]]:
    """Returns (access_token, account_id) from ~/.codex/auth.json."""
    path = os.path.expanduser(os.path.join("~", ".codex", "auth.json"))
    codex_dir = os.environ.get("KANJO_CODEX_DIR")
    if codex_dir:
        for p in codex_dir.split(os.pathsep):
            parent_auth = os.path.join(os.path.dirname(os.path.expanduser(p)), "auth.json")
            if os.path.isfile(parent_auth):
                path = parent_auth
                break
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else data
    access_token = tokens.get("access_token") or tokens.get("accessToken")
    if not isinstance(access_token, str) or not access_token.strip():
        return None
    account_id = tokens.get("account_id") or tokens.get("accountId")
    return access_token.strip(), str(account_id).strip() if account_id else None


def fetch_codex_quota(now: float, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    if is_network_disabled():
        return None
    auth = _load_codex_auth()
    if not auth:
        _debug_log("codex", "no_credentials")
        return None
    access_token, account_id = auth

    url = "https://chatgpt.com/backend-api/wham/usage"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Kanjo",
    })
    req.add_unredirected_header("Authorization", f"Bearer {access_token}")
    if account_id:
        req.add_unredirected_header("ChatGPT-Account-Id", account_id)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            parsed = urllib.parse.urlparse(res.geturl())
            if parsed.scheme != "https" or parsed.hostname != "chatgpt.com":
                _debug_log("codex", "parse_error")
                return None
            data = json.loads(res.read(MAX_RESPONSE_BYTES).decode("utf-8"))
    except urllib.error.HTTPError as e:
        _debug_log("codex", f"http_status {e.code}")
        return None
    except (TimeoutError, urllib.error.URLError) as e:
        if "timed out" in str(e).lower():
            _debug_log("codex", "timeout")
        else:
            _debug_log("codex", "parse_error")
        return None
    except Exception:
        _debug_log("codex", "parse_error")
        return None

    result = parse_codex_usage(data, now=now)
    if not result:
        _debug_log("codex", "parse_error")
    return result


def parse_codex_usage(data: dict, now: float) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    rl = data.get("rate_limit") or {}
    pri = rl.get("primary_window") or {}
    sec = rl.get("secondary_window") or {}
    if not pri and not sec:
        return None

    # Secondary window (weekly)
    sec_pct = _pct(sec.get("used_percent"))
    sec_secs = sec.get("limit_window_seconds")
    sec_hours = int(round(float(sec_secs) / 3600)) if sec_secs else 168

    sec_reset = sec.get("reset_at")
    if sec_reset is None and sec.get("reset_after_seconds") is not None:
        sec_reset = now + float(sec["reset_after_seconds"])
    elif sec_reset is not None:
        sec_reset = float(sec_reset)

    if sec_reset is not None and sec_reset <= now:
        period = sec_hours * 3600
        sec_reset += period * (math.floor((now - sec_reset) / period) + 1)
        sec_pct = None

    # Primary window (5h)
    pri_pct = _pct(pri.get("used_percent"))
    pri_secs = pri.get("limit_window_seconds")
    pri_hours = int(round(float(pri_secs) / 3600)) if pri_secs else 5

    pri_reset = pri.get("reset_at")
    if pri_reset is None and pri.get("reset_after_seconds") is not None:
        pri_reset = now + float(pri["reset_after_seconds"])
    elif pri_reset is not None:
        pri_reset = float(pri_reset)

    if pri_reset is not None and pri_reset <= now:
        pri_reset = None
        pri_pct = None

    if sec_reset is None and sec_pct is None and pri_reset is None and pri_pct is None:
        return None

    out = {
        "weekly_resets_at": _iso_utc(sec_reset),
        "weekly_window_hours": sec_hours,
        "weekly_used_percent": sec_pct,
        "five_hour_resets_at": _iso_utc(pri_reset),
        "five_hour_window_hours": pri_hours,
        "five_hour_used_percent": pri_pct,
        "source": "live",
    }
    plan = data.get("plan_type")
    if isinstance(plan, str) and plan.strip():
        out["plan"] = plan.strip()
    return out


# -----------------------------------------------------------------------------
# 3. Claude Code (HTTPS api.anthropic.com via macOS Keychain / ~/.claude.json)
# -----------------------------------------------------------------------------

def _load_claude_credentials() -> Optional[str]:
    """Retrieve Claude Code access token from macOS Keychain via security command."""
    try:
        res = subprocess.run(
            ["/usr/bin/security", "find-generic-password", "-s", "Claude Code-credentials", "-w"],
            capture_output=True, text=True, timeout=3, check=False
        )
        if res.returncode != 0:
            _debug_log("claude", "keychain_denied")
            return None
        raw_text = res.stdout.strip()
        if not raw_text:
            return None
        data = json.loads(raw_text)
        if isinstance(data, dict):
            oauth = data.get("claudeAiOauth") or {}
            token = oauth.get("accessToken")
            if isinstance(token, str) and token.strip():
                expires_at = oauth.get("expiresAt")
                if isinstance(expires_at, (int, float)):
                    exp = float(expires_at)
                    if exp < 10_000_000_000:
                        exp *= 1000  # seconds to ms
                    if exp <= (time.time() + 30) * 1000:
                        return None  # expired
                return token.strip()
    except Exception:
        pass
    return None


def _claude_from_config(now: float) -> Optional[dict]:
    claude_json = os.path.expanduser(os.environ.get("KANJO_CLAUDE_CONFIG") or os.path.join("~", ".claude.json"))
    try:
        with open(claude_json, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            cached = data.get("cachedUsageUtilization")
            if isinstance(cached, dict):
                util = cached.get("utilization")
                if isinstance(util, dict):
                    res = parse_claude_usage(util, now=now)
                    if res:
                        res["source"] = "live"
                        return res
    except Exception:
        pass
    return None


def fetch_claude_quota(now: float, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    if is_network_disabled():
        return None
    token = _load_claude_credentials()
    if token:
        url = "https://api.anthropic.com/api/oauth/usage?at_wall=1&skip_spend=1"
        req = urllib.request.Request(url, headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "anthropic-beta": "oauth-2025-04-20",
            "User-Agent": "claude-code/2.1.0",
        })
        req.add_unredirected_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(req, timeout=timeout) as res:
                parsed = urllib.parse.urlparse(res.geturl())
                if parsed.scheme != "https" or parsed.hostname != "api.anthropic.com":
                    _debug_log("claude", "parse_error")
                    return None
                data = json.loads(res.read(MAX_RESPONSE_BYTES).decode("utf-8"))
                result = parse_claude_usage(data, now=now)
                if result:
                    return result
                _debug_log("claude", "parse_error")
        except urllib.error.HTTPError as e:
            _debug_log("claude", f"http_status {e.code}")
        except (TimeoutError, urllib.error.URLError) as e:
            if "timed out" in str(e).lower():
                _debug_log("claude", "timeout")
            else:
                _debug_log("claude", "parse_error")
        except Exception:
            _debug_log("claude", "parse_error")

    # If live token is not in keychain or expired, fallback to Claude CLI's own cache in ~/.claude.json
    cached_result = _claude_from_config(now)
    if cached_result:
        return cached_result

    _debug_log("claude", "no_credentials")
    return None


def parse_claude_usage(data: dict, now: float) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    seven = data.get("seven_day") or {}
    five = data.get("five_hour") or {}
    if not seven and not five:
        return None

    # Weekly
    sec_pct = _percentage(seven.get("utilization"))
    sec_reset = _parse_iso(seven.get("resets_at"))
    sec_hours = 168
    if sec_reset is not None and sec_reset <= now:
        period = sec_hours * 3600
        sec_reset += period * (math.floor((now - sec_reset) / period) + 1)
        sec_pct = None

    # 5h
    pri_pct = _percentage(five.get("utilization"))
    pri_reset = _parse_iso(five.get("resets_at"))
    pri_hours = 5
    if pri_reset is not None and pri_reset <= now:
        pri_reset = None
        pri_pct = None

    if sec_reset is None and sec_pct is None and pri_reset is None and pri_pct is None:
        return None

    return {
        "weekly_resets_at": _iso_utc(sec_reset),
        "weekly_window_hours": sec_hours,
        "weekly_used_percent": sec_pct,
        "five_hour_resets_at": _iso_utc(pri_reset),
        "five_hour_window_hours": pri_hours,
        "five_hour_used_percent": pri_pct,
        "source": "live",
    }


# -----------------------------------------------------------------------------
# 4. Grok CLI (HTTPS cli-chat-proxy.grok.com)
# -----------------------------------------------------------------------------

def _load_grok_auth() -> Optional[str]:
    """Find valid Grok bearer token from ~/.grok/auth.json."""
    path = os.path.expanduser(os.path.join("~", ".grok", "auth.json"))
    grok_dir = os.environ.get("KANJO_GROK_DIR")
    if grok_dir:
        path = os.path.join(os.path.expanduser(grok_dir), "auth.json")
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None

    if not isinstance(data, dict):
        return None
    for entry in data.values():
        if not isinstance(entry, dict):
            continue
        token = entry.get("key") or entry.get("access_token")
        if isinstance(token, str) and token.strip():
            expires_at = entry.get("expires_at")
            if isinstance(expires_at, str):
                exp = _parse_iso(expires_at)
                if exp and exp <= time.time():
                    continue  # expired
            return token.strip()
    return None


def fetch_grok_quota(now: float, timeout: int = REQUEST_TIMEOUT) -> Optional[dict]:
    if is_network_disabled():
        return None
    token = _load_grok_auth()
    if not token:
        _debug_log("grok", "no_credentials")
        return None

    url = "https://cli-chat-proxy.grok.com/v1/billing?format=credits"
    req = urllib.request.Request(url, headers={
        "Accept": "application/json",
        "User-Agent": "Kanjo",
    })
    req.add_unredirected_header("Authorization", f"Bearer {token}")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            parsed = urllib.parse.urlparse(res.geturl())
            if parsed.scheme != "https" or parsed.hostname != "cli-chat-proxy.grok.com":
                _debug_log("grok", "parse_error")
                return None
            data = json.loads(res.read(MAX_RESPONSE_BYTES).decode("utf-8"))
    except urllib.error.HTTPError as e:
        _debug_log("grok", f"http_status {e.code}")
        return None
    except (TimeoutError, urllib.error.URLError) as e:
        if "timed out" in str(e).lower():
            _debug_log("grok", "timeout")
        else:
            _debug_log("grok", "parse_error")
        return None
    except Exception:
        _debug_log("grok", "parse_error")
        return None

    result = parse_grok_usage(data, now=now)
    if not result:
        _debug_log("grok", "parse_error")
    return result


def parse_grok_usage(data: dict, now: float) -> Optional[dict]:
    if not isinstance(data, dict):
        return None
    cfg = data.get("config")
    if not isinstance(cfg, dict):
        return None
    period = cfg.get("currentPeriod") or {}
    end_raw = period.get("end") or cfg.get("billingPeriodEnd")
    reset_ts = _parse_iso(end_raw)

    pct_raw = cfg.get("creditUsagePercent")
    if "creditUsagePercent" not in cfg:
        # Protobuf JSON omits zero values; unified billing user with a valid period has 0% used
        has_period = bool(period.get("start") and reset_ts is not None)
        if cfg.get("isUnifiedBillingUser") is True and has_period:
            pct_raw = 0.0
    used_pct = _pct(pct_raw)

    if reset_ts is None and used_pct is None:
        return None

    hours = 168
    if reset_ts is not None and reset_ts <= now:
        period_s = hours * 3600
        reset_ts += period_s * (math.floor((now - reset_ts) / period_s) + 1)
        used_pct = None

    plan = data.get("subscriptionTier") or data.get("plan") or ("SuperGrok" if cfg.get("isUnifiedBillingUser") else None)
    out = {
        "weekly_resets_at": _iso_utc(reset_ts),
        "weekly_window_hours": hours,
        "weekly_used_percent": used_pct,
        "five_hour_resets_at": None,
        "five_hour_window_hours": None,
        "five_hour_used_percent": None,
        "source": "live",
    }
    if isinstance(plan, str) and plan.strip():
        out["plan"] = plan.strip()
    return out


# -----------------------------------------------------------------------------
# Top-level Orchestrator
# -----------------------------------------------------------------------------

FETCHERS = {
    "antigravity": fetch_antigravity_quota,
    "codex": fetch_codex_quota,
    "claude": fetch_claude_quota,
    "grok": fetch_grok_quota,
}


def fetch_all_quotas(now: Optional[float] = None, no_network: bool = False) -> Dict[str, dict]:
    """Fetch live quotas for all supported providers, respecting cache TTL and security rules."""
    now = time.time() if now is None else now
    cached = load_quota_cache()
    if cached:
        fetched_at = cached.get("fetched_at")
        if isinstance(fetched_at, (int, float)) and 0 <= now - float(fetched_at) < CACHE_TTL:
            providers = cached.get("providers")
            if isinstance(providers, dict):
                return {k: v for k, v in providers.items() if isinstance(v, dict)}

    if no_network or is_network_disabled():
        if cached:
            providers = cached.get("providers")
            if isinstance(providers, dict):
                return {k: v for k, v in providers.items() if isinstance(v, dict)}
        return {}

    results = {}
    for agent, fetcher in FETCHERS.items():
        try:
            res = fetcher(now=now)
            if res:
                results[agent] = res
        except Exception:
            pass

    if results:
        old_providers = (cached.get("providers") if cached else {}) or {}
        merged = dict(old_providers)
        merged.update(results)
        save_quota_cache({
            "version": CACHE_VERSION,
            "fetched_at": now,
            "providers": merged,
        })
        return results

    if cached:
        providers = cached.get("providers")
        if isinstance(providers, dict):
            return {k: v for k, v in providers.items() if isinstance(v, dict)}
    return {}
