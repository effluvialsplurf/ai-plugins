"""Portable minimalist swarm orchestration core (`swarmctl`)."""
from __future__ import annotations

from .adapters import (
    ClaudeAdapter,
    TemplateAdapter,
    TurnRequest,
    TurnResult,
    format_prompt_delta,
    get_adapter,
)
from .store import SwarmStore, parse_mentions, validate_ident
from .supervisor import ensure_supervisor, run_supervisor_loop
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
