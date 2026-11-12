"""Windows platform support for Kanjo.

Provides PowerShell execution, Windows Credential Manager integration (advapi32),
the Recycle Bin (shell32), the per-user directory conventions (``%APPDATA%``,
``%LOCALAPPDATA%``, ``%USERPROFILE%``) and the list of agents that have no
Windows build. All credential, powershell and shell routines safely no-op or
return None/False on non-Windows, so callers never need to branch themselves.
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import ntpath
import os
import posixpath
import re
import subprocess
import sys
from typing import Callable, Iterable, Optional


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


# ---- per-user directories ------------------------------------------------------------
# Node/Python CLIs keep their dot-dirs in %USERPROFILE% on Windows, which is what
# os.path.expanduser("~") already returns there; the helpers below cover the macOS
# conventions that have a documented Windows counterpart (Electron/desktop apps and
# XDG-style data dirs) plus Kanjo's own directories.

def user_profile() -> Optional[str]:
    """``%USERPROFILE%`` (or the home directory when it is unset)."""
    if not is_windows():
        return None
    return os.environ.get("USERPROFILE") or os.path.expanduser("~")


def app_data() -> Optional[str]:
    """``%APPDATA%`` (``C:\\Users\\<user>\\AppData\\Roaming``), the config counterpart."""
    if not is_windows():
        return None
    return os.environ.get("APPDATA") or join(user_profile() or "", "AppData", "Roaming")


def local_app_data() -> Optional[str]:
    """``%LOCALAPPDATA%`` (``C:\\Users\\<user>\\AppData\\Local``)."""
    if not is_windows():
        return None
    return os.environ.get("LOCALAPPDATA") or join(user_profile() or "", "AppData", "Local")


def temp_dirs() -> list:
    """``%TEMP%`` / ``%TMP%`` / ``%LOCALAPPDATA%\\Temp``, deduplicated, in that order.

    Empty on non-Windows; callers keep their POSIX prefixes.
    """
    if not is_windows():
        return []
    out = []
    seen = set()
    for value in (os.environ.get("TEMP"), os.environ.get("TMP"),
                  join(local_app_data() or "", "Temp")):
        if value:
            key = value.replace("/", "\\").rstrip("\\").lower()
            if key and key not in seen:
                seen.add(key)
                out.append(value)
    return out


def join(path: str, *parts: str) -> str:
    """``os.path.join`` using the rules of ``path``'s own flavour.

    ``os.path.join`` uses the host separator, which turns a Windows base into
    ``C:\\Users\\x/kanjo`` on the macOS test machine, and a POSIX base into
    ``/Users/x\\kanjo`` on Windows. Both are wrong for the *other* flavour, and
    identical to ``os.path.join`` for the host's own paths.
    """
    if is_windows_path(path):
        return ntpath.join(path, *parts)
    if path.startswith("/"):
        return posixpath.join(path, *parts)
    return os.path.join(path, *parts)


def app_support_dir(name: str) -> str:
    """Windows counterpart of ``~/Library/Application Support/<name>``: ``%APPDATA%\\<name>``.

    Electron and .NET desktop apps keep roaming settings there. POSIX hosts keep
    the macOS path, so callers get the same string they always did off Windows.
    """
    if is_windows():
        return join(app_data() or "", name)
    return os.path.expanduser(os.path.join("~/Library/Application Support", name))


def local_data_dir(name: str) -> str:
    """Windows counterpart of ``~/.local/share/<name>``: ``%LOCALAPPDATA%\\<name>``.

    Tools that follow ``XDG_DATA_HOME`` on POSIX keep their data under
    ``%LOCALAPPDATA%`` on Windows (OpenCode is the documented exception and passes
    its own ``%USERPROFILE%\\.local\\share\\opencode`` path instead).
    """
    if is_windows():
        return join(local_app_data() or "", name)
    return os.path.expanduser(os.path.join("~/.local/share", name))


def config_dir(name: str) -> str:
    """Windows counterpart of ``~/.config/<name>``: ``%APPDATA%\\<name>`` (``%USERPROFILE%\\.config``
    for tools that use that dot-dir themselves).

    Same string as before off Windows, so nothing changes on macOS/Linux.
    """
    if is_windows():
        return join(app_data() or "", name)
    return os.path.expanduser(os.path.join("~/.config", name))


# Kanjo's own directories. ``KANJO_CONFIG_DIR`` / ``KANJO_DATA_DIR`` / ``KANJO_CACHE_DIR``
# override all of them on every platform.
def kanjo_config_dir() -> str:
    """``%APPDATA%\\kanjo`` on Windows, ``~/.config/kanjo`` elsewhere."""
    return config_dir("kanjo")


def kanjo_data_dir() -> str:
    """``%LOCALAPPDATA%\\kanjo\\data`` on Windows, ``~/.local/share/kanjo`` elsewhere."""
    if is_windows():
        return join(local_app_data() or "", "kanjo", "data")
    return os.path.expanduser(os.path.join("~/.local/share/kanjo"))


def kanjo_cache_dir() -> str:
    """``%LOCALAPPDATA%\\kanjo\\cache`` on Windows, ``~/.cache/kanjo`` (or XDG) elsewhere."""
    if is_windows():
        return join(local_app_data() or "", "kanjo", "cache")
    base = os.environ.get("XDG_CACHE_HOME") or os.path.join(os.path.expanduser("~"), ".cache")
    return os.path.join(base, "kanjo")


# ---- path helpers ---------------------------------------------------------------------
_WIN_ABS = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")


def expanduser(path: str) -> str:
    """``os.path.expanduser`` with the Windows profile as ``~``.

    On Windows ``os.path.expanduser`` already uses ``USERPROFILE``; doing it here
    keeps the Windows branches testable from another OS (where ``~`` would resolve
    to the machine running the tests instead) and normalizes the separators of the
    remainder, so ``~/.claude/projects`` becomes ``C:\\Users\\a\\.claude\\projects``.
    """
    if not is_windows():
        return os.path.expanduser(path)
    if path == "~":
        return user_profile() or path
    if path.startswith(("~/", "~\\")):
        parts = [p for p in re.split(r"[\\/]+", path[2:]) if p]
        return join(user_profile() or "", *parts) if parts else (user_profile() or path)
    return path


def is_windows_path(path: Optional[str]) -> bool:
    """Windows absolute path (``C:\\...``, ``C:/...``, ``\\\\server\\share``)."""
    return bool(_WIN_ABS.match(path or ""))


def normcase_key(path: str) -> str:
    """Case-folded, slash-normalized key for comparing Windows paths.

    Drive letters and path components are case-insensitive on Windows, and Node
    tools write both ``C:\\Users\\x`` and ``c:/users/x``. POSIX paths are returned
    unchanged so every existing comparison keeps its exact meaning.
    """
    if not path:
        return path or ""
    if not is_windows_path(path):
        return path
    return ntpath.normcase(path.replace("/", "\\"))


def same_path(a: Optional[str], b: Optional[str]) -> bool:
    """True when both names refer to the same path (case-insensitively on Windows)."""
    if a is None or b is None:
        return a is b
    return normcase_key(a) == normcase_key(b)


def is_subpath(child: Optional[str], parent: Optional[str]) -> bool:
    """True when ``child`` is ``parent`` or inside it, on POSIX and Windows paths alike."""
    if not child or not parent:
        return False
    c, p = normcase_key(child), normcase_key(parent)
    p = p.rstrip("\\/")
    if c == p:
        return True
    return c.startswith(p + "/") or c.startswith(p + "\\")


def abspath(path: str) -> str:
    """``os.path.abspath`` that keeps a Windows path a Windows path.

    ``os.path.abspath`` on macOS would turn ``C:\\Users\\a`` into
    ``/current/dir/C:\\Users\\a``; the Windows spelling is returned instead so the
    same code path works when scanning Windows-style paths from another OS. A
    POSIX path on a Windows host is left POSIX for the same reason.
    """
    if is_windows_path(path):
        return ntpath.abspath(path)
    if path.startswith("/"):
        return posixpath.normpath(path)
    return os.path.abspath(path)


def normpath(path: str) -> str:
    """``os.path.normpath`` using the rules of the path's own flavour.

    A POSIX path keeps ``/`` even when the process runs on Windows (logs and test
    fixtures from another machine), and ``\\`` is only a separator in Windows paths.
    """
    if is_windows_path(path):
        return ntpath.normpath(path)
    if path.startswith("/"):
        return posixpath.normpath(path)
    return os.path.normpath(path)


def relpath(path: str, start: Optional[str] = None) -> str:
    """``os.path.relpath`` for either path flavour."""
    if is_windows_path(path) or is_windows_path(start or ""):
        return ntpath.relpath(path, start)
    return os.path.relpath(path, start) if start else os.path.relpath(path)


def dirname(path: str) -> str:
    """``os.path.dirname`` for either path flavour."""
    return ntpath.dirname(path) if is_windows_path(path) else posixpath.dirname(path)


def basename(path: str) -> str:
    """``os.path.basename`` for either path flavour."""
    return ntpath.basename(path) if is_windows_path(path) else posixpath.basename(path)


def path_parts(path: str) -> list:
    """Path components, using the separators of the path's own flavour.

    A POSIX path keeps ``\\`` inside a component (it is a legal file-name
    character there); a Windows path splits on both separators.
    """
    if is_windows_path(path):
        return [p for p in re.split(r"[\\/]+", ntpath.normpath(path)) if p]
    return [p for p in path.split("/") if p]


def abspath_of(path: str, cwd: Optional[str] = None) -> str:
    """Absolute path using the rules of the path's own flavour.

    A POSIX path stays POSIX even when the process runs on Windows (logs from
    another machine, test fixtures); a Windows path stays Windows everywhere.
    """
    if is_windows_path(path):
        return ntpath.abspath(path)
    if path.startswith("/"):
        return posixpath.normpath(path)
    return os.path.abspath(path)


# ---- agents without a Windows build ---------------------------------------------------
# Sources whose desktop app / CLI is macOS-only (or whose Windows storage location is
# unknown): skipped silently on Windows instead of crashing, and listed in
# ``kanjo paths --json`` under ``windows_unsupported``.
WINDOWS_UNSUPPORTED = {
    "grok_bot": "Grok Bot is a macOS-only desktop app",
    "qoderwork": "QoderWork is a macOS-only desktop app",
    "qoder_ide": "Qoder IDE is not available on Windows",
    "mimocode": "MiMo Code is a macOS-only desktop app",
}


def unsupported_agents() -> dict:
    """``agent -> reason`` when running on Windows, empty elsewhere."""
    return dict(WINDOWS_UNSUPPORTED) if is_windows() else {}


def is_supported(agent: str) -> bool:
    """False on Windows for agents that have no Windows build."""
    return not (is_windows() and agent in WINDOWS_UNSUPPORTED)


def supported_agents(agents: Iterable[str]) -> list:
    """Drop the unsupported agents, keeping the input order."""
    return [agent for agent in agents if is_supported(agent)]


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


# ---- Recycle Bin (shell32!SHFileOperationW) ------------------------------------------
# disk clean moves files there instead of ~/.Trash on Windows. Same flags Explorer
# uses: undoable (FOF_ALLOWUNDO), no confirmation UI, silent, errors not shown.
FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400
FOF_WANTNUKEWARNING = 0x4000
RECYCLE_BIN = "Recycle Bin"


class SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", ctypes.c_uint),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", ctypes.c_void_p),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


# Injection hook so the Recycle Bin path can be tested on macOS/Linux.
_shell_backend = None


def recycle_list(paths) -> str:
    """The ``pFrom`` payload for ``SHFileOperationW``: paths separated and ended by NUL.

    ``SHFileOperationW`` takes a list, not one path: every item is NUL-terminated and
    the list ends with a second NUL.
    """
    return "\0".join(str(p) for p in paths if str(p)) + "\0\0"


def recycle(paths) -> Optional[int]:
    """Move ``paths`` to the Recycle Bin. Returns 0 on success, an error code otherwise.

    ``None`` on non-Windows (the caller then uses the Trash). The code is the
    ``SHFileOperationW`` return value; a non-zero value means nothing is guaranteed
    to have moved. Never raises: a locked or in-use file is reported by the caller.
    """
    if _shell_backend is not None:
        return _shell_backend.recycle(paths)
    if not is_windows():
        return None
    shell32 = _get_shell32()
    if shell32 is None:
        return -1
    items = [str(p) for p in paths if str(p)]
    if not items:
        return 0
    # pFrom is a double-NUL-terminated list. A plain str would stop at the first
    # NUL, so build an explicit wide buffer.
    buf = ctypes.create_unicode_buffer(recycle_list(items))
    op = SHFILEOPSTRUCTW()
    op.hwnd = None
    op.wFunc = FO_DELETE
    op.pFrom = ctypes.cast(buf, wintypes.LPCWSTR)
    op.pTo = None
    op.fFlags = FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI
    op.fAnyOperationsAborted = False
    op.hNameMappings = None
    op.lpszProgressTitle = None
    try:
        SHFileOperationW = shell32.SHFileOperationW
        SHFileOperationW.argtypes = [ctypes.POINTER(SHFILEOPSTRUCTW)]
        SHFileOperationW.restype = ctypes.c_int
        code = int(SHFileOperationW(ctypes.byref(op)))
    except (AttributeError, OSError, ValueError):
        return -1
    if code == 0 and op.fAnyOperationsAborted:
        return 0x4C7  # ERROR_CANCELLED: the shell stopped part-way
    return code


def _get_shell32():
    if not is_windows():
        return None
    try:
        return ctypes.WinDLL("shell32", use_last_error=True)
    except (AttributeError, OSError):
        return None
