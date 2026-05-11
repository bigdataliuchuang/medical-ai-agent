import os
import asyncio
import pymysql
from dotenv import load_dotenv

load_dotenv()

DORIS_CONFIG = dict(
    host=os.getenv("DORIS_HOST", "localhost"),
    port=int(os.getenv("DORIS_PORT", "9030")),
    user=os.getenv("DORIS_USER", "root"),
    password=os.getenv("DORIS_PASSWORD", ""),
    database=os.getenv("DORIS_DATABASE", "ads"),
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
    connect_timeout=10,
    read_timeout=30,
)
MAX_ROWS = int(os.getenv("DORIS_MAX_ROWS", "100"))


def execute(sql: str) -> dict:
    sql_stripped = sql.strip().rstrip(";")
    if not sql_stripped.upper().startswith("SELECT"):
        return {"data": [], "row_count": 0, "error": "仅允许 SELECT 查询"}

    try:
        conn = pymysql.connect(**DORIS_CONFIG)
        with conn.cursor() as cursor:
            cursor.execute(sql_stripped)
            rows = cursor.fetchmany(MAX_ROWS)
        conn.close()
        truncated = len(rows) >= MAX_ROWS
        return {"data": rows, "row_count": len(rows), "error": None, "truncated": truncated}
    except Exception as e:
        return {"data": [], "row_count": 0, "error": str(e), "truncated": False}


async def execute_async(sql: str) -> dict:
    return await asyncio.to_thread(execute, sql)
