# Bondi — Recomendador conversacional Suprabond AR

Asistente público para clientes y vendedores de Suprabond Argentina. Usa
RAG sobre cuatro fuentes:

1. **Catálogo Shopify** `tienda.suprabond.com` — productos con precio, stock,
   imagen, URL canónica.
2. **Sitio corporativo** `www.suprabond.com` — datos institucionales y
   técnicos (categorías, hojas técnicas en HTML, contacto).
3. **PDFs subidos por operadores** — hojas técnicas, manuales, fichas
   de seguridad. Se cargan desde el backoffice.
4. **FAQs curados** — pares pregunta/respuesta editables en el backoffice.

Encima del RAG hay **hard rules** (reglas inquebrantables del system
prompt) que el operador puede editar en vivo: "no recomendar marcas que
no sean Suprabond/Bulit/Somerset", disclaimers obligatorios para
químicos, etc.

Repo independiente del dashboard de Gestión de Vendedores GSU UY.

## Estado del proyecto

**v0.2 — Operación completa** (multi-source + curaduría + logging).
Sub-fases entregadas:

- [x] **1.1** — Ingestion Shopify (691 productos).
- [x] **1.2** — FAISS + OpenAI embeddings.
- [x] **1.3** — Backend FastAPI con tool use.
- [x] **1.4** — Frontend chat standalone.
- [x] **1.5** — Backoffice Streamlit (curaduría + hard rules + logs).
- [x] **1.6** — Ingestion de PDFs + ingestion web del sitio corporativo.
- [x] **1.7** — Deploy con dos services Render: `bondi.suprabond.ai` (chat) + `admin.suprabond.ai` (kitchen).
- [x] **1.8** — Hybrid search (BM25 + vector), feedback público inline, sitemap crawler, tab Test.

## Arquitectura

| Componente | Tech |
|---|---|
| Backend chat | FastAPI + Anthropic SDK (Claude Sonnet 4.6) |
| Retrieval | Hybrid BM25 (`rank-bm25`) + vector FAISS (cosine), alpha=0.7 |
| Embeddings | OpenAI `text-embedding-3-small`, 1536 dim |
| Logging | SQLite (`data/bondi.db`) con feedback público + admin |
| Backoffice (kitchen) | Streamlit cliente HTTP del backend, tema Vitsoe/Rams |
| Frontend chat | HTML/JS vanilla con feedback inline 👍/👎 |
| Hosting | Render 2 services (`bondi-api` + `bondi-kitchen`) con disk 1GB |
| PDFs | pypdf, chunking por página |
| Web crawl | httpx + BS4 + sitemap.xml + BFS depth-2 fallback |

## Setup local

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# editar .env con tus claves
```

## Primer build del corpus

```bash
export OPENAI_API_KEY=sk-...
python ingestion/ingest_shopify.py        # ~6s, 691 productos
python -m ingestion.ingest_web --depth 2 --max-pages 200   # ~2 min
python -m embeddings.build_index          # ~15s, ~USD 0.005
```

PDFs: subilos en el backoffice (tab "📄 PDFs") y dale "Re-ingestar PDFs"
+ "Rebuild Index".

## Correr backend

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export BONDI_ADMIN_PASS=tu-password
uvicorn backend.main:app --reload --port 8000
```

Endpoints públicos:
- `GET /` — chat público (frontend embebido).
- `POST /chat` — endpoint del agent.
- `GET /healthz` — healthcheck.
- `GET /catalog/stats` — info del catálogo.

Endpoints admin (header `X-Admin-Token: <BONDI_ADMIN_PASS>`):
- `POST /admin/reload` — recargar index + curation tras rebuild.
- `GET /admin/turns` — listar conversaciones.
- `GET /admin/turn/{id}` — detalle + feedback.
- `POST /admin/feedback` — guardar rating del operador.
- `GET /admin/db/stats` — métricas SQLite.

## Correr backoffice

En otra terminal:

```bash
export BONDI_ADMIN_PASS=tu-password
export OPENAI_API_KEY=sk-...               # para los rebuilds del index
export BONDI_BACKEND_URL=http://localhost:8000
streamlit run backoffice/app.py
```

Abrí `http://localhost:8501`. Ingresá la password y vas a ver 7 tabs:

| Tab | Para qué |
|---|---|
| 📊 Dashboard | Stats globales, status del backend |
| 💬 Conversaciones | Cada turn loggeado, feedback good/bad/flag con notas |
| 📋 Curaduría (FAQs) | CRUD de FAQs que entran al RAG |
| ⚖️ Hard Rules | Editar reglas inquebrantables del system prompt |
| 📄 PDFs | Subir hojas técnicas, re-ingestar |
| 🌐 Crawl Web | Re-crawlear el sitio corporativo |
| 🔧 Index | Rebuild + Reload backend |

**Workflow típico** después de cambios:
1. Hard rules → el agent las usa en el próximo `/chat` (hot reload).
2. FAQs / PDFs nuevos / web re-crawleada → tenés que hacer **Rebuild Index** y después **Reload Backend** para que el chat las vea.

## Deploy en Render

Ver `render.yaml`. Pasos:

1. Pushear el repo a GitHub.
2. Render → New → Blueprint → conectar repo.
3. Cargar las env vars que pide: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
   `BONDI_ADMIN_PASS`.
4. Esperar ~3 min al primer build.
5. Chat público queda en `https://<service>.onrender.com/`.

**Importante**: el backoffice Streamlit **no** se deploya por defecto —
se corre local. Si querés exponerlo (con auth de password), agregalo
como segundo Web Service en `render.yaml` con `startCommand: streamlit
run backoffice/app.py --server.port $PORT --server.address 0.0.0.0`.

## Esquema del corpus

Cada doc indexado tiene siempre estos campos en metadata:

- `id` — único, prefijado por source (`product-<handle>`, `pdf-<slug>-pN`,
  `web-<path-slug>`, `faq-<id>`).
- `source_type` — `"product"` | `"pdf"` | `"web"` | `"faq"`.
- `title`, `url`, `tags`, `body_text_short`.

Y los siguientes solo si aplica (`source_type == "product"`):
- `vendor`, `product_type`, `variants`, `image_url`, `handle`.

## Costos estimados

| Item | Costo |
|---|---|
| 1 build de index completo | USD ~0.005 (OpenAI embeddings) |
| 1 conversación promedio | USD 0.005-0.02 (Claude tool use) |
| Render starter | USD 7 / mes |
| Disk persistente 1GB | incluido en starter |

## Snapshot del catálogo (último build)

- 691 productos (Bulit 470 + Suprabond 213 + Somerset 7 + Tienda Suprabond 1)
- 161 tags únicos
- Body text avg 518 chars
- 0 productos sin descripción
- 26 productos sin SKU (3.7%)
