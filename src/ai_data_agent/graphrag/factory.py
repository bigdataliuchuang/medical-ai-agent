"""Factories for production GraphRAG dependencies."""

from __future__ import annotations

from ai_data_agent.config import DataAgentConfig
from ai_data_agent.graphrag.embedding import OpenAICompatibleEmbeddingClient
from ai_data_agent.graphrag.milvus_store import (
    MilvusConnectionConfig,
    MilvusMetadataStore,
    connect_collection,
    connect_lite_collection,
)


def build_embedding_client(config: DataAgentConfig) -> OpenAICompatibleEmbeddingClient:
    provider = str(config.require("embedding.provider")).lower()
    if provider not in {"openai", "openai-compatible"}:
        raise ValueError(f"Unsupported embedding provider for current production factory: {provider}")
    return OpenAICompatibleEmbeddingClient(
        base_url=_optional_value(config.raw.get("embedding", {}).get("base_url"), "https://api.openai.com/v1"),
        api_key=str(config.require("embedding.api_key")),
        model=str(config.require("embedding.model")),
    )


def build_milvus_store(config: DataAgentConfig, create_if_missing: bool = False) -> MilvusMetadataStore:
    milvus_mode = str(config.raw.get("milvus", {}).get("mode", "standalone")).lower()
    if milvus_mode == "lite":
        collection = connect_lite_collection(
            uri=str(config.require("milvus.uri")),
            collection=str(config.require("milvus.collection")),
            embedding_dimension=int(config.require("embedding.dimension")),
            create_if_missing=create_if_missing,
        )
        return MilvusMetadataStore(collection)

    milvus_config = MilvusConnectionConfig(
        host=str(config.require("milvus.host")),
        port=int(config.require("milvus.port")),
        collection=str(config.require("milvus.collection")),
        embedding_dimension=int(config.require("embedding.dimension")),
    )
    collection = connect_collection(milvus_config, create_if_missing=create_if_missing)
    return MilvusMetadataStore(collection)


def _optional_value(value: object, default: str) -> str:
    if value is None:
        return default
    text = str(value)
    if text.startswith("${") and text.endswith("}"):
        return default
    return text
