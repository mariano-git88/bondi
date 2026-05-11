"""
main.py — FastAPI app del recommender.

Endpoints públicos:
  POST /chat          — conversación con tool use. Stateless: cliente manda
                        history completa. Loggea cada turn en SQLite.
  GET  /healthz       — healthcheck.
  GET  /catalog/stats — info del catálogo cargado.

Endpoints admin (uso del backoffice):
  POST /admin/reload  — recargar engine + curation desde disco (post rebuild).
                        Protegido por header X-Admin-Token contra BONDI_ADMIN_PASS.
  POST /admin/feedback — guardar feedback operador sobre un turn.
  GET  /admin/turns   — listar conversaciones recientes.
  GET  /admin/turn/{id} — detalle de un turn + feedback.

Setup en startup:
  1. Cargar products.jsonl → dict por handle.
  2. Cargar FAISS index + metadata → SearchEngine.
  3. Construir docs_by_id desde el metadata (para get_doc).
  4. Cargar curation.json.
  5. init_db().

Run local:
    uvicorn backend.main:app --reload --port 8000
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from embeddings.search import SearchEngine

from . import agent, db

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bondi")

app = FastAPI(title="Bondi — Suprabond AR Recommender", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =====================================================================
# State global cargado al startup
# =====================================================================

_engine: SearchEngine | None = None
_products_by_handle: dict[str, dict] = {}
_docs_by_id: dict[str, dict] = {}
_curation: dict = {}
_anthropic_api_key: str | None = None
_admin_pass: str | None = None


def _load_products() -> None:
    global _products_by_handle
    _products_by_handle = {}
    jsonl_path = Path("data/products.jsonl")
    if not jsonl_path.exists():
        log.error(f"No existe {jsonl_path}. Corré ingestion/ingest_shopify.py.")
        return
    with open(jsonl_path, encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            h = p.get("handle")
            if h:
                _products_by_handle[h] = p
    log.info(f"Productos cargados en memoria: {len(_products_by_handle)}")


def _load_engine() -> None:
    global _engine, _docs_by_id
    try:
        _engine = SearchEngine()
        log.info(f"SearchEngine: {_engine.index.ntotal} vectores.")
        _docs_by_id = {m.get("id"): m for m in _engine.metadata if m.get("id")}
        log.info(f"docs_by_id: {len(_docs_by_id)} entries")
    except FileNotFoundError as e:
        log.error(f"No se pudo cargar SearchEngine: {e}.")
        _engine = None
        _docs_by_id = {}


def _load_curation() -> None:
    global _curation
    _curation = agent.load_curation()
    log.info(f"Curation cargado: version={_curation.get('version')}, "
             f"hard_rules={len(_curation.get('hard_rules') or [])}, "
             f"faqs={len(_curation.get('faqs') or [])}")


@app.on_event("startup")
def _startup():
    global _anthropic_api_key, _admin_pass

    _anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not _anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY no presente — /chat va a fallar hasta configurarla.")

    if not os.environ.get("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY no presente — SearchEngine no puede embeber queries.")

    _admin_pass = os.environ.get("BONDI_ADMIN_PASS") or "admin"
    if _admin_pass == "admin":
        log.warning("BONDI_ADMIN_PASS no configurado — usando default inseguro 'admin'.")

    db.init_db()
    _load_products()
    _load_engine()
    _load_curation()


def _check_admin(token: str | None) -> None:
    if not token or not _admin_pass or not secrets.compare_digest(token, _admin_pass):
        raise HTTPException(401, "Token admin inválido.")


# =====================================================================
# Schemas
# =====================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    history: list[dict]
    tool_calls: list[dict]
    session_id: str
    turn_id: int | None = None


class FeedbackRequest(BaseModel):
    turn_id: int
    rating: str  # 'good', 'bad', 'flag'
    note: str | None = None
    operator: str | None = None


# =====================================================================
# Endpoints públicos
# =====================================================================

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "version": "0.2.0",
        "engine_loaded": _engine is not None,
        "products_loaded": len(_products_by_handle),
        "docs_loaded": len(_docs_by_id),
        "curation_version": _curation.get("version"),
        "hard_rules": len(_curation.get("hard_rules") or []),
        "anthropic_key": bool(_anthropic_api_key),
    }


@app.get("/catalog/stats")
def catalog_stats():
    if not _products_by_handle:
        raise HTTPException(503, "Catálogo no cargado.")
    vendors: dict[str, int] = {}
    for p in _products_by_handle.values():
        v = (p.get("vendor") or "(sin vendor)").strip()
        vendors[v] = vendors.get(v, 0) + 1
    by_source: dict[str, int] = {}
    for m in (_engine.metadata if _engine else []):
        st = m.get("source_type") or "(unknown)"
        by_source[st] = by_source.get(st, 0) + 1
    return {
        "total_products": len(_products_by_handle),
        "vendors": vendors,
        "index_total": _engine.index.ntotal if _engine else 0,
        "index_by_source": by_source,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    if _engine is None:
        raise HTTPException(503, "Search engine no inicializado.")
    if not _anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY no configurada.")

    session_id = req.session_id or str(uuid.uuid4())
    messages: list[dict] = list(req.history) + [
        {"role": "user", "content": req.message}
    ]

    # Recargar curation en cada chat (hot reload tras edición en backoffice).
    curation_now = agent.load_curation()
    ctx = {
        "engine": _engine,
        "products_by_handle": _products_by_handle,
        "docs_by_id": _docs_by_id,
        "curation": curation_now,
    }

    try:
        response_text, tool_calls, hard_rules_version = agent.responder(
            messages, ctx, _anthropic_api_key
        )
    except Exception as exc:
        log.exception("Error en agent.responder")
        raise HTTPException(500, f"Agent error: {exc}")

    # Log persistente del turn (no falla el chat si el insert falla).
    turn_id = None
    try:
        turn_id = db.log_turn(
            session_id=session_id,
            user_msg=req.message,
            assistant_msg=response_text,
            tool_calls=tool_calls,
            hard_rules_version=hard_rules_version,
        )
    except Exception:
        log.exception("Falló el log_turn")

    return ChatResponse(
        response=response_text,
        history=messages,
        tool_calls=tool_calls,
        session_id=session_id,
        turn_id=turn_id,
    )


# =====================================================================
# Endpoints admin (backoffice)
# =====================================================================

@app.post("/admin/reload")
def admin_reload(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    _load_products()
    _load_engine()
    _load_curation()
    return {
        "reloaded": True,
        "products": len(_products_by_handle),
        "docs": len(_docs_by_id),
        "curation_version": _curation.get("version"),
        "index_total": _engine.index.ntotal if _engine else 0,
    }


@app.get("/admin/turns")
def admin_turns(limit: int = 100, session_id: str | None = None,
                x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return {"turns": db.list_recent_turns(limit=limit, session_id=session_id)}


@app.get("/admin/turn/{turn_id}")
def admin_turn(turn_id: int, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    t = db.get_turn(turn_id)
    if not t:
        raise HTTPException(404, f"Turn {turn_id} no encontrado.")
    return t


@app.post("/admin/feedback")
def admin_feedback(req: FeedbackRequest, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    feedback_id = db.save_feedback(
        turn_id=req.turn_id,
        rating=req.rating,
        note=req.note,
        operator=req.operator,
    )
    return {"feedback_id": feedback_id}


@app.get("/admin/db/stats")
def admin_db_stats(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return db.stats()


# =====================================================================
# Frontend estático
# =====================================================================
#
# El backend sirve el chat público en GET / (frontend/index.html) cuando
# la carpeta frontend/ está presente. Esto permite un deploy unificado en
# Render: un solo Web Service hostea API + chat. Si no querés exponer el
# chat por la misma URL que la API, comentá este bloque.

_frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if _frontend_dir.exists() and (_frontend_dir / "index.html").exists():
    @app.get("/", include_in_schema=False)
    def frontend_root():
        return FileResponse(str(_frontend_dir / "index.html"))

    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")
    log.info(f"Frontend montado: {_frontend_dir}")
else:
    log.info(f"Frontend no encontrado en {_frontend_dir} — endpoints API solamente.")
