"""Module entrypoint (`python3 -m swarmctl`)."""
from __future__ import annotations

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
