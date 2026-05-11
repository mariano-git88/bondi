"""
app.py — Backoffice Streamlit de Bondi.

Tabs:
  📊 Dashboard         — stats generales
  💬 Conversaciones    — lista + detalle + feedback (good/bad/flag)
  📋 Curaduría (FAQs)  — CRUD de FAQs que entran al RAG
  ⚖️ Hard Rules        — CRUD de reglas inquebrantables del system prompt
  📄 PDFs              — upload + lista + re-ingestion
  🌐 Crawl Web         — trigger crawl del sitio corporativo
  🔧 Index             — rebuild + reload backend

Auth: password en sidebar contra env BONDI_ADMIN_PASS (default 'admin').

Run:
    cd bondi
    export BONDI_ADMIN_PASS=tu-password
    export OPENAI_API_KEY=sk-...    # para rebuild
    streamlit run backoffice/app.py
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import streamlit as st

# Asegurar imports de backend.* funcionen cuando se corre con streamlit run.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import db  # noqa: E402

CURATION_PATH = ROOT / "data" / "curation.json"
PDFS_DIR = ROOT / "data" / "pdfs"
DOCS_PDFS_JSONL = ROOT / "data" / "docs_pdfs.jsonl"
DOCS_WEB_JSONL = ROOT / "data" / "docs_web.jsonl"
PRODUCTS_JSONL = ROOT / "data" / "products.jsonl"
INDEX_PATH = ROOT / "data" / "products.faiss"
META_PATH = ROOT / "data" / "products_metadata.pkl"

BACKEND_URL_DEFAULT = os.environ.get("BONDI_BACKEND_URL", "http://localhost:8000")

st.set_page_config(page_title="Bondi Backoffice", page_icon="🤖", layout="wide")
db.init_db()


# =====================================================================
# Helpers
# =====================================================================

def load_curation() -> dict:
    if not CURATION_PATH.exists():
        return {
            "version": 1,
            "hard_rules": [],
            "faqs": [],
            "disclaimers": {},
            "contact": {},
        }
    return json.loads(CURATION_PATH.read_text(encoding="utf-8"))


def save_curation(data: dict) -> None:
    # Bump de version + updated_at en cada guardado para que el agent lo sepa.
    data["version"] = int(data.get("version") or 0) + 1
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    CURATION_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def run_cmd(cmd: list[str], env_extra: dict | None = None) -> tuple[int, str, str]:
    env = os.environ.copy()
    if env_extra:
        env.update(env_extra)
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env, capture_output=True, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def call_backend_reload(backend_url: str, admin_token: str) -> tuple[bool, str]:
    try:
        import httpx
        r = httpx.post(
            f"{backend_url.rstrip('/')}/admin/reload",
            headers={"X-Admin-Token": admin_token},
            timeout=30,
        )
        if r.status_code == 200:
            return True, r.text
        return False, f"HTTP {r.status_code}: {r.text}"
    except Exception as exc:
        return False, str(exc)


def file_exists_info(p: Path) -> str:
    if not p.exists():
        return "❌ no existe"
    size = p.stat().st_size
    mtime = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
    if size < 1024:
        return f"✅ {size} B — {mtime}"
    if size < 1024 * 1024:
        return f"✅ {size / 1024:.1f} KB — {mtime}"
    return f"✅ {size / (1024 * 1024):.1f} MB — {mtime}"


# =====================================================================
# Auth
# =====================================================================

def check_auth() -> bool:
    expected = os.environ.get("BONDI_ADMIN_PASS") or "admin"
    if expected == "admin":
        st.sidebar.warning("⚠️ BONDI_ADMIN_PASS no configurada — usando default 'admin'.")
    pwd = st.sidebar.text_input("Password", type="password", key="auth_pwd")
    if not pwd:
        st.sidebar.info("Ingresá la password para acceder.")
        return False
    if pwd != expected:
        st.sidebar.error("Password incorrecta.")
        return False
    st.sidebar.success("Autenticado ✅")
    return True


# =====================================================================
# Sidebar
# =====================================================================

st.sidebar.title("🤖 Bondi Backoffice")

if not check_auth():
    st.stop()

operator = st.sidebar.text_input("Operador (para feedback)", value="anon")
backend_url = st.sidebar.text_input("Backend URL", value=BACKEND_URL_DEFAULT)
admin_token = os.environ.get("BONDI_ADMIN_PASS") or "admin"

st.sidebar.markdown("---")
st.sidebar.markdown("### Archivos")
st.sidebar.text(f"products.jsonl: {file_exists_info(PRODUCTS_JSONL)}")
st.sidebar.text(f"docs_pdfs.jsonl: {file_exists_info(DOCS_PDFS_JSONL)}")
st.sidebar.text(f"docs_web.jsonl: {file_exists_info(DOCS_WEB_JSONL)}")
st.sidebar.text(f"index.faiss: {file_exists_info(INDEX_PATH)}")
st.sidebar.text(f"curation.json: {file_exists_info(CURATION_PATH)}")


# =====================================================================
# Tabs
# =====================================================================

tab_dash, tab_chats, tab_faqs, tab_rules, tab_pdfs, tab_web, tab_index = st.tabs([
    "📊 Dashboard",
    "💬 Conversaciones",
    "📋 Curaduría (FAQs)",
    "⚖️ Hard Rules",
    "📄 PDFs",
    "🌐 Crawl Web",
    "🔧 Index",
])


# ---------- Dashboard ----------
with tab_dash:
    st.header("Dashboard")
    s = db.stats()
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Turns", s["turns"])
    col2.metric("Sesiones", s["sessions"])
    col3.metric("👍 Good", s["feedback_good"])
    col4.metric("👎 Bad", s["feedback_bad"])

    cur = load_curation()
    st.markdown("### Estado de curaduría")
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Hard rules", len(cur.get("hard_rules") or []))
    cc2.metric("FAQs", len(cur.get("faqs") or []))
    cc3.metric("Versión curation", cur.get("version") or 0)

    st.markdown("### Backend status")
    try:
        import httpx
        r = httpx.get(f"{backend_url.rstrip('/')}/healthz", timeout=5)
        if r.status_code == 200:
            st.json(r.json())
        else:
            st.warning(f"HTTP {r.status_code}: {r.text}")
    except Exception as exc:
        st.warning(f"Backend no responde ({backend_url}): {exc}")


# ---------- Conversaciones ----------
with tab_chats:
    st.header("Conversaciones")
    limit = st.slider("Cantidad a mostrar", 10, 500, 50, 10)
    rows = db.list_recent_turns(limit=limit)
    if not rows:
        st.info("Todavía no hay conversaciones registradas.")
    else:
        df = pd.DataFrame([
            {
                "turn_id": r["turn_id"],
                "ts": r["ts"],
                "session": (r["session_id"] or "")[:8],
                "user_msg": (r["user_msg"] or "")[:80],
                "assistant_msg": (r["assistant_msg"] or "")[:80],
                "feedback": r.get("feedback_count") or 0,
            }
            for r in rows
        ])
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.markdown("---")
        sel = st.number_input("Ver detalle de turn_id", min_value=0, step=1, value=0)
        if sel and sel > 0:
            t = db.get_turn(int(sel))
            if not t:
                st.error("No existe ese turn_id.")
            else:
                st.markdown(f"**Sesión**: `{t['session_id']}`  |  **Timestamp**: `{t['ts']}`")
                st.markdown("#### 👤 User")
                st.code(t["user_msg"], language="markdown")
                st.markdown("#### 🤖 Assistant")
                st.code(t["assistant_msg"], language="markdown")

                tool_calls = json.loads(t["tool_calls_json"] or "[]")
                if tool_calls:
                    with st.expander(f"🔧 Tool calls ({len(tool_calls)})"):
                        st.json(tool_calls)

                st.markdown("#### Feedback")
                fb_col1, fb_col2, fb_col3 = st.columns(3)
                with fb_col1:
                    if st.button("👍 Good", key=f"good_{sel}"):
                        db.save_feedback(int(sel), "good", operator=operator)
                        st.success("Guardado 👍")
                with fb_col2:
                    if st.button("👎 Bad", key=f"bad_{sel}"):
                        db.save_feedback(int(sel), "bad", operator=operator)
                        st.success("Guardado 👎")
                with fb_col3:
                    if st.button("🚩 Flag", key=f"flag_{sel}"):
                        db.save_feedback(int(sel), "flag", operator=operator)
                        st.success("Flag agregado 🚩")

                note = st.text_area("Nota (opcional)", key=f"note_{sel}", height=100)
                if st.button("Guardar nota", key=f"savenote_{sel}") and note.strip():
                    db.save_feedback(int(sel), "flag", note=note.strip(), operator=operator)
                    st.success("Nota guardada.")

                if t.get("feedback"):
                    st.markdown("#### Historial de feedback")
                    st.dataframe(pd.DataFrame(t["feedback"]), hide_index=True)


# ---------- Curaduría (FAQs) ----------
with tab_faqs:
    st.header("Curaduría — FAQs")
    st.caption("Las FAQs se indexan junto con productos y son consultables por el agent vía search_knowledge.")
    cur = load_curation()
    faqs = cur.get("faqs") or []
    df = pd.DataFrame(faqs) if faqs else pd.DataFrame(columns=["id", "question", "answer", "tags"])
    if "tags" in df.columns:
        df["tags"] = df["tags"].apply(lambda t: ", ".join(t) if isinstance(t, list) else (t or ""))

    edited = st.data_editor(
        df,
        num_rows="dynamic",
        use_container_width=True,
        column_config={
            "id": st.column_config.TextColumn("id", required=False),
            "question": st.column_config.TextColumn("Pregunta", width="medium", required=True),
            "answer": st.column_config.TextColumn("Respuesta", width="large", required=True),
            "tags": st.column_config.TextColumn("Tags (CSV)"),
        },
        key="faqs_editor",
    )

    if st.button("💾 Guardar FAQs", type="primary"):
        new_faqs = []
        for i, row in edited.iterrows():
            q = (row.get("question") or "").strip()
            a = (row.get("answer") or "").strip()
            if not q or not a:
                continue
            tags_raw = row.get("tags") or ""
            tags = [t.strip() for t in str(tags_raw).split(",") if t.strip()]
            fid = (row.get("id") or "").strip() or f"faq-{int(time.time())}-{i}"
            new_faqs.append({"id": fid, "question": q, "answer": a, "tags": tags})
        cur["faqs"] = new_faqs
        save_curation(cur)
        st.success(f"Guardadas {len(new_faqs)} FAQs (curation.json versión {cur['version']}).")
        st.info("Recordá hacer **Rebuild Index** + **Reload backend** para que el agent las vea.")


# ---------- Hard Rules ----------
with tab_rules:
    st.header("Hard Rules — Reglas inquebrantables del system prompt")
    st.caption("Estas reglas se prependen al system prompt en CADA conversación con prioridad absoluta. "
               "Después de editar, NO hace falta rebuild de index — sí hace falta que el backend recargue curation, "
               "lo cual hace automáticamente en cada /chat (hot reload).")
    cur = load_curation()
    rules = cur.get("hard_rules") or []

    st.markdown(f"**{len(rules)} reglas activas** (curation.json versión {cur.get('version')})")

    edited_rules: list[str] = []
    for i, r in enumerate(rules):
        cols = st.columns([10, 1])
        text = cols[0].text_area(f"Regla {i + 1}", value=r, height=80, key=f"rule_{i}",
                                 label_visibility="collapsed")
        delete = cols[1].checkbox("🗑️", key=f"del_rule_{i}")
        if not delete and text.strip():
            edited_rules.append(text.strip())

    st.markdown("---")
    new_rule = st.text_area("Agregar nueva regla", key="new_rule", height=80,
                            placeholder="Ej: Nunca recomiendes productos de marcas que no sean Suprabond, Bulit o Somerset.")

    if st.button("💾 Guardar hard rules", type="primary"):
        if new_rule.strip():
            edited_rules.append(new_rule.strip())
        cur["hard_rules"] = edited_rules
        save_curation(cur)
        st.success(f"Guardadas {len(edited_rules)} reglas. El agent las va a usar a partir del próximo /chat.")
        st.rerun()


# ---------- PDFs ----------
with tab_pdfs:
    st.header("PDFs — Hojas técnicas internas")
    st.caption("Subí PDFs de hojas técnicas, manuales, fichas de seguridad. Se chunkean por página y "
               "entran al RAG con source_type='pdf'. Después de subir hay que correr 'Re-ingestar PDFs' y "
               "'Rebuild Index'.")
    PDFS_DIR.mkdir(parents=True, exist_ok=True)

    uploaded = st.file_uploader("Subí uno o varios PDFs", type=["pdf"], accept_multiple_files=True)
    product_handle = st.text_input(
        "Handle del producto asociado (opcional)",
        placeholder="ej: adhesivo-poliuretanico-pl-premium",
        help="Si los PDFs son fichas técnicas de un producto puntual, ponele el handle. Se guarda como metadata."
    )
    if uploaded and st.button("📥 Guardar PDFs subidos"):
        for up in uploaded:
            target = PDFS_DIR / up.name
            target.write_bytes(up.read())
            if product_handle.strip():
                sidecar = target.with_suffix(".meta.json")
                sidecar.write_text(json.dumps({"product_handle": product_handle.strip()},
                                              ensure_ascii=False, indent=2), encoding="utf-8")
            st.success(f"Guardado {up.name}")
    st.markdown("---")

    pdfs = sorted(PDFS_DIR.glob("*.pdf"))
    if pdfs:
        st.markdown(f"**{len(pdfs)} PDFs en data/pdfs/:**")
        for p in pdfs:
            sidecar = p.with_suffix(".meta.json")
            sidecar_info = ""
            if sidecar.exists():
                try:
                    meta = json.loads(sidecar.read_text(encoding="utf-8"))
                    sidecar_info = f" — producto: `{meta.get('product_handle')}`"
                except Exception:
                    pass
            cols = st.columns([10, 1])
            cols[0].text(f"📄 {p.name} ({p.stat().st_size // 1024} KB){sidecar_info}")
            if cols[1].button("🗑️", key=f"del_{p.name}"):
                p.unlink()
                if sidecar.exists():
                    sidecar.unlink()
                st.rerun()
    else:
        st.info("Todavía no hay PDFs subidos.")

    st.markdown("---")
    if st.button("🔄 Re-ingestar PDFs", help="Corre ingest_pdfs.py sobre todos los PDFs de data/pdfs/"):
        with st.spinner("Procesando PDFs..."):
            rc, out, err = run_cmd([sys.executable, "-m", "ingestion.ingest_pdfs"])
        st.code(out + ("\n" + err if err else ""))
        if rc == 0:
            st.success("Re-ingestión OK. Hacé Rebuild Index para que entren al RAG.")
        else:
            st.error(f"Re-ingestión falló (rc={rc}).")


# ---------- Crawl Web ----------
with tab_web:
    st.header("Crawl Web — www.suprabond.com / .com.ar")
    st.caption("Crawler BFS del sitio corporativo. Excluye la tienda Shopify para no duplicar.")

    start_url = st.text_input(
        "Start URL (vacío = prueba defaults)",
        placeholder="https://www.suprabond.com.ar",
    )
    depth = st.slider("Depth (BFS)", 0, 3, 2)
    max_pages = st.slider("Max páginas", 10, 500, 200, 10)

    if st.button("🕸️ Correr crawl", type="primary"):
        cmd = [sys.executable, "-m", "ingestion.ingest_web",
               "--depth", str(depth), "--max-pages", str(max_pages)]
        if start_url.strip():
            cmd += ["--start", start_url.strip()]
        with st.spinner(f"Crawleando (puede tardar unos minutos)..."):
            rc, out, err = run_cmd(cmd)
        st.code(out + ("\n" + err if err else ""), language="text")
        if rc == 0:
            st.success("Crawl OK. Hacé Rebuild Index para que entren al RAG.")
        else:
            st.error(f"Crawl falló (rc={rc}).")

    if DOCS_WEB_JSONL.exists():
        with DOCS_WEB_JSONL.open(encoding="utf-8") as f:
            docs = [json.loads(line) for line in f if line.strip()]
        st.markdown(f"**{len(docs)} páginas en docs_web.jsonl**")
        if docs:
            tabla = pd.DataFrame([
                {"id": d["id"], "title": d.get("title", "")[:60], "url": d.get("url"),
                 "chars": (d.get("metadata") or {}).get("length", 0)}
                for d in docs
            ])
            st.dataframe(tabla, use_container_width=True, hide_index=True)


# ---------- Index ----------
with tab_index:
    st.header("Index FAISS — Rebuild + Reload")
    st.caption("Rebuild lee TODAS las fuentes (productos + PDFs + web + FAQs) y regenera el índice. "
               "Reload le pide al backend que recargue el index sin reiniciar.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### 🔨 Rebuild Index")
        st.markdown("Requiere `OPENAI_API_KEY` en el entorno. Costo: ~USD 0.005 para ~750 docs.")
        skip_products = st.checkbox("Skip products", value=False)
        skip_pdfs = st.checkbox("Skip pdfs", value=False)
        skip_web = st.checkbox("Skip web", value=False)
        skip_faqs = st.checkbox("Skip faqs", value=False)
        if st.button("🔨 Rebuild Index", type="primary"):
            if not os.environ.get("OPENAI_API_KEY"):
                st.error("Falta OPENAI_API_KEY en el entorno del backoffice.")
            else:
                cmd = [sys.executable, "-m", "embeddings.build_index"]
                if skip_products: cmd.append("--skip-products")
                if skip_pdfs: cmd.append("--skip-pdfs")
                if skip_web: cmd.append("--skip-web")
                if skip_faqs: cmd.append("--skip-faqs")
                with st.spinner("Construyendo embeddings + index..."):
                    rc, out, err = run_cmd(cmd)
                st.code(out + ("\n" + err if err else ""), language="text")
                if rc == 0:
                    st.success("Index rebuilt. Hacé Reload Backend para que el chat lo use.")
                else:
                    st.error(f"Rebuild falló (rc={rc}).")

    with col_right:
        st.markdown("### 🔄 Reload Backend")
        st.markdown(f"Le pide al backend en `{backend_url}` que recargue el index + curation.")
        if st.button("🔄 Reload Backend"):
            ok, msg = call_backend_reload(backend_url, admin_token)
            if ok:
                st.success(f"Reload OK: {msg}")
            else:
                st.error(f"Reload falló: {msg}")

        st.markdown("### 🌐 Re-ingestar Shopify")
        st.markdown("Pulla el catálogo de tienda.suprabond.com a products.jsonl.")
        if st.button("🛒 Re-ingestar Shopify"):
            with st.spinner("Bajando catálogo Shopify..."):
                rc, out, err = run_cmd([sys.executable, "ingestion/ingest_shopify.py"])
            st.code(out + ("\n" + err if err else ""), language="text")
            if rc == 0:
                st.success("Catálogo OK. Hacé Rebuild Index para que entre al RAG.")
            else:
                st.error(f"Falló (rc={rc}).")
