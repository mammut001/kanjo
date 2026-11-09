"""CodeBuddy coding agent: ``~/.codebuddy/projects/<slug>/<session>.jsonl``."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import workbuddy as _wb
from .base import Session

AGENT = "codebuddy"


def roots() -> List[str]:
    return _wb.roots(agent=AGENT)


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    return _wb.discover(dirs=dirs, agent=AGENT)


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    return _wb.parse_file(path, subagent_of=subagent_of, agent=AGENT)
