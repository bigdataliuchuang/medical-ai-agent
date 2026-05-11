"""Milvus-backed vector store for production metadata retrieval."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from ai_data_agent.graphrag.chunking import MetadataChunk


class MilvusStoreError(RuntimeError):
    """Raised when Milvus operations fail."""


class MilvusCollectionProtocol(Protocol):
    def insert(self, data: list[list[Any]]) -> Any:
        """Insert column-oriented Milvus data."""

    def flush(self) -> Any:
        """Flush pending writes."""

    def search(self, *args: Any, **kwargs: Any) -> Any:
        """Run vector search."""


@dataclass(frozen=True)
class VectorSearchResult:
    doc_id: str
    score: float
    content: str
    metadata: dict[str, str]


@dataclass(frozen=True)
class MilvusConnectionConfig:
    host: str
    port: int
    collection: str
    embedding_dimension: int
    alias: str = "medical_data_agent"


FIELD_ORDER = [
    "doc_id",
    "doc_type",
    "source_path",
    "layer",
    "business_domain",
    "table_name",
    "field_name",
    "metric_name",
    "content",
    "embedding",
]

VARCHAR_LENGTHS = {
    "doc_id": 64,
    "doc_type": 32,
    "source_path": 512,
    "layer": 32,
    "business_domain": 64,
    "table_name": 512,
    "field_name": 512,
    "metric_name": 128,
    "content": 8192,
}


class MilvusMetadataStore:
    def __init__(self, collection: MilvusCollectionProtocol, vector_field: str = "embedding"):
        self.collection = collection
        self.vector_field = vector_field

    def upsert_chunks(self, chunks: list[MetadataChunk], embeddings: list[list[float]]) -> int:
        if len(chunks) != len(embeddings):
            raise MilvusStoreError("Chunk count and embedding count must match.")
        if not chunks:
            return 0

        data = [
            [chunk.doc_id for chunk in chunks],
            [chunk.doc_type for chunk in chunks],
            [chunk.source_path for chunk in chunks],
            [chunk.layer or "" for chunk in chunks],
            [chunk.business_domain or "" for chunk in chunks],
            [chunk.table_name or "" for chunk in chunks],
            [chunk.field_name or "" for chunk in chunks],
            [chunk.metric_name or "" for chunk in chunks],
            [chunk.content for chunk in chunks],
            embeddings,
        ]
        self.collection.insert(data)
        self.collection.flush()
        return len(chunks)

    def search(self, query_embedding: list[float], top_k: int = 5) -> list[VectorSearchResult]:
        try:
            raw_results = self.collection.search(
                data=[query_embedding],
                anns_field=self.vector_field,
                param={"metric_type": "COSINE", "params": {"ef": 64}},
                limit=top_k,
                output_fields=[
                    "doc_id",
                    "doc_type",
                    "source_path",
                    "layer",
                    "business_domain",
                    "table_name",
                    "field_name",
                    "metric_name",
                    "content",
                ],
            )
        except Exception as exc:
            raise MilvusStoreError(f"Milvus search failed: {exc}") from exc

        hits = raw_results[0] if raw_results else []
        return [_result_from_hit(hit) for hit in hits]


class MilvusClientCollectionAdapter:
    """Adapt the MilvusClient API used by Milvus Lite to the collection protocol."""

    def __init__(self, client: Any, collection_name: str):
        self.client = client
        self.collection_name = collection_name

    def insert(self, data: list[list[Any]]) -> Any:
        rows = [
            {field: data[field_index][row_index] for field_index, field in enumerate(FIELD_ORDER)}
            for row_index in range(len(data[0]) if data else 0)
        ]
        if hasattr(self.client, "upsert"):
            return self.client.upsert(collection_name=self.collection_name, data=rows)
        return self.client.insert(collection_name=self.collection_name, data=rows)

    def flush(self) -> Any:
        flush = getattr(self.client, "flush", None)
        if callable(flush):
            return flush(collection_name=self.collection_name)
        return None

    def search(self, *args: Any, **kwargs: Any) -> Any:
        data = kwargs.get("data")
        limit = kwargs.get("limit", 5)
        output_fields = kwargs.get("output_fields")
        search_params = kwargs.get("param")
        raw_results = self.client.search(
            collection_name=self.collection_name,
            data=data,
            limit=limit,
            output_fields=output_fields,
            search_params=search_params,
        )
        return [[_ClientHit(hit) for hit in hits] for hits in raw_results]


class _ClientEntity:
    def __init__(self, entity: dict[str, Any]):
        self._entity = entity

    def get(self, key: str) -> Any:
        return self._entity.get(key)


class _ClientHit:
    def __init__(self, hit: dict[str, Any]):
        self.entity = _ClientEntity(hit.get("entity", hit))
        self.score = hit.get("distance", hit.get("score", 0.0))


def build_collection_schema(embedding_dimension: int) -> Any:
    """Build the production Milvus schema.

    The import is intentionally inside the function so unit tests that only
    validate local contracts do not require a Milvus client installation.
    """

    try:
        from pymilvus import CollectionSchema, DataType, FieldSchema
    except ModuleNotFoundError as exc:
        raise MilvusStoreError("pymilvus is required for production Milvus schema creation.") from exc

    fields = [
        FieldSchema(name="doc_id", dtype=DataType.VARCHAR, max_length=64, is_primary=True),
        FieldSchema(name="doc_type", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="source_path", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="layer", dtype=DataType.VARCHAR, max_length=32),
        FieldSchema(name="business_domain", dtype=DataType.VARCHAR, max_length=64),
        FieldSchema(name="table_name", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="field_name", dtype=DataType.VARCHAR, max_length=512),
        FieldSchema(name="metric_name", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="content", dtype=DataType.VARCHAR, max_length=8192),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=embedding_dimension),
    ]
    return CollectionSchema(
        fields=fields,
        description="Medical data governance metadata chunks for GraphRAG",
        enable_dynamic_field=False,
    )


def connect_collection(config: MilvusConnectionConfig, create_if_missing: bool = False) -> Any:
    """Connect to a production Milvus collection.

    `create_if_missing` is explicit because production startup should normally
    fail when the collection is absent; collection creation belongs to an
    operator-controlled ingestion/setup step.
    """

    try:
        from pymilvus import Collection, connections, utility
    except ModuleNotFoundError as exc:
        raise MilvusStoreError("pymilvus is required for production Milvus access.") from exc

    try:
        connections.connect(alias=config.alias, host=config.host, port=str(config.port))
        exists = utility.has_collection(config.collection, using=config.alias)
        if not exists and not create_if_missing:
            raise MilvusStoreError(f"Milvus collection does not exist: {config.collection}")
        if not exists:
            schema = build_collection_schema(config.embedding_dimension)
            collection = Collection(name=config.collection, schema=schema, using=config.alias)
            collection.create_index(
                field_name="embedding",
                index_params={
                    "index_type": "HNSW",
                    "metric_type": "COSINE",
                    "params": {"M": 16, "efConstruction": 200},
                },
            )
        else:
            collection = Collection(name=config.collection, using=config.alias)
        collection.load()
        return collection
    except MilvusStoreError:
        raise
    except Exception as exc:
        raise MilvusStoreError(f"Milvus collection connection failed: {exc}") from exc


def connect_lite_collection(
    uri: str,
    collection: str,
    embedding_dimension: int,
    create_if_missing: bool = False,
) -> MilvusClientCollectionAdapter:
    """Connect to a local Milvus Lite database through MilvusClient."""

    try:
        from pymilvus import MilvusClient
    except ModuleNotFoundError as exc:
        raise MilvusStoreError(
            "pymilvus[milvus-lite] is required for local Milvus Lite access."
        ) from exc

    try:
        client = MilvusClient(uri)
        exists = client.has_collection(collection)
        if not exists and not create_if_missing:
            raise MilvusStoreError(f"Milvus Lite collection does not exist: {collection}")
        if not exists:
            client.create_collection(
                collection_name=collection,
                dimension=embedding_dimension,
                primary_field_name="doc_id",
                id_type="string",
                vector_field_name="embedding",
                metric_type="COSINE",
                auto_id=False,
                enable_dynamic_field=True,
                max_length=VARCHAR_LENGTHS["doc_id"],
            )
        return MilvusClientCollectionAdapter(client, collection)
    except MilvusStoreError:
        raise
    except Exception as exc:
        raise MilvusStoreError(f"Milvus Lite collection connection failed: {exc}") from exc


def _result_from_hit(hit: Any) -> VectorSearchResult:
    entity = getattr(hit, "entity", None)
    getter = entity.get if entity is not None and hasattr(entity, "get") else lambda key: ""
    metadata = {
        "doc_type": getter("doc_type") or "",
        "source_path": getter("source_path") or "",
        "layer": getter("layer") or "",
        "business_domain": getter("business_domain") or "",
        "table_name": getter("table_name") or "",
        "field_name": getter("field_name") or "",
        "metric_name": getter("metric_name") or "",
    }
    return VectorSearchResult(
        doc_id=getter("doc_id") or "",
        score=float(getattr(hit, "score", getattr(hit, "distance", 0.0))),
        content=getter("content") or "",
        metadata=metadata,
    )
