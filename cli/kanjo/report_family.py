"""Report family usage command: ``kanjo report-family``.

POSTs JSON family report document to family server /api/report (CONTRACT.md section 13).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

from . import __version__
from .config import Config, ConfigError, load as load_config
from .export import (
    build_family_report,
    load_fast_family_report,
    save_fast_family_report,
    source_fingerprint,
)


def _config(args) -> Config:
    return load_config(getattr(args, "config", None))


def _cache(args):
    if getattr(args, "no_cache", False):
        return None
    from .cache import SessionCache
    return SessionCache()


def cmd_report_family(args) -> int:
    # 1. Token must come strictly from environment variable
    token = os.environ.get("KANJO_FAMILY_TOKEN")
    if not token or not token.strip():
        output = {"status": "error", "message": "KANJO_FAMILY_TOKEN environment variable is not set"}
        print(json.dumps(output))
        return 1
    token = token.strip()

    # 2. Validate URL (reject non-https except http://127.0.0.1 or http://localhost)
    raw_url = getattr(args, "url", "") or ""
    parsed = urllib.parse.urlsplit(raw_url.strip())
    if not (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost"))):
        output = {
            "status": "error",
            "message": "Invalid URL: only HTTPS or local HTTP (127.0.0.1/localhost) URLs are allowed",
        }
        print(json.dumps(output))
        return 1

    # 3. Build family report document
    cfg = _config(args)
    doc = None
    fp = None
    member_label = getattr(args, "member_label", None)
    use_cache = not getattr(args, "no_cache", False)
    if use_cache:
        fp = source_fingerprint(config=cfg)
        doc = load_fast_family_report(fp, member_label=member_label)
    if doc is None:
        doc = build_family_report(config=cfg, cache=_cache(args), member_label=member_label)
        if use_cache:
            if fp is None:
                fp = source_fingerprint(config=cfg)
            save_fast_family_report(fp, doc, member_label=member_label)

    # 4. Prepare HTTP request
    endpoint = raw_url.strip().rstrip("/") + "/api/report"
    req_data = json.dumps(doc, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=req_data,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {token}",
            "User-Agent": f"kanjo/{__version__}",
        },
        method="POST",
    )

    # 5. POST to server with 30s timeout, no retries
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            resp_body = resp.read().decode("utf-8")
            resp_json = json.loads(resp_body) if resp_body else {}
            output = {"status": "sent"}
            if "received_at" in resp_json:
                output["received_at"] = resp_json["received_at"]
            print(json.dumps(output))
            return 0
    except urllib.error.HTTPError as exc:
        err_msg = None
        try:
            err_body = exc.read().decode("utf-8")
            err_json = json.loads(err_body)
            err_msg = err_json.get("error") or err_json.get("message")
        except Exception:
            pass
        if not err_msg:
            err_msg = exc.reason if exc.reason else f"HTTP {exc.code}"
        output = {"status": "error", "http_status": exc.code, "message": str(err_msg)}
        print(json.dumps(output))
        return 1
    except urllib.error.URLError as exc:
        output = {"status": "error", "message": str(exc.reason)}
        print(json.dumps(output))
        return 1
    except Exception as exc:
        output = {"status": "error", "message": str(exc)}
        print(json.dumps(output))
        return 1
