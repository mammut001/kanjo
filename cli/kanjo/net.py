"""TLS trust for Kanjo's outbound HTTPS calls.

A python.org build of Python on macOS ships an OpenSSL with no CA bundle until
"Install Certificates.command" is run, so the default context cannot verify
public servers. On macOS this module also trusts the system root certificates
(exported read-only from Apple's SystemRootCertificates keychain, cached in the
Kanjo cache dir for 7 days) and ``/etc/ssl/cert.pem``. Verification is never
disabled; every extra step is best-effort.
"""

from __future__ import annotations

import os
import ssl
import subprocess
import sys
import tempfile
import time
from typing import Optional

_SECURITY = "/usr/bin/security"
_SYSTEM_ROOTS_KEYCHAIN = "/System/Library/Keychains/SystemRootCertificates.keychain"
_LOCAL_CA_BUNDLE = "/etc/ssl/cert.pem"
_ROOTS_CACHE_NAME = "macos-system-roots.pem"
_ROOTS_MAX_AGE = 7 * 24 * 3600.0
_SECURITY_TIMEOUT = 10

_context: Optional[ssl.SSLContext] = None


def ssl_context() -> ssl.SSLContext:
    """Return the process-wide verifying TLS context (built once)."""
    global _context
    if _context is None:
        _context = _build_context()
    return _context


def _on_macos() -> bool:
    return sys.platform == "darwin"


def _python_org_build() -> bool:
    prefixes = ("/Library/Frameworks/Python.framework/",)
    return any(sys.executable.startswith(p) or sys.prefix.startswith(p) for p in prefixes)


def _build_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if not _on_macos():
        return ctx  # Windows and Linux already use the system store
    for step in (_load_local_bundle, _load_system_roots, _load_certifi):
        try:
            step(ctx)
        except Exception:
            pass  # best-effort: keep whatever loaded so far
    return ctx


def _load_local_bundle(ctx: ssl.SSLContext) -> None:
    if os.path.isfile(_LOCAL_CA_BUNDLE):
        ctx.load_verify_locations(cafile=_LOCAL_CA_BUNDLE)


def _load_system_roots(ctx: ssl.SSLContext) -> None:
    path = _roots_cache_path()
    if path is None:
        return
    if not _roots_cache_fresh(path):
        _refresh_roots_cache(path)  # on failure a stale copy, if any, is still used
    if os.path.isfile(path):
        ctx.load_verify_locations(cafile=path)


def _load_certifi(ctx: ssl.SSLContext) -> None:
    import certifi  # optional; not a dependency
    ctx.load_verify_locations(cafile=certifi.where())


def _roots_cache_path() -> Optional[str]:
    try:
        from .cache import _cache_dir
        return os.path.join(_cache_dir(), _ROOTS_CACHE_NAME)
    except Exception:
        return None


def _roots_cache_fresh(path: str) -> bool:
    try:
        return os.path.isfile(path) and time.time() - os.path.getmtime(path) < _ROOTS_MAX_AGE
    except OSError:
        return False


def _refresh_roots_cache(path: str) -> None:
    try:
        proc = subprocess.run(
            [_SECURITY, "find-certificate", "-a", "-p", _SYSTEM_ROOTS_KEYCHAIN],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=_SECURITY_TIMEOUT,
            check=False,
        )
    except Exception:
        return
    pem = proc.stdout or b""
    if proc.returncode != 0 or b"BEGIN CERTIFICATE" not in pem:
        return
    directory = os.path.dirname(path)
    tmp = None
    try:
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".macos-roots-", dir=directory)
        with os.fdopen(fd, "wb") as fh:
            fh.write(pem)
        os.replace(tmp, path)
        tmp = None
    except OSError:
        pass
    finally:
        if tmp is not None:
            try:
                os.remove(tmp)
            except OSError:
                pass


def is_cert_error(exc: BaseException) -> bool:
    """True when ``exc`` (or the reason inside a URLError) is a TLS verification failure."""
    reason = getattr(exc, "reason", None)
    for candidate in (exc, reason):
        if candidate is None:
            continue
        if isinstance(candidate, ssl.SSLError) or "CERTIFICATE_VERIFY_FAILED" in str(candidate):
            return True
    return False


def cert_hint(exc: BaseException) -> str:
    """Extra advice for a certificate error from a python.org build on macOS, else ''."""
    if not is_cert_error(exc) or not _on_macos() or not _python_org_build():
        return ""
    return ('This Python (from python.org) has no certificate bundle yet; run "Install Certificates.command" '
            "in its folder under /Applications, then try again.")
