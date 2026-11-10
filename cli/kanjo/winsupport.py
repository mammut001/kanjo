"""Windows platform support for Kanjo.

Provides PowerShell execution and Windows Credential Manager integration (advapi32).
All credential and powershell routines safely no-op or return None/False on non-Windows.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
import subprocess
import sys
from typing import Optional, Callable

# Credential Manager constants (wincred.h)
CRED_TYPE_GENERIC = 1
CRED_PERSIST_LOCAL_MACHINE = 2

# Global injection hooks for testing on non-Windows platforms
_powershell_runner: Optional[Callable[[str, int], str]] = None
_cred_backend = None


class FILETIME(ctypes.Structure):
    _fields_ = [
        ("dwLowDateTime", wintypes.DWORD),
        ("dwHighDateTime", wintypes.DWORD),
    ]


class CREDENTIALW(ctypes.Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", ctypes.c_void_p),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


def is_windows() -> bool:
    """Return True if running on a Windows system."""
    return os.name == "nt" or sys.platform.startswith("win")


def _get_advapi32():
    if not is_windows():
        return None
    try:
        return ctypes.WinDLL("advapi32", use_last_error=True)
    except (AttributeError, OSError):
        return None


def powershell(cmd: str, timeout: int = 10) -> str:
    """Run a PowerShell snippet and return stdout decoded as UTF-8.
    
    Returns an empty string on error, timeout, or if run on a non-Windows host.
    """
    if _powershell_runner is not None:
        return _powershell_runner(cmd, timeout)
    if not is_windows():
        return ""
    command = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;" + cmd
    no_window = {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}
    try:
        res = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True,
            timeout=timeout,
            check=False,
            **no_window,
        )
        return res.stdout.decode("utf-8", errors="replace")
    except (OSError, subprocess.SubprocessError):
        return ""


def cred_read(target: str) -> Optional[str]:
    """Read secret string for target from Windows Credential Manager.
    
    Returns the secret as string if found, or None. No-op on non-Windows.
    """
    if _cred_backend is not None:
        return _cred_backend.cred_read(target)
    if not is_windows():
        return None
    advapi32 = _get_advapi32()
    if advapi32 is None:
        return None

    CredReadW = advapi32.CredReadW
    CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    CredReadW.restype = wintypes.BOOL

    CredFree = advapi32.CredFree
    CredFree.argtypes = [ctypes.c_void_p]
    CredFree.restype = None

    p_cred = ctypes.POINTER(CREDENTIALW)()
    if not CredReadW(target, CRED_TYPE_GENERIC, 0, ctypes.byref(p_cred)):
        return None
    try:
        if not p_cred:
            return None
        cred = p_cred.contents
        size = cred.CredentialBlobSize
        blob = cred.CredentialBlob
        if not blob or size == 0:
            return ""
        raw = ctypes.string_at(blob, size)
        return raw.decode("utf-16-le", errors="replace")
    finally:
        CredFree(p_cred)


def cred_write(target: str, secret: str) -> bool:
    """Write secret string for target to Windows Credential Manager (CRED_TYPE_GENERIC, CRED_PERSIST_LOCAL_MACHINE).
    
    Secret is encoded as UTF-16LE. Returns True on success, False otherwise. No-op on non-Windows.
    """
    if _cred_backend is not None:
        return _cred_backend.cred_write(target, secret)
    if not is_windows():
        return False
    advapi32 = _get_advapi32()
    if advapi32 is None:
        return False

    CredWriteW = advapi32.CredWriteW
    CredWriteW.argtypes = [ctypes.POINTER(CREDENTIALW), wintypes.DWORD]
    CredWriteW.restype = wintypes.BOOL

    blob = secret.encode("utf-16-le")
    buf = ctypes.create_string_buffer(blob, len(blob))

    cred = CREDENTIALW()
    cred.Flags = 0
    cred.Type = CRED_TYPE_GENERIC
    cred.TargetName = target
    cred.Comment = None
    cred.CredentialBlobSize = len(blob)
    cred.CredentialBlob = ctypes.cast(buf, ctypes.c_void_p)
    cred.Persist = CRED_PERSIST_LOCAL_MACHINE
    cred.AttributeCount = 0
    cred.Attributes = None
    cred.TargetAlias = None
    cred.UserName = None

    res = CredWriteW(ctypes.pointer(cred), 0)
    return bool(res)


def cred_delete(target: str) -> bool:
    """Delete target credential from Windows Credential Manager.
    
    Returns True if deleted or existed, False otherwise. No-op on non-Windows.
    """
    if _cred_backend is not None:
        return _cred_backend.cred_delete(target)
    if not is_windows():
        return False
    advapi32 = _get_advapi32()
    if advapi32 is None:
        return False

    CredDeleteW = advapi32.CredDeleteW
    CredDeleteW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD]
    CredDeleteW.restype = wintypes.BOOL

    res = CredDeleteW(target, CRED_TYPE_GENERIC, 0)
    return bool(res)
