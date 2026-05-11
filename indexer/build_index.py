import os
import sys
from pymilvus import connections, Collection, CollectionSchema, FieldSchema, DataType, utility
from dotenv import load_dotenv
from indexer.schema_parser import load_all_schemas

load_dotenv()

MILVUS_HOST = os.getenv("MILVUS_HOST", "localhost")
MILVUS_PORT = os.getenv("MILVUS_PORT", "19530")
COLLECTION = os.getenv("MILVUS_COLLECTION", "medical_schema")
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
SCHEMA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "schema")


def build_index(schema_dir: str = None):
    schema_dir = schema_dir or SCHEMA_DIR

    print(f"Loading embedding model: {EMBEDDING_MODEL}")
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise RuntimeError(
            "sentence-transformers is not installed in the lightweight runtime. "
            "Install it before rebuilding the local Milvus index."
        ) from exc

    model = SentenceTransformer(EMBEDDING_MODEL)

    print(f"Loading schemas from: {schema_dir}")
    schemas = load_all_schemas(schema_dir)
    if not schemas:
        print("No schemas found.")
        return

    # 准备文本和向量
    texts = []
    tables = []
    for doc in schemas:
        texts.append(doc.full_text)
        tables.append(doc.table_name)
        for q in doc.sample_questions:
            texts.append(q)
            tables.append(doc.table_name)

    print(f"Encoding {len(texts)} documents...")
    embeddings = model.encode(texts, show_progress_bar=True).tolist()
    dim = len(embeddings[0])

    # 连接 Milvus
    print(f"Connecting to Milvus {MILVUS_HOST}:{MILVUS_PORT}")
    connections.connect(host=MILVUS_HOST, port=MILVUS_PORT)

    # 删除旧 collection
    if utility.has_collection(COLLECTION):
        utility.drop_collection(COLLECTION)
        print(f"Dropped existing collection: {COLLECTION}")

    # 创建 collection
    fields = [
        FieldSchema(name="id", dtype=DataType.INT64, is_primary=True, auto_id=True),
        FieldSchema(name="table_name", dtype=DataType.VARCHAR, max_length=128),
        FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=4096),
        FieldSchema(name="embedding", dtype=DataType.FLOAT_VECTOR, dim=dim),
    ]
    schema = CollectionSchema(fields, description="Medical schema embeddings")
    col = Collection(COLLECTION, schema)

    # 插入数据
    col.insert([tables, texts, embeddings])
    col.flush()
    print(f"Inserted {len(texts)} documents into {COLLECTION}")

    # 创建索引
    col.create_index(
        field_name="embedding",
        index_params={"metric_type": "COSINE", "index_type": "IVF_FLAT", "params": {"nlist": 128}},
    )
    col.load()
    print("Index built and loaded successfully.")

    connections.disconnect("default")
    print("Done.")


if __name__ == "__main__":
    build_index()
