"""Metadata ingestion orchestration for Milvus."""

from __future__ import annotations

from dataclasses import dataclass

from ai_data_agent.graphrag.chunking import MetadataChunk, build_metadata_chunks
from ai_data_agent.graphrag.embedding import EmbeddingClient
from ai_data_agent.graphrag.milvus_store import MilvusMetadataStore
from ai_data_agent.metadata import MetadataRepository


@dataclass(frozen=True)
class IngestionReport:
    chunk_count: int
    inserted_count: int


class MetadataIngestionService:
    def __init__(
        self,
        repository: MetadataRepository,
        embedding_client: EmbeddingClient,
        store: MilvusMetadataStore,
        batch_size: int = 1,
    ):
        self.repository = repository
        self.embedding_client = embedding_client
        self.store = store
        self.batch_size = batch_size

    def build_chunks(self) -> list[MetadataChunk]:
        return build_metadata_chunks(self.repository)

    def ingest(self) -> IngestionReport:
        chunks = self.build_chunks()
        inserted = 0
        for start in range(0, len(chunks), self.batch_size):
            batch = chunks[start : start + self.batch_size]
            embeddings = self.embedding_client.embed_texts([chunk.content for chunk in batch])
            inserted += self.store.upsert_chunks(batch, embeddings)
        return IngestionReport(chunk_count=len(chunks), inserted_count=inserted)
