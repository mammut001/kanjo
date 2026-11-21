#!/usr/bin/env python3
"""Compare independently generated Mac, Windows, and TUI parity goldens."""
import json
from itertools import islice
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent
MISSING = object()


def shared_keys(mac, other):
  if isinstance(mac, dict) and isinstance(other, dict):
    keys = sorted(mac.keys() & other.keys())
    for key in keys:
      yield key, mac[key], other.get(key)
  else:
    yield None, mac, other


def compare(mac, other, path="$", shared_only=False):
  if isinstance(mac, dict) and isinstance(other, dict):
    keys = sorted(mac.keys() & other.keys()) if shared_only else sorted(mac.keys() | other.keys())
    for key in keys:
      if shared_only and key not in other:
        continue
      yield from compare(
        mac.get(key, MISSING),
        other.get(key, MISSING) if isinstance(other, dict) else MISSING,
        f"{path}[{json.dumps(key, ensure_ascii=False)}]",
        shared_only=shared_only,
      )
  elif isinstance(mac, list) and isinstance(other, list):
    for i in range(max(len(mac), len(other))):
      yield from compare(
        mac[i] if i < len(mac) else MISSING,
        other[i] if i < len(other) else MISSING,
        f"{path}[{i}]",
        shared_only=shared_only,
      )
  elif type(mac) is not type(other) or mac != other:
    def show(value):
      return '<missing>' if value is MISSING else repr(value)
    yield f"{path}: Mac {show(mac)}; Other {show(other)}"


def compare_pair(left_name, left, right_name, right, shared_only=False, limit=21):
  label = f"{left_name} vs {right_name}"
  differences = list(islice(compare(left, right, shared_only=shared_only), limit))
  if differences:
    print(f"=== {label} ===")
    print("\n".join(differences[:20]))
    if len(differences) > 20:
      print("Further differences omitted.")
    return 1
  n = len(left) if isinstance(left, dict) else 0
  print(f"{label}: parity goldens match ({n} scenarios).")
  return 0


def main():
  with (ROOT / 'mac.json').open() as f:
    mac = json.load(f)
  with (ROOT / 'windows.json').open() as f:
    windows = json.load(f)
  tui_path = ROOT / 'tui.json'
  code = compare_pair("Mac", mac, "Windows", windows, shared_only=False)

  if tui_path.is_file():
    with tui_path.open() as f:
      tui = json.load(f)
    code = max(code, compare_pair("Mac", mac, "TUI", tui, shared_only=True))

  return code


if __name__ == '__main__':
  sys.exit(main())