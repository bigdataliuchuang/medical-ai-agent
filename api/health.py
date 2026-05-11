import os
import pymysql
from fastapi import APIRouter
from dotenv import load_dotenv

load_dotenv()

router = APIRouter()


@router.get("/api/health")
def health():
    doris_status = "disconnected"
    try:
        conn = pymysql.connect(
            host=os.getenv("DORIS_HOST", "localhost"),
            port=int(os.getenv("DORIS_PORT", "9030")),
            user=os.getenv("DORIS_USER", "root"),
            password=os.getenv("DORIS_PASSWORD", ""),
            database=os.getenv("DORIS_DATABASE", "ads"),
            charset="utf8mb4",
            connect_timeout=5,
        )
        conn.close()
        doris_status = "connected"
    except Exception:
        pass

    return {"status": "ok", "doris": doris_status}
