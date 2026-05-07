"""
main.py — FastAPI app del recommender.

Endpoints:
  POST /chat       — conversación con tool use. Stateless: el cliente
                     manda la history completa en cada request.
  GET  /healthz    — healthcheck para Render / monitoring.
  GET  /catalog/stats — info del catálogo cargado (debugging).

Setup en startup:
  1. Cargar el JSONL → dict por handle (para get_product_details / compare).
  2. Cargar el FAISS index + metadata → SearchEngine.
  3. Validar ANTHROPIC_API_KEY presente.

Run local:
    uvicorn backend.main:app --reload --port 8000

Run prod (Render):
    uvicorn backend.main:app --host 0.0.0.0 --port $PORT
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from embeddings.search import SearchEngine

from . import agent

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("bondi")

app = FastAPI(title="Bondi — Suprabond AR Recommender", version="0.1.0")

# CORS abierto para MVP (el frontend va a estar en otro dominio).
# En producción ajustar a `allow_origins=["https://chat.suprabond.com", ...]`.
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
_anthropic_api_key: str | None = None


@app.on_event("startup")
def _startup():
    global _engine, _products_by_handle, _anthropic_api_key

    _anthropic_api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not _anthropic_api_key:
        log.warning("ANTHROPIC_API_KEY no presente — /chat va a fallar hasta configurarla.")

    if not os.environ.get("OPENAI_API_KEY"):
        log.warning("OPENAI_API_KEY no presente — el SearchEngine no va a poder embeber queries.")

    # Cargar JSONL.
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
    log.info(f"Cargados {len(_products_by_handle)} productos en memoria.")

    # Cargar FAISS index.
    try:
        _engine = SearchEngine()
        log.info(f"SearchEngine cargado: {_engine.index.ntotal} vectores.")
    except FileNotFoundError as e:
        log.error(f"No se pudo cargar SearchEngine: {e}. Corré embeddings/build_index.py.")
        _engine = None


# =====================================================================
# Schemas
# =====================================================================

class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list,
                                description="Lista de mensajes previos en formato Anthropic.")


class ChatResponse(BaseModel):
    response: str
    history: list[dict]
    tool_calls: list[dict]


# =====================================================================
# Endpoints
# =====================================================================

@app.get("/healthz")
def healthz():
    return {
        "status": "ok",
        "engine_loaded": _engine is not None,
        "products_loaded": len(_products_by_handle),
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
    return {
        "total_products": len(_products_by_handle),
        "vendors": vendors,
    }


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest) -> ChatResponse:
    if _engine is None:
        raise HTTPException(503, "Search engine no inicializado. Corré build_index.py.")
    if not _anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY no configurada.")

    # Construir historial Anthropic-style: history previo + nuevo user message.
    messages: list[dict] = list(req.history) + [
        {"role": "user", "content": req.message}
    ]

    ctx = {
        "engine": _engine,
        "products_by_handle": _products_by_handle,
    }

    try:
        response_text, tool_calls = agent.responder(messages, ctx, _anthropic_api_key)
    except Exception as exc:
        log.exception("Error en agent.responder")
        raise HTTPException(500, f"Agent error: {exc}")

    return ChatResponse(
        response=response_text,
        history=messages,
        tool_calls=tool_calls,
    )
