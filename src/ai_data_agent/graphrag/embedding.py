"""Embedding provider contracts and OpenAI-compatible implementation."""

from __future__ import annotations

import json
import urllib.request
from dataclasses import dataclass
from typing import Protocol


class EmbeddingError(RuntimeError):
    """Raised when embedding generation fails."""


class EmbeddingClient(Protocol):
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for all input texts."""


@dataclass(frozen=True)
class OpenAICompatibleEmbeddingClient:
    base_url: str
    api_key: str
    model: str
    timeout_seconds: int = 60

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        request = urllib.request.Request(
            url=self.base_url.rstrip("/") + "/embeddings",
            data=json.dumps({"model": self.model, "input": texts}).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            raise EmbeddingError(f"Embedding request failed: {exc}") from exc

        data = payload.get("data")
        if not isinstance(data, list):
            raise EmbeddingError("Embedding response missing data list.")
        embeddings = [item.get("embedding") for item in sorted(data, key=lambda item: item.get("index", 0))]
        if any(not isinstance(vector, list) for vector in embeddings):
            raise EmbeddingError("Embedding response contains invalid vectors.")
        return embeddings
