"""Regression checks for runtime dependency constraints."""

from __future__ import annotations

from pathlib import Path


def test_marshmallow_is_pinned_below_v4_for_pymilvus_2_4():
    requirements = Path("requirements.txt").read_text(encoding="utf-8").splitlines()

    assert any(line.strip() == "marshmallow<4" for line in requirements)
