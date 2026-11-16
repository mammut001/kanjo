"""Stable, privacy-preserving device identity for Kanjo family reports."""

from __future__ import annotations

import getpass
import hashlib
import os
import re
import secrets
import socket
import subprocess
import sys
import tempfile
from typing import Dict, Optional

from . import winsupport

_DEVICE_ID_RE = re.compile(r"^[0-9a-f]{16}$")
_IOPLATFORM_UUID_RE = re.compile(r'"IOPlatformUUID"\s*=\s*"([^"]+)"')


def device_os() -> str:
    """Return normalized OS identifier: 'macos', 'windows', or 'linux'."""
    if sys.platform == "darwin":
        return "macos"
    if winsupport.is_windows():
        return "windows"
    return "linux"


def _macos_machine_id() -> Optional[str]:
    try:
        proc = subprocess.run(
            ["/usr/sbin/ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        if proc.returncode != 0 or not proc.stdout:
            return None
        match = _IOPLATFORM_UUID_RE.search(proc.stdout)
        if match:
            val = match.group(1).strip()
            return val or None
    except (OSError, subprocess.SubprocessError):
        pass
    return None


def _linux_machine_id() -> Optional[str]:
    for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
        try:
            with open(path, "r", encoding="utf-8") as handle:
                val = handle.read().strip()
            if val:
                return val
        except OSError:
            continue
    return None


def _windows_machine_id() -> Optional[str]:
    try:
        import winreg  # type: ignore

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Cryptography",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "MachineGuid")
        if isinstance(val, str) and val.strip():
            return val.strip()
    except (ImportError, OSError):
        pass
    return None


def _machine_id() -> Optional[str]:
    os_name = device_os()
    if os_name == "macos":
        return _macos_machine_id()
    if os_name == "windows":
        return _windows_machine_id()
    return _linux_machine_id()


def _os_username() -> Optional[str]:
    try:
        user = getpass.getuser()
        if isinstance(user, str) and user.strip():
            return user.strip()
    except Exception:
        pass
    for env_key in ("USER", "USERNAME", "LOGNAME"):
        val = os.environ.get(env_key)
        if val and val.strip():
            return val.strip()
    return None


def _config_dir(config_dir: Optional[str] = None) -> str:
    return os.path.expanduser(
        config_dir or os.environ.get("KANJO_CONFIG_DIR") or winsupport.kanjo_config_dir()
    )


def _fallback_device_id(config_dir: Optional[str] = None) -> str:
    base = _config_dir(config_dir)
    path = winsupport.join(base, "device-id")
    try:
        with open(path, "r", encoding="utf-8") as handle:
            existing = handle.read().strip().lower()
        if _DEVICE_ID_RE.fullmatch(existing):
            return existing
    except OSError:
        pass

    dev_id = secrets.token_hex(8)
    tmp = None
    try:
        os.makedirs(base, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".device-id-", dir=base)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(dev_id + "\n")
        if not winsupport.is_windows():
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
        os.replace(tmp, path)
    except OSError:
        pass
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass
    return dev_id


def resolve_device_id(config_dir: Optional[str] = None) -> str:
    """Return a stable 16-hex-char device id, never exposing raw machine id or username."""
    mid = _machine_id()
    user = _os_username()
    if mid and user:
        raw = f"kanjo-device-v1:{mid}:{user}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:16]
    return _fallback_device_id(config_dir=config_dir)


def sanitize_device_name(name: str) -> str:
    """Sanitize device name to <= 40 printable chars with '@' replaced by '-'."""
    cleaned = "".join(ch for ch in name.replace("@", "-") if ch.isprintable())
    cleaned = cleaned.strip()[:40].strip()
    return cleaned or "device"


def resolve_device_name(device_name: Optional[str] = None, config=None) -> str:
    """Resolve short device name from CLI flag, config, or short hostname."""
    candidate = None
    if isinstance(device_name, str) and device_name.strip():
        candidate = device_name
    elif config is not None and isinstance(getattr(config, "family_device_name", None), str):
        cfg_name = config.family_device_name
        if cfg_name.strip():
            candidate = cfg_name
    if candidate is None:
        try:
            host = socket.gethostname()
            if host:
                candidate = host.split(".", 1)[0]
        except OSError:
            candidate = None
    return sanitize_device_name(candidate or "device")


def build_device_info(
    device_name: Optional[str] = None,
    config=None,
    config_dir: Optional[str] = None,
) -> Dict[str, str]:
    """Build the top-level 'device' object for kanjo-family-report."""
    return {
        "id": resolve_device_id(config_dir=config_dir),
        "name": resolve_device_name(device_name=device_name, config=config),
        "os": device_os(),
    }
