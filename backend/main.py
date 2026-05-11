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
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, Header, HTTPException, UploadFile
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


class PublicFeedbackRequest(BaseModel):
    """Feedback enviado por usuarios públicos desde el frontend del chat.

    No requiere auth admin. Se valida que el turn_id exista. Se loggea
    con operator='public' para distinguirlo del feedback interno.
    """
    turn_id: int
    rating: str  # 'good' o 'bad' nada más (no flag desde público)
    note: str | None = Field(default=None, max_length=500)


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


@app.post("/feedback")
def public_feedback(req: PublicFeedbackRequest):
    """Feedback público (sin auth) que el frontend del chat envía al
    clickear 👍 / 👎 en una respuesta. Validamos que el turn exista y
    que el rating sea uno de los permitidos para el público."""
    if req.rating not in ("good", "bad"):
        raise HTTPException(400, "rating debe ser 'good' o 'bad'.")
    if not db.get_turn(req.turn_id):
        raise HTTPException(404, f"turn_id {req.turn_id} no existe.")
    feedback_id = db.save_feedback(
        turn_id=req.turn_id,
        rating=req.rating,
        note=req.note,
        operator="public",
    )
    return {"feedback_id": feedback_id}


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
def admin_turns(
    limit: int = 100,
    session_id: str | None = None,
    rating: str | None = None,
    since: str | None = None,
    x_admin_token: str | None = Header(None),
):
    _check_admin(x_admin_token)
    return {"turns": db.list_recent_turns(
        limit=limit, session_id=session_id, rating=rating, since_iso=since
    )}


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
# Endpoints admin para el backoffice (kitchen) — el panel los usa por HTTP
# en vez de tocar el filesystem directo. Así Kitchen puede correr en otro
# host (admin.suprabond.ai) y el backend (bondi.suprabond.ai) sigue siendo
# la única fuente de verdad del corpus.
# =====================================================================

@app.get("/admin/curation")
def admin_curation_get(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return agent.load_curation()


@app.post("/admin/curation")
def admin_curation_post(payload: dict, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    payload["version"] = int(payload.get("version") or 0) + 1
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    Path("data/curation.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _load_curation()
    return {"saved": True, "version": payload["version"]}


@app.get("/admin/pdfs")
def admin_pdfs_list(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    pdfs_dir = Path("data/pdfs")
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for p in sorted(pdfs_dir.glob("*.pdf")):
        sidecar = p.with_suffix(".meta.json")
        meta: dict = {}
        if sidecar.exists():
            try:
                meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception:
                pass
        out.append({
            "filename": p.name,
            "size_bytes": p.stat().st_size,
            "product_handle": meta.get("product_handle"),
        })
    return {"pdfs": out}


@app.post("/admin/pdfs/upload")
async def admin_pdfs_upload(
    file: UploadFile = File(...),
    product_handle: str | None = Form(None),
    x_admin_token: str | None = Header(None),
):
    _check_admin(x_admin_token)
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos .pdf")
    pdfs_dir = Path("data/pdfs")
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    target = pdfs_dir / Path(file.filename).name  # safe basename
    content = await file.read()
    target.write_bytes(content)
    if product_handle and product_handle.strip():
        sidecar = target.with_suffix(".meta.json")
        sidecar.write_text(
            json.dumps({"product_handle": product_handle.strip()}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    return {"saved": True, "filename": target.name, "size_bytes": len(content)}


@app.delete("/admin/pdfs/{filename}")
def admin_pdfs_delete(filename: str, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    safe = Path(filename).name  # evita ../ paths
    p = Path("data/pdfs") / safe
    if not p.exists():
        raise HTTPException(404, f"No existe {safe}")
    p.unlink()
    sidecar = p.with_suffix(".meta.json")
    if sidecar.exists():
        sidecar.unlink()
    return {"deleted": True, "filename": safe}


def _run_subprocess(cmd: list[str], timeout: int) -> dict:
    """Helper para correr subprocess y devolver dict serializable.

    Trunca stdout/stderr para no devolver outputs gigantes al cliente.
    """
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return {
            "ok": proc.returncode == 0,
            "returncode": proc.returncode,
            "stdout": (proc.stdout or "")[-4000:],
            "stderr": (proc.stderr or "")[-2000:],
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "returncode": -1, "stdout": "", "stderr": f"Timeout > {timeout}s"}


@app.post("/admin/ingest/pdfs")
def admin_ingest_pdfs(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return _run_subprocess([sys.executable, "-m", "ingestion.ingest_pdfs"], timeout=120)


@app.post("/admin/ingest/shopify")
def admin_ingest_shopify(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    return _run_subprocess([sys.executable, "ingestion/ingest_shopify.py"], timeout=180)


class WebCrawlRequest(BaseModel):
    start_url: str | None = None
    depth: int = 2
    max_pages: int = 200


@app.post("/admin/ingest/web")
def admin_ingest_web(req: WebCrawlRequest, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    cmd = [sys.executable, "-m", "ingestion.ingest_web",
           "--depth", str(req.depth), "--max-pages", str(req.max_pages)]
    if req.start_url:
        cmd += ["--start", req.start_url]
    return _run_subprocess(cmd, timeout=300)


class RebuildRequest(BaseModel):
    skip_products: bool = False
    skip_pdfs: bool = False
    skip_web: bool = False
    skip_faqs: bool = False


@app.post("/admin/rebuild")
def admin_rebuild(req: RebuildRequest, x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    cmd = [sys.executable, "-m", "embeddings.build_index"]
    if req.skip_products: cmd.append("--skip-products")
    if req.skip_pdfs: cmd.append("--skip-pdfs")
    if req.skip_web: cmd.append("--skip-web")
    if req.skip_faqs: cmd.append("--skip-faqs")
    result = _run_subprocess(cmd, timeout=300)
    # Si el rebuild salió OK, recargo el engine in-process para que el
    # próximo /chat use el index nuevo sin necesidad de /admin/reload.
    if result["ok"]:
        _load_engine()
    return result


@app.get("/admin/docs/web")
def admin_docs_web(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    p = Path("data/docs_web.jsonl")
    if not p.exists() or p.stat().st_size == 0:
        return {"docs": []}
    docs = []
    with p.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                docs.append(json.loads(line))
    return {"docs": docs}


class TestQueryRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    history: list[dict] = Field(default_factory=list)


@app.post("/admin/test_query")
def admin_test_query(req: TestQueryRequest, x_admin_token: str | None = Header(None)):
    """Probar una query del agent SIN persistir el turn en la DB.

    Útil para que el operador valide cambios en hard rules / FAQs antes
    de soltarlos al público. Devuelve la respuesta + tool calls + versión
    de hard rules que se usó."""
    _check_admin(x_admin_token)
    if _engine is None:
        raise HTTPException(503, "Search engine no inicializado.")
    if not _anthropic_api_key:
        raise HTTPException(503, "ANTHROPIC_API_KEY no configurada.")

    messages: list[dict] = list(req.history) + [
        {"role": "user", "content": req.message}
    ]
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
        log.exception("Error en agent.responder (test)")
        raise HTTPException(500, f"Agent error: {exc}")

    return {
        "response": response_text,
        "tool_calls": tool_calls,
        "hard_rules_version": hard_rules_version,
        "hard_rules_count": len(curation_now.get("hard_rules") or []),
    }


@app.get("/admin/health/files")
def admin_health_files(x_admin_token: str | None = Header(None)):
    _check_admin(x_admin_token)
    files_meta = [
        ("Catálogo Shopify", "data/products.jsonl"),
        ("PDFs ingestados", "data/docs_pdfs.jsonl"),
        ("Páginas web crawled", "data/docs_web.jsonl"),
        ("Vector store FAISS", "data/products.faiss"),
        ("Curation", "data/curation.json"),
    ]
    out = []
    for label, fname in files_meta:
        p = Path(fname)
        if p.exists():
            stat = p.stat()
            out.append({
                "label": label,
                "filename": fname,
                "exists": True,
                "size_bytes": stat.st_size,
                "mtime": datetime.fromtimestamp(stat.st_mtime).isoformat(),
            })
        else:
            out.append({
                "label": label,
                "filename": fname,
                "exists": False,
                "size_bytes": 0,
                "mtime": None,
            })
    return {"files": out}


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

    @app.get("/logo.png", include_in_schema=False)
    def frontend_logo():
        p = _frontend_dir / "logo.png"
        if not p.exists():
            raise HTTPException(404, "logo.png no encontrado")
        return FileResponse(str(p))

    @app.get("/favicon.ico", include_in_schema=False)
    def frontend_favicon():
        # Reutilizamos el logo como favicon. Si en el futuro hay un .ico
        # específico, agregarlo a frontend/ y servirlo acá.
        p = _frontend_dir / "logo.png"
        if not p.exists():
            raise HTTPException(404)
        return FileResponse(str(p), media_type="image/png")

    app.mount("/static", StaticFiles(directory=str(_frontend_dir)), name="static")
    log.info(f"Frontend montado: {_frontend_dir}")
else:
    log.info(f"Frontend no encontrado en {_frontend_dir} — endpoints API solamente.")
