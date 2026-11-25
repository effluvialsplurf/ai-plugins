"""Portable minimalist swarm orchestration core (`swarmctl`)."""
from __future__ import annotations

from .store import SwarmStore, parse_mentions, validate_ident
from .worktree import WorkspaceManager

__version__ = "0.1.0"
__all__ = ["__version__", "SwarmStore", "WorkspaceManager", "parse_mentions", "validate_ident"]
