"""Syntax smoke tests for the legacy FastAPI entrypoint."""

from __future__ import annotations

import py_compile
from pathlib import Path


def test_legacy_fastapi_files_compile():
    legacy_files = [Path("main.py"), *Path("agent").glob("*.py"), *Path("api").glob("*.py")]

    for path in legacy_files:
        py_compile.compile(str(path), doraise=True)
