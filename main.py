from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from api.chat import router as chat_router
from api.dev import router as dev_router
from api.health import router as health_router
from api.index import router as index_router
from api.audit import router as audit_router
from api.semantic import router as semantic_router

FRONTEND_DIR = Path(__file__).parent / "frontend"

app = FastAPI(title="医疗数据治理 AI Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_origin_regex=r"https://.*\.app\.github\.dev",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(chat_router)
app.include_router(dev_router)
app.include_router(semantic_router)
app.include_router(index_router)
app.include_router(audit_router)

if FRONTEND_DIR.exists():
    @app.get("/", include_in_schema=False)
    async def serve_frontend():
        return FileResponse(FRONTEND_DIR / "index.html")
