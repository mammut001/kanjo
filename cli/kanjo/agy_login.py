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

# Surfaced by `agy-account switch` / `list` JSON and localized by the app/TUI.
# Running agy processes rewrite the slot at their next token refresh, so the
# user must quit (or restart) them after switching.
_SWITCH_NOTE = (
    "running agy sessions write their own login back at their next token "
    "refresh — quit them (or restart them) after switching"
)


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


def count_running_agy() -> Optional[int]:
    """Number of running processes named exactly ``agy``.

    Uses ``pgrep -x agy`` (one PID per line). Returns 0 when none are running,
    and ``None`` when the count cannot be determined (pgrep missing / error).
    Injectable for tests via patching ``kanjo.agy_login.count_running_agy``.
    """
    try:
        res = subprocess.run(
            ["pgrep", "-x", "agy"],
            capture_output=True,
            text=True,
            errors="replace",
            check=False,
        )
    except Exception:
        return None
    if res.returncode not in (0, 1):
        return None
    return len([line for line in (res.stdout or "").splitlines() if line.strip()])


def _running_agy_field(running_agy: Optional[int]) -> Optional[int]:
    """Resolve the ``running_agy`` value: explicit override, else a live count."""
    if running_agy is not None:
        return running_agy
    return count_running_agy()


def set_backend(backend: Optional[KeychainBackend]) -> None:
    global _BACKEND
    _BACKEND = backend


def get_slot_owner(
    backend: KeychainBackend,
    index=None,
    slot_bytes: Optional[bytes] = None,
    cache_dir: Optional[str] = None,
) -> Optional[str]:
    """Determine the account currently in the slot.

    1. Kanjo-write hash match: if sha256(current slot bytes) equals the hash
       recorded by a Kanjo switch, owner = recorded email.
    2. Candidate slot-writing events: every ``login`` auth event and every
       ``refresh`` event, across all files, with ``mdat - 5s <= ts <= mdat + 2s``.
       The owner of such an event is the file's active email at that event.
       If the candidates agree on exactly one email, that is the owner.
    3. Keyring-launch evidence: otherwise, if a launch that *started after mdat*
       loaded the token via keyring (``via == "keyring"``), its email is the owner.
    4. If the two rules disagree, or the candidates disagree, -> None. Never guess.
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

    # 2. Candidate slot-writing events (logins + refreshes) near mdat.
    lo = mdat - 5.0
    hi = mdat + 2.0
    candidate_emails: Set[str] = set()
    for span in index.spans:
        for ts, email, via in getattr(span, "auth_events", []):
            if via == "login" and lo <= ts <= hi:
                candidate_emails.add(str(email).strip().lower())
        for ts in getattr(span, "refresh_events", []):
            if lo <= ts <= hi:
                em = span.active_email_at(ts)
                if em:
                    candidate_emails.add(str(em).strip().lower())

    if len(candidate_emails) > 1:
        # Candidates disagree -> unknown.
        return None
    rule_a = next(iter(candidate_emails)) if candidate_emails else None

    # 3. Keyring-launch evidence: a launch that started after mdat and loaded
    #    the token from the keychain owns whatever was in the slot.
    keyring_emails: Set[str] = set()
    for span in index.spans:
        if span.start > mdat:
            for _ts, email, via in getattr(span, "auth_events", []):
                if via == "keyring":
                    keyring_emails.add(str(email).strip().lower())
    if len(keyring_emails) > 1:
        rule_b: Optional[str] = None
    else:
        rule_b = next(iter(keyring_emails)) if keyring_emails else None

    # 4. Reconcile the two rules; never guess between disagreement.
    if rule_a is not None and rule_b is not None:
        return rule_a if rule_a == rule_b else None
    return rule_a if rule_a is not None else rule_b


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
    running_agy: Optional[int] = None,
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
            "note": _SWITCH_NOTE,
            "running_agy": _running_agy_field(running_agy),
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
        "note": _SWITCH_NOTE,
        "running_agy": _running_agy_field(running_agy),
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

    return 0, {
        "status": "ok",
        "current": current_account,
        "running_agy": count_running_agy(),
        "accounts": accounts,
    }


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
