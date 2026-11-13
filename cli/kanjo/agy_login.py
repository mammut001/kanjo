"""Antigravity CLI (agy) keychain login management and account switcher.

The Antigravity CLI keeps one generic password in the macOS keychain:
service: "gemini", account: "antigravity" (written by go-keyring).

Kanjo manages saved copies under:
service: "com.lanshuagent.kanjo.agy-login", account: <lowercased email>

All keychain operations go through an injectable backend.
Secrets are never passed in argv (interactive mode / stdin only),
never logged, and never included in error messages or exceptions.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
import re
import shlex
import stat
import subprocess
import sys
import tempfile
import time
from typing import Dict, List, Optional, Set, Tuple

from .cache import _cache_dir

SLOT_SERVICE = "gemini"
SLOT_ACCOUNT = "antigravity"
SAVED_SERVICE = "com.lanshuagent.kanjo.agy-login"
SLOT_WRITE_STATE_FILE = "agy-slot-write.json"


def _slot_write_state_path(cache_dir: Optional[str] = None) -> str:
    cdir = cache_dir or _cache_dir()
    return os.path.join(cdir, SLOT_WRITE_STATE_FILE)


def _read_slot_write_record(cache_dir: Optional[str] = None) -> Optional[dict]:
    path = _slot_write_state_path(cache_dir)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "sha256" in data and "email" in data:
            return data
    except (OSError, ValueError):
        pass
    return None


def _record_slot_write(secret_bytes: bytes, email: str, cache_dir: Optional[str] = None) -> None:
    cdir = cache_dir or _cache_dir()
    try:
        os.makedirs(cdir, exist_ok=True)
    except OSError:
        pass
    digest = hashlib.sha256(secret_bytes).hexdigest()
    payload = {
        "sha256": digest,
        "email": email.strip().lower(),
        "written_at": time.time(),
    }
    path = _slot_write_state_path(cdir)
    tmp = None
    try:
        fd, tmp = tempfile.mkstemp(prefix=".agy-slot-write-", dir=cdir)
        os.chmod(tmp, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, separators=(",", ":"))
        os.replace(tmp, path)
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    except OSError:
        pass
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


class KeychainBackend:
    """Interface for macOS Keychain operations."""

    def read_slot(self) -> Optional[bytes]:
        raise NotImplementedError

    def write_slot(self, secret: bytes) -> None:
        raise NotImplementedError

    def slot_modified_at(self) -> Optional[float]:
        raise NotImplementedError

    def read_saved(self, email: str) -> Optional[bytes]:
        raise NotImplementedError

    def write_saved(self, email: str, secret: bytes) -> None:
        raise NotImplementedError

    def delete_saved(self, email: str) -> None:
        raise NotImplementedError

    def list_saved(self) -> List[str]:
        raise NotImplementedError


def _escape_security_arg(val: str) -> str:
    """Escape argument for security -i interactive mode."""
    escaped = val.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


class SecurityKeychainBackend(KeychainBackend):
    """Real macOS keychain backend using /usr/bin/security without argv secrets."""

    def __init__(self, security_bin: str = "/usr/bin/security"):
        self.security_bin = security_bin

    def read_slot(self) -> Optional[bytes]:
        return self._read_generic_password(SLOT_SERVICE, SLOT_ACCOUNT)

    def write_slot(self, secret: bytes) -> None:
        self._write_generic_password(SLOT_SERVICE, SLOT_ACCOUNT, secret)

    def slot_modified_at(self) -> Optional[float]:
        try:
            res = subprocess.run(
                [self.security_bin, "find-generic-password", "-s", SLOT_SERVICE, "-a", SLOT_ACCOUNT],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
            if res.returncode != 0:
                return None
            m = re.search(r'"mdat"[^\n]*"(\d{4})(\d{2})(\d{2})(\d{2})(\d{2})(\d{2})', res.stdout)
            if m:
                dt = datetime(
                    int(m.group(1)),
                    int(m.group(2)),
                    int(m.group(3)),
                    int(m.group(4)),
                    int(m.group(5)),
                    int(m.group(6)),
                    tzinfo=timezone.utc,
                )
                return dt.timestamp()
            return None
        except Exception:
            return None

    def read_saved(self, email: str) -> Optional[bytes]:
        return self._read_generic_password(SAVED_SERVICE, email.lower())

    def write_saved(self, email: str, secret: bytes) -> None:
        self._write_generic_password(SAVED_SERVICE, email.lower(), secret)

    def delete_saved(self, email: str) -> None:
        try:
            subprocess.run(
                [self.security_bin, "delete-generic-password", "-s", SAVED_SERVICE, "-a", email.lower()],
                capture_output=True,
                check=False,
            )
        except Exception:
            pass

    def list_saved(self) -> List[str]:
        try:
            res = subprocess.run(
                [self.security_bin, "dump-keychain"],
                capture_output=True,
                text=True,
                errors="replace",
                check=False,
            )
            if res.returncode != 0:
                return []
            accounts: Set[str] = set()
            blocks = res.stdout.split("class: ")
            for block in blocks[1:]:
                # Check if service matches com.lanshuagent.kanjo.agy-login
                if f'"{SAVED_SERVICE}"' in block or f'<blob>={SAVED_SERVICE}' in block:
                    m = re.search(r'"acct"<blob>="([^"]+)"', block)
                    if m:
                        accounts.add(m.group(1).lower())
            return sorted(accounts)
        except Exception:
            return []

    def _read_generic_password(self, service: str, account: str) -> Optional[bytes]:
        try:
            res = subprocess.run(
                [self.security_bin, "find-generic-password", "-s", service, "-a", account, "-w"],
                capture_output=True,
                check=False,
            )
            if res.returncode != 0:
                return None
            out = res.stdout
            if out.endswith(b"\r\n"):
                out = out[:-2]
            elif out.endswith(b"\n"):
                out = out[:-1]
            return out
        except Exception:
            return None

    def _write_generic_password(self, service: str, account: str, secret: bytes) -> None:
        val_str = secret.decode("utf-8", errors="replace")
        cmd_line = f"add-generic-password -U -s {_escape_security_arg(service)} -a {_escape_security_arg(account)} -w {_escape_security_arg(val_str)}\n"
        stdin_data = cmd_line.encode("utf-8")
        try:
            res = subprocess.run(
                [self.security_bin, "-i"],
                input=stdin_data,
                capture_output=True,
                check=False,
            )
            if res.returncode != 0:
                raise RuntimeError("failed to write keychain item")
        except Exception as exc:
            # Strictly ensure secret is never included in exception message
            if isinstance(exc, RuntimeError) and str(exc) == "failed to write keychain item":
                raise
            raise RuntimeError("failed to execute keychain tool") from None


_BACKEND: Optional[KeychainBackend] = None


def get_backend() -> Optional[KeychainBackend]:
    global _BACKEND
    if _BACKEND is not None:
        return _BACKEND
    if sys.platform == "darwin":
        return SecurityKeychainBackend()
    return None


def set_backend(backend: Optional[KeychainBackend]) -> None:
    global _BACKEND
    _BACKEND = backend


def get_slot_owner(
    backend: KeychainBackend,
    index=None,
    slot_bytes: Optional[bytes] = None,
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Determine the account in the slot.

    1. Kanjo-write hash match: if sha256(current slot bytes) equals the recorded
       hash from a Kanjo switch, owner = recorded email.
    2. Evidence rule: email of earliest span with auth_ts >= mdat + 1.0 that loaded
       from keyring and has exactly one email. Spans with auth_ts in [mdat, mdat+1)
       are ambiguous: if any such span exists with a different email, return None.
    3. Alive-at-mdat refresh rule: if evidence rule finds nothing, look at
       keyring-loaded spans alive at mdat (start <= mdat+1 and end >= mdat-1).
       If there is at least one, they all have exactly one and the same email X,
       and none of them logged any auth/email line with a different email at or
       after mdat-1, owner = X.
    4. Otherwise None.
    """
    if slot_bytes is None:
        slot_bytes = backend.read_slot()

    effective_cache_dir = cache_dir or getattr(index, "cache_dir", None)

    # 1. Kanjo-write hash match
    if slot_bytes:
        record = _read_slot_write_record(effective_cache_dir)
        if record:
            rec_sha = record.get("sha256")
            rec_email = record.get("email")
            if rec_sha and rec_email:
                cur_sha = hashlib.sha256(slot_bytes).hexdigest()
                if cur_sha.lower() == str(rec_sha).strip().lower():
                    return str(rec_email).strip().lower()

    mdat = backend.slot_modified_at()
    if mdat is None:
        return None

    if index is None:
        from .antigravity_accounts import get_account_index
        index = get_account_index()

    keyring_spans = [s for s in index.spans if s.auth_ts is not None]
    keyring_spans.sort(key=lambda s: s.auth_ts)

    # 2. Evidence rule
    first_qualifying_email = None
    for s in keyring_spans:
        if s.auth_ts < (mdat + 1.0):
            continue
        if len(s.emails) == 1:
            first_qualifying_email = next(iter(s.emails)).lower()
            break
        elif len(s.emails) > 1:
            return None

    if first_qualifying_email is not None:
        for s in keyring_spans:
            if mdat <= s.auth_ts < (mdat + 1.0):
                if not s.emails:
                    continue
                s_emails = {e.lower() for e in s.emails}
                if len(s_emails) != 1 or next(iter(s_emails)) != first_qualifying_email:
                    return None
        return first_qualifying_email

    # Spans with auth_ts in [mdat, mdat+1) are ambiguous; if any exists with no qualifying span >= mdat+1, return None
    for s in keyring_spans:
        if mdat <= s.auth_ts < (mdat + 1.0):
            return None

    # 3. Alive-at-mdat refresh rule
    # Look at keyring-loaded spans that were ALIVE at mdat (start <= mdat+1 and end >= mdat-1)
    # and loaded keyring before mdat (auth_ts < mdat)
    live_spans = [
        s for s in keyring_spans
        if s.start <= (mdat + 1.0) and s.end >= (mdat - 1.0) and s.auth_ts < mdat
    ]
    if live_spans:
        distinct_emails: Set[str] = set()
        all_single = True
        for s in live_spans:
            if len(s.emails) != 1:
                all_single = False
                break
            distinct_emails.add(next(iter(s.emails)).lower())
        if all_single and len(distinct_emails) == 1:
            candidate = next(iter(distinct_emails))
            # none of them logged any auth/email line with a different email at or after mdat - 1
            has_different_auth = False
            for s in live_spans:
                for event_ts, event_email in getattr(s, "auth_events", []):
                    if event_ts >= (mdat - 1.0) and str(event_email).strip().lower() != candidate:
                        has_different_auth = True
                        break
                if has_different_auth:
                    break
            if not has_different_auth:
                return candidate

    return None


def sync(
    backend: Optional[KeychainBackend] = None,
    index=None,
    cache_dir: Optional[str] = None,
) -> dict:
    """Save/refresh the slot value into that account's saved copy if owner is known."""
    backend = backend or get_backend()
    if backend is None:
        return {"status": "error", "message": "only supported on macOS"}

    slot_bytes = backend.read_slot()
    if not slot_bytes:
        return {"status": "ok", "synced": False, "reason": "slot empty"}

    owner = get_slot_owner(backend, index, slot_bytes=slot_bytes, cache_dir=cache_dir)
    if not owner:
        return {"status": "ok", "synced": False, "reason": "slot owner unknown"}

    saved_bytes = backend.read_saved(owner)
    if saved_bytes != slot_bytes:
        for other_email in backend.list_saved():
            if other_email.lower() != owner.lower():
                if backend.read_saved(other_email) == slot_bytes:
                    return {"status": "ok", "synced": False, "reason": "slot matches another account"}
        backend.write_saved(owner, slot_bytes)
        return {"status": "ok", "synced": True, "account": owner}

    return {"status": "ok", "synced": False, "account": owner, "reason": "already up to date"}


def switch(
    email: str,
    backend: Optional[KeychainBackend] = None,
    index=None,
    cache_dir: Optional[str] = None,
) -> Tuple[int, dict]:
    """Switch active login slot to target email."""
    backend = backend or get_backend()
    if backend is None:
        return 1, {"status": "error", "message": "only supported on macOS"}

    target = email.strip().lower()
    if not target:
        return 1, {"status": "error", "message": "email cannot be empty"}

    # 1. run sync first (keeps the outgoing account's refreshed token)
    sync(backend, index, cache_dir=cache_dir)

    # After step 1 sync, if slot bytes equal target's saved copy already, return ok without writing
    target_bytes = backend.read_saved(target)
    slot_bytes = backend.read_slot()
    if target_bytes and slot_bytes == target_bytes:
        return 0, {
            "status": "ok",
            "account": target,
            "note": "running agy sessions keep their old account until restarted",
        }

    # 2. if slot owner is unknown and slot is non-empty and differs from every saved copy, refuse
    slot_bytes = backend.read_slot()
    if slot_bytes:
        owner = get_slot_owner(backend, index, slot_bytes=slot_bytes, cache_dir=cache_dir)
        if not owner:
            saved_list = backend.list_saved()
            matches_any = False
            for saved_email in saved_list:
                if backend.read_saved(saved_email) == slot_bytes:
                    matches_any = True
                    break
            if not matches_any:
                return 1, {
                    "status": "error",
                    "error": "unsaved_login",
                    "message": "current login is not saved yet; run agy once and refresh Kanjo",
                }

    # 3. require a saved copy for EMAIL, else error no_saved_login
    target_bytes = backend.read_saved(target)
    if not target_bytes:
        return 1, {
            "status": "error",
            "error": "no_saved_login",
            "message": f"no saved login for {target}",
        }

    # 4. write saved bytes into the slot, read back and compare; on mismatch restore
    prev_bytes = slot_bytes
    backend.write_slot(target_bytes)
    readback = backend.read_slot()
    if readback != target_bytes:
        if prev_bytes is not None:
            backend.write_slot(prev_bytes)
        return 1, {
            "status": "error",
            "error": "verification_failed",
            "message": "read-back mismatch after writing slot; restored previous login",
        }

    _record_slot_write(target_bytes, target, cache_dir=cache_dir)

    # 5. output
    return 0, {
        "status": "ok",
        "account": target,
        "note": "running agy sessions keep their old account until restarted",
    }


def list_accounts_login(backend: Optional[KeychainBackend] = None, index=None) -> Tuple[int, dict]:
    """List all seen and saved accounts with saved_login and current status."""
    backend = backend or get_backend()
    if backend is None:
        return 1, {"status": "error", "message": "only supported on macOS"}

    if index is None:
        from .antigravity_accounts import get_account_index
        index = get_account_index()

    saved_accounts = set(backend.list_saved())
    log_accounts = {em for span in index.spans for em in span.emails}
    all_emails = sorted(saved_accounts.union(log_accounts))

    current_account = index.get_current_account()

    accounts = []
    for em in all_emails:
        accounts.append({
            "email": em,
            "saved_login": em in saved_accounts,
            "current": em == current_account,
        })

    return 0, {"status": "ok", "current": current_account, "accounts": accounts}


def forget(email: str, backend: Optional[KeychainBackend] = None, cache_dir: Optional[str] = None) -> Tuple[int, dict]:
    """Remove saved login for email."""
    backend = backend or get_backend()
    if backend is None:
        return 1, {"status": "error", "message": "only supported on macOS"}

    target = email.strip().lower()
    backend.delete_saved(target)
    try:
        record = _read_slot_write_record(cache_dir)
        if record and str(record.get("email")).strip().lower() == target:
            path = _slot_write_state_path(cache_dir)
            if os.path.exists(path):
                os.unlink(path)
    except OSError:
        pass
    return 0, {"status": "ok", "account": target, "action": "forgotten"}
