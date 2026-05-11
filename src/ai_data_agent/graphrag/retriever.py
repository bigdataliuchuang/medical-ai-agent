"""GraphRAG metadata retrieval orchestration."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from threading import Lock

from ai_data_agent.graphrag.embedding import EmbeddingClient
from ai_data_agent.graphrag.graph import SchemaGraphRetriever
from ai_data_agent.graphrag.milvus_store import MilvusMetadataStore, VectorSearchResult

logger = logging.getLogger(__name__)

_DEFAULT_CACHE_TTL_S = 300  # 5 minutes
_DEFAULT_CACHE_MAX_SIZE = 128


@dataclass(frozen=True)
class RetrievalContext:
    query: str
    vector_results: list[VectorSearchResult]
    related_tables: dict[str, list[str]]
    lineage_matches: dict[str, list[dict]]


class _SearchCache:
    """Thread-safe LRU-ish cache with TTL for retrieval results."""

    def __init__(
        self, ttl_s: float = _DEFAULT_CACHE_TTL_S, max_size: int = _DEFAULT_CACHE_MAX_SIZE
    ):
        self._ttl_s = ttl_s
        self._max_size = max_size
        self._store: dict[tuple[str, int], tuple[float, RetrievalContext]] = {}
        self._lock = Lock()

    def get(self, key: tuple[str, int]) -> RetrievalContext | None:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            ts, ctx = entry
            if time.monotonic() - ts > self._ttl_s:
                del self._store[key]
                return None
            return ctx

    def put(self, key: tuple[str, int], value: RetrievalContext) -> None:
        with self._lock:
            if len(self._store) >= self._max_size:
                oldest_key = min(self._store, key=lambda k: self._store[k][0])
                del self._store[oldest_key]
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()


class GraphRagRetriever:
    def __init__(
        self,
        embedding_client: EmbeddingClient,
        store: MilvusMetadataStore,
        graph_retriever: SchemaGraphRetriever,
        *,
        cache_ttl_s: float = _DEFAULT_CACHE_TTL_S,
    ):
        self.embedding_client = embedding_client
        self.store = store
        self.graph_retriever = graph_retriever
        self._cache = _SearchCache(ttl_s=cache_ttl_s)

    def search_metadata(self, query: str, top_k: int = 5) -> RetrievalContext:
        cache_key = (query, top_k)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("Cache hit for query: %s", query[:80])
            return cached

        embeddings = self.embedding_client.embed_texts([query])
        if len(embeddings) != 1:
            raise RuntimeError("Embedding client must return exactly one query embedding.")
        vector_results = self.store.search(embeddings[0], top_k=top_k)

        if not vector_results:
            logger.warning("Vector search returned 0 results for query: %s", query[:80])

        table_names = sorted(
            {
                table
                for result in vector_results
                for table in result.metadata.get("table_name", "").split(",")
                if table
            }
        )
        related_tables = {table: self.graph_retriever.related_tables(table) for table in table_names}
        lineage_matches = {
            table: self.graph_retriever.find_lineage(table)
            for table in table_names
            if self.graph_retriever.find_lineage(table)
        }
        result = RetrievalContext(
            query=query,
            vector_results=vector_results,
            related_tables=related_tables,
            lineage_matches=lineage_matches,
        )
        self._cache.put(cache_key, result)
        return result

    def clear_cache(self) -> None:
        """Evict all cached retrieval results."""
        self._cache.clear()
