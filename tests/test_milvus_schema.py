from __future__ import annotations

import pytest

from ai_data_agent.graphrag.milvus_store import build_collection_schema


def test_build_collection_schema_defines_primary_key_and_vector_field() -> None:
    pymilvus = pytest.importorskip("pymilvus")

    schema = build_collection_schema(1536)
    fields = {field.name: field for field in schema.fields}

    assert fields["doc_id"].is_primary is True
    assert fields["embedding"].dtype == pymilvus.DataType.FLOAT_VECTOR
    assert fields["embedding"].params["dim"] == 1536
