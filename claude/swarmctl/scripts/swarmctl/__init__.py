"""Portable minimalist swarm orchestration core (`swarmctl`)."""
from __future__ import annotations

from typing import Any

from .adapters import (
    ClaudeAdapter,
    TemplateAdapter,
    TurnRequest,
    TurnResult,
    format_prompt_delta,
    get_adapter,
)
from .store import SwarmStore, parse_mentions, validate_ident
from .worktree import WorkspaceManager

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "ClaudeAdapter",
    "SwarmStore",
    "TemplateAdapter",
    "TurnRequest",
    "TurnResult",
    "WorkspaceManager",
    "ensure_supervisor",
    "format_prompt_delta",
    "get_adapter",
    "parse_mentions",
    "run_supervisor_loop",
    "validate_ident",
]


def __getattr__(name: str) -> Any:
    if name in ("ensure_supervisor", "run_supervisor_loop"):
        from . import supervisor

        return getattr(supervisor, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
