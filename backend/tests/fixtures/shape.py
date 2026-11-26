"""tests/fixtures/shape.py — Helper to assert API responses match contract fixture shapes.

Loads JSON fixtures from /contract/examples/<name>.json when present and
checks recursively that keys and Python types match.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CONTRACT_EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "contract" / "examples"


def load_fixture(filename: str) -> Any | None:
    """Load a fixture from /contract/examples/<filename>, or return None if absent."""
    path = CONTRACT_EXAMPLES_DIR / filename
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def assert_matches_shape(actual: Any, example: Any, path: str = "$") -> None:
    """Recursively verify that *actual* has the same keys and value types as *example*."""
    if example is None:
        return  # nullable in fixture; skip strict type check

    if isinstance(example, bool):
        assert isinstance(actual, bool), f"{path}: expected bool, got {type(actual).__name__}"
        return

    if isinstance(example, (int, float)) and not isinstance(actual, bool):
        assert isinstance(actual, (int, float)), (
            f"{path}: expected number, got {type(actual).__name__}"
        )
        return

    if isinstance(example, dict):
        assert isinstance(actual, dict), f"{path}: expected dict, got {type(actual).__name__}"
        for key, val in example.items():
            assert key in actual, f"{path}: missing key {key!r}"
            assert_matches_shape(actual[key], val, f"{path}.{key}")
        return

    if isinstance(example, list):
        assert isinstance(actual, list), f"{path}: expected list, got {type(actual).__name__}"
        if example and actual:
            assert_matches_shape(actual[0], example[0], f"{path}[0]")
        return

    assert isinstance(actual, type(example)), (
        f"{path}: expected {type(example).__name__}, got {type(actual).__name__}"
    )
