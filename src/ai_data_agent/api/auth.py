"""API key authentication for the Data Agent API."""

from __future__ import annotations

from fastapi import HTTPException, Request


class APIKeyAuth:
    """FastAPI dependency for API key authentication."""

    def __init__(self, valid_keys: list[str], header_name: str = "X-API-Key"):
        self._valid_keys = set(valid_keys)
        self._header_name = header_name

    async def __call__(self, request: Request) -> str:
        key = request.headers.get(self._header_name)
        if not key:
            raise HTTPException(status_code=401, detail=f"Missing {self._header_name} header")
        if key not in self._valid_keys:
            raise HTTPException(status_code=401, detail="Invalid API key")
        return key
