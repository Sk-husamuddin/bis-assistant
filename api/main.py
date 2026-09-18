import os
import sys
import pathlib

# Make `bis-assistant` runnable from either C:\sih2026 or C:\sih2026\bis-assistant
# When uvicorn is launched from the repo root, `api` is not on sys.path.
# This block adds the project root to sys.path so `import agent.*` works.
_THIS_DIR = pathlib.Path(__file__).resolve().parent
_PROJECT_ROOT = _THIS_DIR.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from agent.graph import run_query
from api.speak import router as speak_router
from api.transcribe import router as transcribe_router

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = FastAPI(title="BIS Intelligent Assistant", version="1.0.0")

app.include_router(speak_router)
app.include_router(transcribe_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=3, description="Natural language question about BIS standards/schemes")
    target_language: str = Field(default="en", pattern="^(en|hi|te|ta)$")

class QueryResponse(BaseModel):
    answer: str
    translated_answer: str | None = None
    target_language: str = "en"
    citations: list[dict]
    query_type: str
    used_live_fallback: bool

@app.get("/health")
def health():
    return {"status": "ok"}

@app.post("/query", response_model=QueryResponse)
def query_endpoint(req: QueryRequest):
    result = run_query(req.query.strip(), target_language=req.target_language)
    return {
        "answer": result.get("answer", ""),
        "translated_answer": result.get("translated_answer"),
        "target_language": req.target_language,
        "citations": result.get("citations", []),
        "query_type": result.get("query_type", "standard_lookup"),
        "used_live_fallback": bool(result.get("used_live_fallback", False)),
    }

# Frontend — TypeScript Vite dashboard (frontend/dist) takes precedence, fallback to legacy static/index.html
FRONTEND_DIST = pathlib.Path(__file__).parent.parent / "frontend" / "dist"
STATIC_DIR = pathlib.Path(__file__).parent.parent / "static"

# mount built assets (Vite emits /assets/*) — must be before catch-all
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIST / "assets")), name="frontend-assets")

@app.get("/")
def serve_index():
    # prefer new TS dashboard
    for cand in [FRONTEND_DIST / "index.html", STATIC_DIR / "index.html"]:
        if cand.exists():
            return FileResponse(str(cand), media_type="text/html")
    return {"message": "BIS Assistant API — POST /query"}

# audio cache for precached demo mp3s (Phase 1: 6 files, Phase 2: 24) — mounted now per Q2
AUDIO_CACHE_DIR = pathlib.Path(__file__).parent.parent / "static" / "audio_cache"
AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/audio_cache", StaticFiles(directory=str(AUDIO_CACHE_DIR)), name="audio-cache")

# legacy tester still available at /static and /legacy
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/legacy", StaticFiles(directory=str(STATIC_DIR), html=True), name="legacy")
