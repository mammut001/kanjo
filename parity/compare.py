#!/usr/bin/env python3
"""Compare independently generated Mac and Windows parity goldens."""
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
MISSING = object()


def compare(mac, windows, path="$"):
    if isinstance(mac, dict) and isinstance(windows, dict):
        for key in sorted(mac.keys() | windows.keys()):
            yield from compare(mac.get(key, MISSING), windows.get(key, MISSING), f"{path}.{key}")
    elif isinstance(mac, list) and isinstance(windows, list):
        for i in range(max(len(mac), len(windows))):
            yield from compare(mac[i] if i < len(mac) else MISSING,
                               windows[i] if i < len(windows) else MISSING, f"{path}[{i}]")
    elif type(mac) is not type(windows) or mac != windows:
        def show(value):
            return '<missing>' if value is MISSING else repr(value)
        yield f"{path}: Mac {show(mac)}; Windows {show(windows)}"


def main():
    with (ROOT / 'mac.json').open() as f:
        mac = json.load(f)
    with (ROOT / 'windows.json').open() as f:
        windows = json.load(f)
    differences = list(compare(mac, windows))
    if differences:
        print('\n'.join(differences))
        return 1
    print(f"Parity goldens match ({len(mac)} scenarios).")
    return 0


if __name__ == '__main__':
    sys.exit(main())
