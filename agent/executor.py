# Doris 查询执行 - 待实现（Phase 1）
import os
import pymysql
from dotenv import load_dotenv

load_dotenv()

def execute(sql: str) -> dict:
    try:
        conn = pymysql.connect(
            host=os.getenv("DORIS_HOST", "localhost"),
            port=int(os.getenv("DORIS_PORT", "9030")),
            user=os.getenv("DORIS_USER", "root"),
            password=os.getenv("DORIS_PASSWORD", ""),
            database=os.getenv("DORIS_DATABASE", "ads"),
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
        )
        with conn.cursor() as cursor:
            cursor.execute(sql)
            rows = cursor.fetchmany(int(os.getenv("DORIS_MAX_ROWS", "100")))
        conn.close()
        return {"data": rows, "row_count": len(rows), "error": None}
    except Exception as e:
        return {"data": [], "row_count": 0, "error": str(e)}
