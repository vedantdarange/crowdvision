"""app/container.py — Dependency injection wiring.

Repositories and services are wired here. Later phases fill this in.
Nothing is instantiated at import time — call wire() after create_app().
"""
from __future__ import annotations


def wire() -> None:
    """Wire repositories and services. Called from create_app()."""
    # B1+ phases fill this in.
    pass
