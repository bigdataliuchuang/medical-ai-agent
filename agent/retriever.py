import os
from pymilvus import connections, Collection
from sentence_transformers import SentenceTransformer
from dotenv import load_dotenv
from indexer.schema_parser import load_all_schemas, SchemaDoc

load_dotenv()

MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION = os.getenv("MILVUS_COLLECTION", "medical_schema")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema")

_model = None


def _get_model():
    global _model
    if _model is None:
        _model = SentenceTransformer(EMBEDDING_MODEL)
    return _model


def retrieve(question: str, top_k: int = 3) -> list:
    try:
        return _retrieve_milvus(question, top_k)
    except Exception:
        return _fallback_all()


def _retrieve_milvus(question: str, top_k: int) -> list:
    model = _get_model()
    q_embedding = model.encode([question]).tolist()

    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)
    col = Collection(COLLECTION)
    col.load()

    results = col.search(
        data=q_embedding,
        anns_field="embedding",
        param={"metric_type": "COSINE", "params": {"nprobe": 16}},
        limit=top_k,
        output_fields=["table_name", "text"],
    )

    connections.disconnect("default")

    docs = []
    seen = set()
    for hit in results[0]:
        table = hit.entity.get("table_name")
        if table not in seen:
            seen.add(table)
            docs.append(SchemaDoc(
                table_name=table,
                full_text=hit.entity.get("text", ""),
            ))
    return docs


def _fallback_all() -> list:
    return load_all_schemas(SCHEMA_DIR)
