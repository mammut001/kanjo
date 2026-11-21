#!/usr/bin/env python3
"""Localization correctness check for Mac / Windows / iOS strings and the TUI.

Verifies:
  1. Every key used in Swift/C#/Python sources exists in all required languages
  2. Format specifiers match across languages (count, type, order; positional OK)
  3. No key is defined twice in one .strings file
  4. .strings files parse (escaped quotes, semicolons, comments)
  5. Lists keys defined but never referenced (report only; does not delete)

Windows reads the same
``ui/Sources/KanjoCore/Resources/{en,zh-Hans,fr}.lproj/Localizable.strings``
(see ``Kanjo.Core.csproj``). iOS has no separate table — it links KanjoCore.
Windows-only overrides live in ``WindowsL10n.cs`` and must cover en/zh-Hans/fr.
The TUI (``cli/kanjo/tui/i18n.py``) only ships ``en`` / ``zh``.

Exit code 0 on success, 1 on any hard error. Unused keys are printed to stdout
and do not fail the check.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import OrderedDict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple

LANGS = ("en", "zh-Hans", "fr")
# Matches the conversion set Windows L10n.ToNetFormat accepts (see L10n.cs).
FORMAT_SPEC = re.compile(
    r"%(?:(\d+)\$)?[-+0#]*\d*(?:\.\d+)?(lld|ld|d|i|u|f|g|s|@|%)"
)
# Python str.format field names used by the TUI.
PY_FIELD = re.compile(r"(?<!\{)\{([a-zA-Z_][a-zA-Z0-9_]*)\}")

SWIFT_TR = re.compile(r'L10n\.tr\(\s*"([^"]+)"')
SWIFT_L = re.compile(r'(?<![\w.])L\(\s*"([^"]+)"')
CS_TR = re.compile(r'(?:L10n|WindowsL10n)\.Tr\(\s*"([^"]+)"')
CS_TRL = re.compile(r'(?:L10n|WindowsL10n)\.TrL\(\s*[^,]+,\s*"([^"]+)"')
CS_LT = re.compile(r'\bL\.T\(\s*"([^"]+)"')
# Ternary / switch / labelKey string literals that look like localization keys.
# Segments may start with a digit (e.g. settings.background_refresh.30s).
KEY_LITERAL = re.compile(
    r'"([a-z][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9][a-zA-Z0-9_]*)+)"'
)
TUI_T = re.compile(r"""\bt\(\s*['"]([^'"]+)['"]""")
TUI_DYNAMIC_PREFIX = re.compile(
    r"""\bt\(\s*['"]([a-z][a-zA-Z0-9_.]*)['"]\s*\+"""
)


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def strings_path(root: Path, lang: str) -> Path:
    return (
        root
        / "ui"
        / "Sources"
        / "KanjoCore"
        / "Resources"
        / f"{lang}.lproj"
        / "Localizable.strings"
    )


def parse_strings_file(path: Path) -> Tuple[OrderedDict, List[str], Optional[str]]:
    """Parse OpenStep ``.strings``. Returns (map, duplicate_keys, parse_error)."""
    text = path.read_text(encoding="utf-8")
    result: OrderedDict = OrderedDict()
    duplicates: List[str] = []
    i = 0
    n = len(text)

    def skip_trivia() -> None:
        nonlocal i
        while i < n:
            c = text[i]
            if c.isspace() or c == "\ufeff":
                i += 1
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "/":
                while i < n and text[i] != "\n":
                    i += 1
                continue
            if c == "/" and i + 1 < n and text[i + 1] == "*":
                i += 2
                while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                    i += 1
                i = min(i + 2, n)
                continue
            break

    def read_quoted() -> str:
        nonlocal i
        # Caller guarantees text[i] == '"'
        i += 1
        out: List[str] = []
        while i < n:
            c = text[i]
            if c == "\\" and i + 1 < n:
                nxt = text[i + 1]
                i += 2
                mapping = {
                    "n": "\n",
                    "t": "\t",
                    "r": "\r",
                    '"': '"',
                    "\\": "\\",
                    "'": "'",
                }
                if nxt == "u" and i + 4 <= n:
                    try:
                        out.append(chr(int(text[i : i + 4], 16)))
                        i += 4
                        continue
                    except ValueError:
                        out.append(nxt)
                        continue
                out.append(mapping.get(nxt, nxt))
                continue
            if c == '"':
                i += 1
                break
            out.append(c)
            i += 1
        return "".join(out)

    while True:
        skip_trivia()
        if i >= n:
            break
        if text[i] != '"':
            return result, duplicates, f"{path}: parse stuck at offset {i}: {text[i:i+60]!r}"
        key = read_quoted()
        skip_trivia()
        if i >= n or text[i] != "=":
            return result, duplicates, f"{path}: expected '=' after key {key!r}"
        i += 1
        skip_trivia()
        if i >= n or text[i] != '"':
            return result, duplicates, f"{path}: expected value for key {key!r}"
        value = read_quoted()
        skip_trivia()
        if i < n and text[i] == ";":
            i += 1
        if key in result:
            duplicates.append(key)
        result[key] = value
    return result, duplicates, None


def normalize_spec_types(format_string: str) -> Tuple[str, ...]:
    """Return ordered type tokens for printf-style placeholders.

    Types: int (d/i/u/ld/lld), str (@/s), float (f/g). ``%%`` is ignored.
    Positional ``%2$@`` reorder the sequence; otherwise order of appearance wins.
    """
    items: List[Tuple[Optional[int], str]] = []
    for match in FORMAT_SPEC.finditer(format_string):
        conv = match.group(2)
        if conv == "%":
            continue
        pos = int(match.group(1)) if match.group(1) else None
        if conv in ("d", "i", "u", "ld", "lld"):
            typ = "int"
        elif conv in ("@", "s"):
            typ = "str"
        else:
            typ = "float"
        items.append((pos, typ))
    if any(pos is not None for pos, _ in items):
        ordered = sorted(
            ((pos if pos is not None else idx + 1), typ)
            for idx, (pos, typ) in enumerate(items)
        )
        return tuple(typ for _, typ in ordered)
    return tuple(typ for _, typ in items)


def parse_windows_overrides(path: Path) -> Dict[str, Dict[str, str]]:
    """Extract ``WindowsL10n`` override tables: key -> {lang: value}."""
    text = path.read_text(encoding="utf-8")
    overrides: Dict[str, Dict[str, str]] = {}
    # Split on top-level ["key"] = new(...) blocks inside Overrides.
    for match in re.finditer(
        r'\["([^"]+)"\]\s*=\s*new\s*\(StringComparer\.Ordinal\)\s*\{(.*?)\n\s*\},',
        text,
        re.S,
    ):
        key = match.group(1)
        body = match.group(2)
        table: Dict[str, str] = {}
        for lang_match in re.finditer(
            r'\["([^"]+)"\]\s*=\s*"((?:\\.|[^"\\])*)"', body
        ):
            lang = lang_match.group(1)
            raw = lang_match.group(2)
            value = (
                raw.replace("\\\\", "\0")
                .replace("\\n", "\n")
                .replace("\\t", "\t")
                .replace('\\"', '"')
                .replace("\0", "\\")
            )
            table[lang] = value
        overrides[key] = table
    return overrides


def collect_source_keys(root: Path) -> Tuple[Set[str], Set[str]]:
    """Return (direct_api_keys, all_key_shaped_literals_matching_catalog_later)."""
    direct: Set[str] = set()
    literals: Set[str] = set()

    swift_roots = [
        root / "ui" / "Sources",
        root / "ios" / "Kanjo",
    ]
    for base in swift_roots:
        if not base.exists():
            continue
        for path in base.rglob("*.swift"):
            content = path.read_text(encoding="utf-8", errors="replace")
            direct.update(SWIFT_TR.findall(content))
            direct.update(SWIFT_L.findall(content))
            literals.update(KEY_LITERAL.findall(content))

    cs_root = root / "windows" / "src"
    if cs_root.exists():
        for path in cs_root.rglob("*.cs"):
            content = path.read_text(encoding="utf-8", errors="replace")
            direct.update(CS_TR.findall(content))
            direct.update(CS_TRL.findall(content))
            direct.update(CS_LT.findall(content))
            literals.update(KEY_LITERAL.findall(content))

    # Only dotted keys are localization keys (filters ternary false positives
    # like "active" / "manual" picked up near L10n calls).
    direct = {k for k in direct if "." in k}
    return direct, literals


def collect_tui_keys(root: Path) -> Tuple[Set[str], Set[str]]:
    """Return (literal t() keys, dynamic prefixes like 'range.')."""
    used: Set[str] = set()
    prefixes: Set[str] = set()
    tui_dir = root / "cli" / "kanjo" / "tui"
    for path in tui_dir.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        used.update(TUI_T.findall(content))
        prefixes.update(TUI_DYNAMIC_PREFIX.findall(content))
    return used, prefixes


def load_tui_strings(root: Path) -> Dict[str, Dict[str, str]]:
    sys.path.insert(0, str(root / "cli"))
    from kanjo.tui.i18n import _STRINGS  # type: ignore

    return {lang: dict(table) for lang, table in _STRINGS.items()}


class CheckResult:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.unused_app: List[str] = []
        self.unused_tui: List[str] = []
        self.unused_windows_overrides: List[str] = []

    def fail(self, msg: str) -> None:
        self.errors.append(msg)


def run_checks(root: Optional[Path] = None) -> CheckResult:
    root = root or repo_root()
    result = CheckResult()

    tables: Dict[str, OrderedDict] = {}
    for lang in LANGS:
        path = strings_path(root, lang)
        if not path.is_file():
            result.fail(f"missing strings file: {path}")
            continue
        parsed, duplicates, err = parse_strings_file(path)
        if err:
            result.fail(err)
            continue
        for dup in duplicates:
            result.fail(f"{lang}: duplicate key {dup!r} (later definition wins silently)")
        tables[lang] = parsed

    if len(tables) != len(LANGS):
        return result

    en, zh, fr = tables["en"], tables["zh-Hans"], tables["fr"]
    for lang, table in (("zh-Hans", zh), ("fr", fr)):
        missing = sorted(set(en) - set(table))
        extra = sorted(set(table) - set(en))
        if missing:
            result.fail(f"{lang} missing keys: {', '.join(missing)}")
        if extra:
            result.fail(f"{lang} has keys not in en: {', '.join(extra)}")

    for key in sorted(set(en) & set(zh) & set(fr)):
        expected = normalize_spec_types(en[key])
        for lang, table in (("zh-Hans", zh), ("fr", fr)):
            got = normalize_spec_types(table[key])
            if got != expected:
                result.fail(
                    f"specifier mismatch for {key!r}: en={expected} "
                    f"{lang}={got} | en={en[key]!r} | {lang}={table[key]!r}"
                )

    overrides_path = root / "windows" / "src" / "Kanjo.Core" / "WindowsL10n.cs"
    overrides = parse_windows_overrides(overrides_path) if overrides_path.is_file() else {}
    for key, table in sorted(overrides.items()):
        for lang in LANGS:
            if lang not in table:
                result.fail(f"WindowsL10n override {key!r} missing language {lang}")
        if all(lang in table for lang in LANGS):
            expected = normalize_spec_types(table["en"])
            for lang in ("zh-Hans", "fr"):
                got = normalize_spec_types(table[lang])
                if got != expected:
                    result.fail(
                        f"WindowsL10n specifier mismatch for {key!r}: "
                        f"en={expected} {lang}={got}"
                    )

    defined = set(en) | set(overrides)
    direct, literals = collect_source_keys(root)
    # Literals only count as "used" when they are real catalog / override keys
    # (avoids treating random dotted identifiers as localization keys).
    used = set(direct) | (literals & defined)

    missing_used = sorted(k for k in direct if k not in defined)
    if missing_used:
        result.fail(
            "keys used in Swift/C# sources missing from Localizable.strings "
            f"and WindowsL10n: {', '.join(missing_used)}"
        )

    for key in sorted(k for k in used if k not in overrides):
        for lang in LANGS:
            if key not in tables[lang]:
                result.fail(f"used key {key!r} missing in {lang}")

    result.unused_app = sorted(k for k in en if k not in used)
    result.unused_windows_overrides = sorted(k for k in overrides if k not in used)

    # --- TUI ---
    try:
        tui = load_tui_strings(root)
    except Exception as exc:  # pragma: no cover - import wiring
        result.fail(f"failed to load TUI i18n: {exc}")
        return result

    if "en" not in tui or "zh" not in tui:
        result.fail("TUI i18n must define 'en' and 'zh' tables")
        return result

    en_t, zh_t = tui["en"], tui["zh"]
    if set(en_t) != set(zh_t):
        only_en = sorted(set(en_t) - set(zh_t))
        only_zh = sorted(set(zh_t) - set(en_t))
        if only_en:
            result.fail(f"TUI zh missing keys: {', '.join(only_en)}")
        if only_zh:
            result.fail(f"TUI en missing keys: {', '.join(only_zh)}")

    for key in sorted(set(en_t) & set(zh_t)):
        pe = set(PY_FIELD.findall(en_t[key]))
        pz = set(PY_FIELD.findall(zh_t[key]))
        if pe != pz:
            result.fail(
                f"TUI placeholder mismatch for {key!r}: en={sorted(pe)} zh={sorted(pz)}"
            )

    tui_used, prefixes = collect_tui_keys(root)
    # Also count any catalog key that appears as a string literal in TUI sources
    # (covers ternaries like t("a" if x else "b", lang)).
    tui_dir = root / "cli" / "kanjo" / "tui"
    for path in tui_dir.rglob("*.py"):
        if path.name == "i18n.py":
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        for lit in KEY_LITERAL.findall(content):
            if lit in en_t:
                tui_used.add(lit)
        # Bare single-segment TUI keys ("more", "loading", …).
        for lit in re.findall(r"""['"]([a-z][a-z0-9_]*)['"]""", content):
            if lit in en_t:
                tui_used.add(lit)

    # Expand dynamic prefixes (e.g. t("range." + value)).
    for prefix in prefixes:
        tui_used.update(k for k in en_t if k.startswith(prefix))
        if prefix in tui_used and prefix not in en_t:
            tui_used.discard(prefix)

    missing_tui = sorted(
        k for k in tui_used
        if k not in en_t and k not in prefixes and not k.endswith(".")
    )
    if missing_tui:
        result.fail(f"TUI keys used in code missing from i18n.py: {', '.join(missing_tui)}")

    result.unused_tui = sorted(k for k in en_t if k not in tui_used)
    return result


def format_report(result: CheckResult) -> str:
    lines: List[str] = []
    if result.errors:
        lines.append(f"L10n check FAILED ({len(result.errors)} error(s)):")
        for err in result.errors:
            lines.append(f"  - {err}")
    else:
        lines.append("L10n check OK.")
    lines.append("")
    lines.append(f"Unused Localizable.strings keys ({len(result.unused_app)}):")
    for key in result.unused_app:
        lines.append(f"  {key}")
    if result.unused_windows_overrides:
        lines.append(
            f"Unused WindowsL10n overrides ({len(result.unused_windows_overrides)}):"
        )
        for key in result.unused_windows_overrides:
            lines.append(f"  {key}")
    lines.append(f"Unused TUI keys ({len(result.unused_tui)}):")
    for key in result.unused_tui:
        lines.append(f"  {key}")
    return "\n".join(lines) + "\n"


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=None,
        help="Repository root (default: parent of scripts/)",
    )
    parser.add_argument(
        "--quiet-unused",
        action="store_true",
        help="Do not print the unused-key lists",
    )
    args = parser.parse_args(argv)
    result = run_checks(args.root)
    if result.errors:
        print(format_report(result), end="")
        return 1
    if args.quiet_unused:
        print("L10n check OK.")
    else:
        print(format_report(result), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
