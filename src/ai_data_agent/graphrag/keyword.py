"""Lightweight keyword retrieval for metadata exact-match recall."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Iterable

from ai_data_agent.graphrag.chunking import MetadataChunk, build_metadata_chunks
from ai_data_agent.graphrag.milvus_store import VectorSearchResult
from ai_data_agent.metadata import MetadataRepository

_TOKEN_RE = re.compile(r"[a-zA-Z0-9_.]+|[\u4e00-\u9fff]+")
_EXACT_METADATA_FIELDS = ("table_name", "field_name", "metric_name", "doc_id")


@dataclass(frozen=True)
class _IndexedChunk:
    chunk: MetadataChunk
    tokens: Counter[str]
    length: int
    exact_text: str


class KeywordMetadataIndex:
    """Small BM25-style index over curated metadata chunks.

    This is intentionally local and dependency-free. Its job is not to replace
    vector search; it catches exact identifiers that embeddings can miss, then
    GraphRAG fuses both result sets.
    """

    def __init__(self, chunks: Iterable[MetadataChunk]):
        self._chunks = [_index_chunk(chunk) for chunk in chunks]
        self._doc_freq: Counter[str] = Counter()
        for indexed in self._chunks:
            self._doc_freq.update(indexed.tokens.keys())
        self._avg_len = (
            sum(indexed.length for indexed in self._chunks) / len(self._chunks)
            if self._chunks
            else 0.0
        )

    @classmethod
    def from_repository(cls, repository: MetadataRepository) -> "KeywordMetadataIndex":
        return cls(build_metadata_chunks(repository))

    def search(self, query: str, top_k: int = 5) -> list[VectorSearchResult]:
        query_tokens = _tokenize(query)
        if not query_tokens:
            return []

        scored: list[tuple[float, _IndexedChunk]] = []
        for indexed in self._chunks:
            score = _bm25_score(
                query_tokens=query_tokens,
                document=indexed,
                doc_freq=self._doc_freq,
                doc_count=len(self._chunks),
                avg_len=self._avg_len,
            )
            score += _exact_match_boost(query, indexed)
            if score > 0:
                scored.append((score, indexed))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [_to_result(indexed, score) for score, indexed in scored[:top_k]]


def _index_chunk(chunk: MetadataChunk) -> _IndexedChunk:
    metadata = chunk.metadata()
    token_text = " ".join([chunk.content, *metadata.values()])
    tokens = Counter(_tokenize(token_text))
    exact_text = " ".join(
        str(metadata.get(field, "")) for field in _EXACT_METADATA_FIELDS
    ).lower()
    return _IndexedChunk(
        chunk=chunk,
        tokens=tokens,
        length=sum(tokens.values()),
        exact_text=exact_text,
    )


def _tokenize(text: str) -> list[str]:
    return [match.group(0).lower() for match in _TOKEN_RE.finditer(text)]


def _bm25_score(
    query_tokens: list[str],
    document: _IndexedChunk,
    doc_freq: Counter[str],
    doc_count: int,
    avg_len: float,
) -> float:
    if doc_count == 0 or avg_len <= 0:
        return 0.0

    k1 = 1.5
    b = 0.75
    score = 0.0
    for token in set(query_tokens):
        freq = document.tokens.get(token, 0)
        if freq == 0:
            continue
        df = doc_freq.get(token, 0)
        idf = math.log(1 + (doc_count - df + 0.5) / (df + 0.5))
        denom = freq + k1 * (1 - b + b * document.length / avg_len)
        score += idf * (freq * (k1 + 1)) / denom
    return score


def _exact_match_boost(query: str, document: _IndexedChunk) -> float:
    query_lower = query.lower()
    boost = 0.0
    for token in _tokenize(query):
        if "." in token or "_" in token:
            if token in document.exact_text:
                boost += 8.0
    if query_lower and query_lower in document.chunk.content.lower():
        boost += 2.0
    return boost


def _to_result(indexed: _IndexedChunk, score: float) -> VectorSearchResult:
    chunk = indexed.chunk
    return VectorSearchResult(
        doc_id=chunk.doc_id,
        score=score,
        content=chunk.content,
        metadata=chunk.metadata(),
    )
