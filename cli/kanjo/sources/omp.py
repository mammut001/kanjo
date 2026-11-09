"""OMP coding agent: ``~/.omp/agent/sessions/<encoded-cwd>/<timestamp>_<id>.jsonl``."""

from __future__ import annotations

from typing import List, Optional, Tuple

from . import pi as _pi
from .base import Session

AGENT = "omp"


def roots() -> List[str]:
    return _pi.roots(agent=AGENT)


def discover(dirs: Optional[List[str]] = None) -> List[Tuple[str, Optional[str]]]:
    return _pi.discover(dirs=dirs, agent=AGENT)


def parse_file(path: str, subagent_of: Optional[str] = None) -> Session:
    return _pi.parse_file(path, subagent_of=subagent_of, agent=AGENT)
