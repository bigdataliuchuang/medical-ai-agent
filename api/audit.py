from fastapi import APIRouter, Query
from audit.logger import read_logs

router = APIRouter()


@router.get("/api/audit/logs")
def get_audit_logs(
    date: str = Query(default=None, description="日期 YYYY-MM-DD，默认今天"),
    user_id: str = Query(default=None, description="用户ID，可选"),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    return read_logs(date_str=date, user_id=user_id, page=page, page_size=page_size)
