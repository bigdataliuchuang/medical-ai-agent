from __future__ import annotations

from pathlib import Path

from ai_data_agent.graphrag.chunking import build_metadata_chunks
from ai_data_agent.graphrag.ingest import MetadataIngestionService
from ai_data_agent.graphrag.milvus_store import FIELD_ORDER, MilvusMetadataStore
from ai_data_agent.metadata import MetadataRepository


ROOT = Path(__file__).resolve().parents[1]


class StubEmbeddingClient:
    def __init__(self) -> None:
        self.texts: list[str] = []
        self.calls: list[list[str]] = []

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        self.texts.extend(texts)
        return [[float(index), 0.1, 0.2] for index, _ in enumerate(texts)]


class StubCollection:
    def __init__(self) -> None:
        self.inserted = None
        self.flushed = False

    def insert(self, data):
        self.inserted = data

    def flush(self):
        self.flushed = True


def test_build_metadata_chunks_includes_tables_metrics_rules_and_graphs() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")

    chunks = build_metadata_chunks(repo)
    doc_types = {chunk.doc_type for chunk in chunks}

    assert {"table", "field", "metric", "dq_rule", "schema_graph", "lineage"}.issubset(doc_types)
    assert any(chunk.table_name == "dwd.dwd_visit" for chunk in chunks)
    assert any(chunk.metric_name == "antitumor_drug_amount" for chunk in chunks)


def test_ingestion_service_embeds_and_writes_chunks_to_store() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    embedding = StubEmbeddingClient()
    collection = StubCollection()
    store = MilvusMetadataStore(collection)
    service = MetadataIngestionService(repo, embedding, store)

    report = service.ingest()

    assert report.chunk_count == report.inserted_count
    assert report.chunk_count == len(embedding.texts)
    assert collection.inserted is not None
    assert len(collection.inserted) == len(FIELD_ORDER)
    assert collection.flushed is True


def test_ingestion_service_batches_embedding_requests() -> None:
    repo = MetadataRepository.load(ROOT / "metadata")
    embedding = StubEmbeddingClient()
    collection = StubCollection()
    store = MilvusMetadataStore(collection)
    service = MetadataIngestionService(repo, embedding, store, batch_size=5)

    report = service.ingest()

    assert report.chunk_count == report.inserted_count
    assert len(embedding.calls) > 1
    assert all(len(call) <= 5 for call in embedding.calls)
