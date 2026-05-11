"""
app.py — Backoffice Streamlit de Bondi (kitchen).

Cliente HTTP del backend. NO toca filesystem propio: cada read/write
(curation, PDFs, ingest, rebuild, conversaciones, feedback) va por
endpoints `/admin/*` del backend FastAPI. Eso permite deployar este app
en admin.suprabond.ai mientras el backend vive en bondi.suprabond.ai y
que ambos compartan estado.

Tabs:
  📊 Resumen        — stats globales + estado del backend
  💬 Conversaciones — log de chats + feedback (good/bad/flag)
  📋 FAQs           — CRUD de FAQs (entran al RAG)
  ⚖️ Reglas         — Hard Rules inquebrantables del system prompt
  📄 PDFs           — upload + re-ingestion
  🌐 Web            — crawler del sitio corporativo
  🔧 Index          — rebuild + reload backend
  ❤️ Salud          — archivos del corpus + healthcheck + db stats

Auth: password contra env BONDI_ADMIN_PASS. La password se envía al
backend como header `X-Admin-Token` en cada call.

Tema visual: Vitsoe/Dieter Rams (theme.py).

Tutorial: modal con @st.dialog (tutorial.py).

Run:
    cd bondi
    export BONDI_ADMIN_PASS=...
    export BONDI_BACKEND_URL=https://bondi.suprabond.ai
    streamlit run backoffice/app.py
"""

from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import pandas as pd
import streamlit as st

# Asegurar que `theme.py` y `tutorial.py` (locales a este package) se importen.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import theme  # noqa: E402
import tutorial  # noqa: E402

BACKEND_URL_DEFAULT = os.environ.get("BONDI_BACKEND_URL", "http://localhost:8000")


# =====================================================================
# Page config + theme
# =====================================================================

st.set_page_config(
    page_title="Bondi — Kitchen",
    page_icon="🤖",
    layout="wide",
)
theme.apply_theme()


# =====================================================================
# HTTP client al backend
# =====================================================================

def _headers(token: str) -> dict:
    return {"X-Admin-Token": token, "Accept": "application/json"}


def api_get(backend_url: str, token: str, path: str, timeout: float = 10.0) -> tuple[bool, dict | str]:
    try:
        r = httpx.get(f"{backend_url.rstrip('/')}{path}", headers=_headers(token), timeout=timeout)
        if r.status_code == 200:
            try:
                return True, r.json()
            except Exception:
                return True, r.text
        return False, f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def api_post(
    backend_url: str,
    token: str,
    path: str,
    json: dict | None = None,
    timeout: float = 30.0,
) -> tuple[bool, dict | str]:
    try:
        r = httpx.post(
            f"{backend_url.rstrip('/')}{path}",
            headers=_headers(token),
            json=json,
            timeout=timeout,
        )
        if r.status_code == 200:
            try:
                return True, r.json()
            except Exception:
                return True, r.text
        return False, f"HTTP {r.status_code}: {r.text[:500]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def api_post_multipart(
    backend_url: str,
    token: str,
    path: str,
    files: dict,
    data: dict | None = None,
    timeout: float = 60.0,
) -> tuple[bool, dict | str]:
    try:
        r = httpx.post(
            f"{backend_url.rstrip('/')}{path}",
            headers={"X-Admin-Token": token},
            files=files,
            data=data or {},
            timeout=timeout,
        )
        if r.status_code == 200:
            try:
                return True, r.json()
            except Exception:
                return True, r.text
        return False, f"HTTP {r.status_code}: {r.text[:500]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def api_delete(backend_url: str, token: str, path: str, timeout: float = 10.0) -> tuple[bool, dict | str]:
    try:
        r = httpx.delete(f"{backend_url.rstrip('/')}{path}", headers=_headers(token), timeout=timeout)
        if r.status_code == 200:
            return True, r.json()
        return False, f"HTTP {r.status_code}: {r.text[:300]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"


def fmt_size(n: int) -> str:
    if n is None:
        return "—"
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    return f"{n / (1024 * 1024):.1f} MB"


def fmt_ts(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M")
    except Exception:
        return iso


# =====================================================================
# Tutorial modal
# =====================================================================

@st.dialog("Tutorial — Cómo usar el backoffice de Bondi", width="large")
def _show_tutorial_dialog():
    tutorial.render()


# =====================================================================
# Auth gate (password compartida con el backend via X-Admin-Token)
# =====================================================================

st.sidebar.title("Kitchen")
st.sidebar.caption("Backoffice operativo de Bondi")

backend_url = st.sidebar.text_input("Backend URL", value=BACKEND_URL_DEFAULT)
pwd = st.sidebar.text_input("Password (BONDI_ADMIN_PASS)", type="password", key="auth_pwd")

if not pwd:
    st.sidebar.info("Ingresá la password para acceder.")
    st.stop()

# Probar la password contra un endpoint admin barato.
ok_auth, auth_msg = api_get(backend_url, pwd, "/admin/db/stats", timeout=8.0)
if not ok_auth:
    if isinstance(auth_msg, str) and "401" in auth_msg:
        st.sidebar.error("Password incorrecta.")
    else:
        st.sidebar.error(f"No pude hablar con el backend: {auth_msg}")
    st.stop()

admin_token = pwd
st.sidebar.success("Autenticado")
operator = st.sidebar.text_input("Operador (para feedback)", value="anon")


# =====================================================================
# Header con título + botón Tutorial
# =====================================================================

_col_title, _col_btn = st.columns([5, 1], vertical_alignment="center")
with _col_title:
    st.title("Kitchen — Bondi")
    st.caption(
        f"Backend: `{backend_url}` · Editá hard rules, FAQs, PDFs y revisá conversaciones reales. "
        "Si es tu primera vez, abrí el tutorial."
    )
with _col_btn:
    if st.button("Tutorial", use_container_width=True, key="btn_tutorial"):
        _show_tutorial_dialog()


# =====================================================================
# Tabs
# =====================================================================

tab_dash, tab_chats, tab_faqs, tab_rules, tab_pdfs, tab_web, tab_index, tab_test, tab_salud = st.tabs([
    "📊 Resumen",
    "💬 Conversaciones",
    "📋 FAQs",
    "⚖️ Reglas",
    "📄 PDFs",
    "🌐 Web",
    "🔧 Index",
    "🧪 Test",
    "❤️ Salud",
])


# ---------- Resumen ----------
with tab_dash:
    st.header("Resumen")
    ok, stats = api_get(backend_url, admin_token, "/admin/db/stats")
    if ok and isinstance(stats, dict):
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Turns", stats.get("turns", 0))
        col2.metric("Sesiones", stats.get("sessions", 0))
        col3.metric("👍 Good", stats.get("feedback_good", 0))
        col4.metric("👎 Bad", stats.get("feedback_bad", 0))
    else:
        st.warning(f"No pude leer stats: {stats}")

    ok_cur, cur = api_get(backend_url, admin_token, "/admin/curation")
    if ok_cur and isinstance(cur, dict):
        st.markdown("### Curaduría")
        cc1, cc2, cc3 = st.columns(3)
        cc1.metric("Hard rules", len(cur.get("hard_rules") or []))
        cc2.metric("FAQs", len(cur.get("faqs") or []))
        cc3.metric("Versión", cur.get("version") or 0)


# ---------- Conversaciones ----------
with tab_chats:
    st.header("Conversaciones")

    # Filtros en una fila.
    fcol1, fcol2, fcol3, fcol4 = st.columns([1, 1, 2, 1])
    with fcol1:
        limit = st.number_input("Límite", 10, 1000, 100, 10)
    with fcol2:
        rating_filter = st.selectbox(
            "Rating",
            ["todos", "good", "bad", "flag", "sin feedback"],
            index=0,
        )
    with fcol3:
        from datetime import date as _date, timedelta as _td
        since_date = st.date_input(
            "Desde",
            value=_date.today() - _td(days=30),
            help="Solo turns posteriores a esta fecha (00:00 UTC).",
        )
    with fcol4:
        session_filter = st.text_input("Session ID (parcial OK)", value="")

    # Armar query string.
    params = [f"limit={int(limit)}"]
    if rating_filter == "sin feedback":
        params.append("rating=none")
    elif rating_filter != "todos":
        params.append(f"rating={rating_filter}")
    if since_date:
        params.append(f"since={since_date.isoformat()}T00:00:00")
    if session_filter.strip():
        params.append(f"session_id={session_filter.strip()}")
    query = "&".join(params)

    ok, payload = api_get(backend_url, admin_token, f"/admin/turns?{query}")
    rows = payload.get("turns", []) if (ok and isinstance(payload, dict)) else []
    if not rows:
        st.info("Sin conversaciones para esos filtros.")
    else:
        df = pd.DataFrame([
            {
                "turn_id": r["turn_id"],
                "ts": r["ts"],
                "session": (r["session_id"] or "")[:8],
                "user_msg": (r["user_msg"] or "")[:80],
                "assistant_msg": (r["assistant_msg"] or "")[:80],
                "rating": r.get("last_rating") or "—",
                "feedback_count": r.get("feedback_count") or 0,
            }
            for r in rows
        ])
        st.markdown(f"**{len(df)} conversaciones**")
        st.dataframe(df, use_container_width=True, hide_index=True)

        # Export CSV de lo filtrado (más detalle que la tabla visible).
        export_df = pd.DataFrame([
            {
                "turn_id": r["turn_id"],
                "ts": r["ts"],
                "session_id": r["session_id"],
                "user_msg": r["user_msg"],
                "assistant_msg": r["assistant_msg"],
                "rating": r.get("last_rating") or "",
                "feedback_count": r.get("feedback_count") or 0,
                "hard_rules_version": r.get("hard_rules_version"),
            }
            for r in rows
        ])
        csv_bytes = export_df.to_csv(index=False).encode("utf-8")
        st.download_button(
            "⬇️ Export CSV",
            data=csv_bytes,
            file_name=f"bondi-conversaciones-{datetime.now().strftime('%Y%m%d-%H%M')}.csv",
            mime="text/csv",
        )

        st.divider()
        sel = st.number_input("Ver detalle de turn_id", min_value=0, step=1, value=0)
        if sel and sel > 0:
            ok_t, t = api_get(backend_url, admin_token, f"/admin/turn/{int(sel)}")
            if not ok_t:
                st.error(f"No existe ese turn_id ({t})")
            else:
                st.markdown(f"**Sesión**: `{t['session_id']}`  |  **Timestamp**: `{t['ts']}`")
                st.markdown("#### 👤 User")
                st.code(t["user_msg"], language="markdown")
                st.markdown("#### 🤖 Assistant")
                st.code(t["assistant_msg"], language="markdown")

                import json as _json
                tool_calls = _json.loads(t.get("tool_calls_json") or "[]")
                if tool_calls:
                    with st.expander(f"🔧 Tool calls ({len(tool_calls)})"):
                        st.json(tool_calls)

                st.markdown("#### Feedback")
                fb_col1, fb_col2, fb_col3 = st.columns(3)
                with fb_col1:
                    if st.button("👍 Good", key=f"good_{sel}"):
                        api_post(backend_url, admin_token, "/admin/feedback",
                                 json={"turn_id": int(sel), "rating": "good", "operator": operator})
                        st.success("Guardado 👍")
                with fb_col2:
                    if st.button("👎 Bad", key=f"bad_{sel}"):
                        api_post(backend_url, admin_token, "/admin/feedback",
                                 json={"turn_id": int(sel), "rating": "bad", "operator": operator})
                        st.success("Guardado 👎")
                with fb_col3:
                    if st.button("🚩 Flag", key=f"flag_{sel}"):
                        api_post(backend_url, admin_token, "/admin/feedback",
                                 json={"turn_id": int(sel), "rating": "flag", "operator": operator})
                        st.success("Flag agregado 🚩")

                note = st.text_area("Nota (opcional)", key=f"note_{sel}", height=100)
                if st.button("Guardar nota", key=f"savenote_{sel}") and note.strip():
                    api_post(backend_url, admin_token, "/admin/feedback",
                             json={"turn_id": int(sel), "rating": "flag",
                                   "note": note.strip(), "operator": operator})
                    st.success("Nota guardada.")

                if t.get("feedback"):
                    st.markdown("#### Historial de feedback")
                    st.dataframe(pd.DataFrame(t["feedback"]), hide_index=True)


# ---------- FAQs ----------
with tab_faqs:
    st.header("Curaduría — FAQs")
    st.caption("Cambios acá requieren Rebuild Index + Reload Backend para impactar al chat (no es hot-reload).")

    ok, cur = api_get(backend_url, admin_token, "/admin/curation")
    if not ok or not isinstance(cur, dict):
        st.error(f"No pude leer curation: {cur}")
    else:
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
            ok_save, msg = api_post(backend_url, admin_token, "/admin/curation", json=cur)
            if ok_save:
                v = msg.get("version") if isinstance(msg, dict) else "?"
                st.success(f"Guardadas {len(new_faqs)} FAQs (versión {v}).")
                st.info("Hacé **Rebuild Index** desde 🔧 Index para que el chat las vea.")
            else:
                st.error(f"Falló: {msg}")


# ---------- Reglas ----------
with tab_rules:
    st.header("Hard Rules — Reglas inquebrantables")
    st.caption("Hot-reload: NO requieren rebuild. El backend las relee en cada /chat.")

    ok, cur = api_get(backend_url, admin_token, "/admin/curation")
    if not ok or not isinstance(cur, dict):
        st.error(f"No pude leer curation: {cur}")
    else:
        rules = cur.get("hard_rules") or []
        st.markdown(f"**{len(rules)} reglas activas** (versión {cur.get('version')})")

        edited_rules: list[str] = []
        for i, r in enumerate(rules):
            cols = st.columns([10, 1])
            text = cols[0].text_area(f"Regla {i + 1}", value=r, height=80, key=f"rule_{i}",
                                     label_visibility="collapsed")
            delete = cols[1].checkbox("🗑️", key=f"del_rule_{i}")
            if not delete and text.strip():
                edited_rules.append(text.strip())

        st.divider()
        new_rule = st.text_area(
            "Agregar nueva regla", key="new_rule", height=80,
            placeholder="Ej: Nunca inventes información operativa (locales, horarios, plazos, precios).",
        )

        if st.button("💾 Guardar hard rules", type="primary"):
            if new_rule.strip():
                edited_rules.append(new_rule.strip())
            cur["hard_rules"] = edited_rules
            ok_save, msg = api_post(backend_url, admin_token, "/admin/curation", json=cur)
            if ok_save:
                st.success(f"Guardadas {len(edited_rules)} reglas. Activas en la próxima conversación.")
                st.rerun()
            else:
                st.error(f"Falló: {msg}")


# ---------- PDFs ----------
with tab_pdfs:
    st.header("PDFs — Hojas técnicas internas")
    st.caption("Subí PDFs (chunkeados por página). Después Re-ingestar PDFs + Rebuild Index.")

    uploaded = st.file_uploader("Subí uno o varios PDFs", type=["pdf"], accept_multiple_files=True)
    product_handle = st.text_input(
        "Handle del producto asociado (opcional)",
        placeholder="ej: adhesivo-poliuretanico-pl-premium",
        help="Si los PDFs son fichas de un producto puntual, ponele el handle.",
    )
    if uploaded and st.button("📥 Guardar PDFs subidos"):
        for up in uploaded:
            ok_up, msg = api_post_multipart(
                backend_url, admin_token, "/admin/pdfs/upload",
                files={"file": (up.name, up.getvalue(), "application/pdf")},
                data={"product_handle": product_handle.strip()} if product_handle.strip() else None,
                timeout=120.0,
            )
            if ok_up:
                st.success(f"Subido {up.name}")
            else:
                st.error(f"Falló {up.name}: {msg}")
        st.rerun()

    st.divider()

    ok_l, payload = api_get(backend_url, admin_token, "/admin/pdfs")
    pdfs = payload.get("pdfs", []) if (ok_l and isinstance(payload, dict)) else []
    if pdfs:
        st.markdown(f"**{len(pdfs)} PDFs en el backend:**")
        for p in pdfs:
            cols = st.columns([10, 1])
            handle_info = f" — producto: `{p['product_handle']}`" if p.get("product_handle") else ""
            cols[0].text(f"📄 {p['filename']} ({fmt_size(p['size_bytes'])}){handle_info}")
            if cols[1].button("🗑️", key=f"del_{p['filename']}"):
                ok_del, msg = api_delete(backend_url, admin_token, f"/admin/pdfs/{p['filename']}")
                if ok_del:
                    st.rerun()
                else:
                    st.error(msg)
    else:
        st.info("Todavía no hay PDFs subidos.")

    st.divider()
    if st.button("🔄 Re-ingestar PDFs"):
        with st.spinner("Procesando PDFs en el backend..."):
            ok_ing, res = api_post(backend_url, admin_token, "/admin/ingest/pdfs", timeout=150.0)
        if ok_ing and isinstance(res, dict):
            st.code(res.get("stdout", "") + (("\n" + res.get("stderr", "")) if res.get("stderr") else ""))
            if res.get("ok"):
                st.success("Re-ingestión OK. Hacé Rebuild Index para que entren al RAG.")
            else:
                st.error(f"Re-ingestión falló (rc={res.get('returncode')}).")
        else:
            st.error(f"Falló: {res}")


# ---------- Web ----------
with tab_web:
    st.header("Crawl Web — www.suprabond.com / .com.ar")
    st.caption("BFS depth-2, respeta robots.txt, excluye la tienda Shopify.")

    start_url = st.text_input(
        "Start URL (vacío = prueba defaults del backend)",
        placeholder="https://www.suprabond.com.ar",
    )
    depth = st.slider("Depth (BFS)", 0, 3, 2)
    max_pages = st.slider("Max páginas", 10, 500, 200, 10)

    if st.button("🕸️ Correr crawl", type="primary"):
        with st.spinner("Crawleando en el backend (puede tardar unos minutos)..."):
            ok_c, res = api_post(
                backend_url, admin_token, "/admin/ingest/web",
                json={"start_url": start_url.strip() or None, "depth": depth, "max_pages": max_pages},
                timeout=320.0,
            )
        if ok_c and isinstance(res, dict):
            st.code(res.get("stdout", "") + (("\n" + res.get("stderr", "")) if res.get("stderr") else ""))
            if res.get("ok"):
                st.success("Crawl OK. Hacé Rebuild Index para que entren al RAG.")
            else:
                st.error(f"Crawl falló (rc={res.get('returncode')}).")
        else:
            st.error(f"Falló: {res}")

    ok_d, payload = api_get(backend_url, admin_token, "/admin/docs/web")
    docs = payload.get("docs", []) if (ok_d and isinstance(payload, dict)) else []
    if docs:
        st.markdown(f"**{len(docs)} páginas capturadas**")
        tabla = pd.DataFrame([
            {
                "id": d.get("id"),
                "title": (d.get("title") or "")[:60],
                "url": d.get("url"),
                "chars": (d.get("metadata") or {}).get("length", 0),
            }
            for d in docs
        ])
        st.dataframe(tabla, use_container_width=True, hide_index=True)


# ---------- Index ----------
with tab_index:
    st.header("Index FAISS — Rebuild + Reload")
    st.caption("Rebuild regenera el FAISS desde TODAS las fuentes en el backend. "
               "Reload solo recarga el index ya construido sin re-embedear.")

    col_left, col_right = st.columns(2)
    with col_left:
        st.markdown("### 🔨 Rebuild Index")
        st.markdown("Llama al endpoint del backend. Requiere `OPENAI_API_KEY` configurada en el server. "
                    "Costo: ~USD 0.005 para ~750 docs.")
        skip_products = st.checkbox("Skip products", value=False)
        skip_pdfs = st.checkbox("Skip pdfs", value=False)
        skip_web = st.checkbox("Skip web", value=False)
        skip_faqs = st.checkbox("Skip faqs", value=False)
        if st.button("🔨 Rebuild Index", type="primary"):
            with st.spinner("Rebuildeando en el backend..."):
                ok_r, res = api_post(
                    backend_url, admin_token, "/admin/rebuild",
                    json={
                        "skip_products": skip_products,
                        "skip_pdfs": skip_pdfs,
                        "skip_web": skip_web,
                        "skip_faqs": skip_faqs,
                    },
                    timeout=320.0,
                )
            if ok_r and isinstance(res, dict):
                st.code(res.get("stdout", "") + (("\n" + res.get("stderr", "")) if res.get("stderr") else ""))
                if res.get("ok"):
                    st.success("Index rebuilt. El backend ya recargó automáticamente — el chat ve el nuevo index.")
                else:
                    st.error(f"Rebuild falló (rc={res.get('returncode')}).")
            else:
                st.error(f"Falló: {res}")

    with col_right:
        st.markdown("### 🔄 Reload Backend")
        st.markdown("Solo recarga products_by_handle + index + curation desde disco. Útil si "
                    "alguien tocó archivos del corpus sin rebuild.")
        if st.button("🔄 Reload Backend"):
            ok_rl, msg = api_post(backend_url, admin_token, "/admin/reload", timeout=30.0)
            if ok_rl:
                st.success(f"Reload OK: {msg}")
            else:
                st.error(f"Reload falló: {msg}")

        st.markdown("### 🛒 Re-ingestar Shopify")
        st.markdown("Pulla el catálogo de tienda.suprabond.com.")
        if st.button("🛒 Re-ingestar Shopify"):
            with st.spinner("Bajando catálogo Shopify..."):
                ok_s, res = api_post(backend_url, admin_token, "/admin/ingest/shopify", timeout=200.0)
            if ok_s and isinstance(res, dict):
                st.code(res.get("stdout", "") + (("\n" + res.get("stderr", "")) if res.get("stderr") else ""))
                if res.get("ok"):
                    st.success("Catálogo OK. Hacé Rebuild Index para que entre al RAG.")
                else:
                    st.error(f"Falló (rc={res.get('returncode')}).")
            else:
                st.error(f"Falló: {res}")


# ---------- Test ----------
with tab_test:
    st.header("Test del agent")
    st.caption("Probá una query SIN registrarla en la DB. Útil para validar cambios "
               "en hard rules o FAQs antes de soltarlos al público.")

    test_msg = st.text_area(
        "Mensaje del usuario",
        height=100,
        placeholder="Ej: ¿Qué adhesivo recomiendan para pegar madera con metal?",
        key="test_msg",
    )

    if st.button("🧪 Probar", type="primary", disabled=not test_msg.strip()):
        with st.spinner("El agent está pensando..."):
            ok_t, res = api_post(
                backend_url, admin_token, "/admin/test_query",
                json={"message": test_msg.strip(), "history": []},
                timeout=60.0,
            )
        if ok_t and isinstance(res, dict):
            st.markdown("### 🤖 Respuesta del agent")
            st.markdown(res.get("response", ""))
            cols = st.columns(3)
            cols[0].metric("Tool calls", len(res.get("tool_calls", []) or []))
            cols[1].metric("Hard rules aplicadas", res.get("hard_rules_count", 0))
            cols[2].metric("Versión curation", res.get("hard_rules_version", 0))

            tool_calls = res.get("tool_calls", []) or []
            if tool_calls:
                with st.expander(f"🔧 Tool calls ({len(tool_calls)})"):
                    st.json(tool_calls)
        else:
            st.error(f"Falló: {res}")


# ---------- Salud ----------
with tab_salud:
    st.header("Salud del sistema")
    st.caption("Estado de las fuentes del corpus + healthcheck del backend + métricas de la DB.")

    st.markdown("### Archivos del corpus (en el backend)")
    ok_f, payload = api_get(backend_url, admin_token, "/admin/health/files")
    files = payload.get("files", []) if (ok_f and isinstance(payload, dict)) else []
    if files:
        rows = []
        for f in files:
            if f.get("exists"):
                rows.append({
                    "Fuente": f["label"],
                    "Archivo": f["filename"],
                    "Estado": f"✅ {fmt_size(f['size_bytes'])}",
                    "Última modificación": fmt_ts(f.get("mtime")),
                })
            else:
                rows.append({
                    "Fuente": f["label"],
                    "Archivo": f["filename"],
                    "Estado": "❌ no existe",
                    "Última modificación": "—",
                })
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
    else:
        st.warning("No pude leer estado de archivos.")

    st.markdown("### Backend status (/healthz)")
    ok_h, hdata = api_get(backend_url, admin_token, "/healthz")
    if ok_h:
        st.json(hdata)
    else:
        st.warning(f"No pude leer healthz: {hdata}")

    st.markdown("### DB stats (SQLite del backend)")
    ok_s, stats = api_get(backend_url, admin_token, "/admin/db/stats")
    if ok_s and isinstance(stats, dict):
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Turns", stats.get("turns", 0))
        c2.metric("Sesiones", stats.get("sessions", 0))
        c3.metric("👍 Good", stats.get("feedback_good", 0))
        c4.metric("👎 Bad", stats.get("feedback_bad", 0))
        c5.metric("Total feedback", stats.get("feedback_total", 0))

    st.markdown("### Catalog stats")
    ok_c, cstats = api_get(backend_url, admin_token, "/catalog/stats")
    if ok_c:
        st.json(cstats)
