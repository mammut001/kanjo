"""Qoder CN (Domestic edition)."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import qodercli as _qc
from .base import Session

AGENT = "qodercli_cn"


def roots() -> List[str]:
    return _qc.roots(agent=AGENT)


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    return _qc.discover(dirs=dirs, agent=AGENT)


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    return _qc.parse_file(path, subagent_of=subagent_of, agent=AGENT)
