# Bondi — Recommender conversacional Suprabond AR

Asistente público que recomienda productos del catálogo de Suprabond
Argentina a vendedores y clientes finales. Usa RAG sobre el catálogo
de Shopify (`tienda.suprabond.com`) y, en fases posteriores, hojas
técnicas y curaduría manual.

Repo independiente del dashboard de Gestión de Vendedores GSU UY
(`gsu-gestion-vendedores`). Mismo grupo empresarial, dominios
funcionales y stacks distintos.

## Estado del proyecto

**Fase 1 — MVP** en progreso. Plan en 7 sub-fases:

- [x] **1.1 — Setup repo + ingestion Shopify**: 691 productos del catálogo
  AR descargados y normalizados a JSONL en 6.4s.
- [x] **1.2 — Vector store FAISS + embeddings OpenAI**: 693 productos
  indexados, retrieval top-5 ~87% relevancia validada con queries reales.
- [x] **1.3 — Backend FastAPI con Claude tool use**: 4 tools
  (search_catalog, get_product_details, compare_products,
  escalate_to_human). Endpoint `POST /chat` stateless.
- [x] **1.4 — Frontend chat**: `frontend/index.html` standalone (HTML
  + JS + CSS embebidos, sin frameworks). Markdown rendering nativo,
  history persistente en localStorage, ejemplos clicables.
- [ ] **1.5 — Backoffice Streamlit** (auth + curaduría + insights + upload PDFs).
- [ ] **1.6 — Pipeline de PDFs subidos → re-ingestion**.
- [x] **1.7 — Deploy**: `render.yaml` para backend en Render, `docs/`
  como source de GitHub Pages para frontend, cron diario que dispara
  redeploy de Render para refrescar catálogo. Pendiente: configurar en
  Render + GitHub Pages + secrets.

## Arquitectura confirmada

| Componente | Tech |
|---|---|
| Backend chat | FastAPI + Anthropic SDK |
| Vector store | FAISS local persistido |
| Embeddings | OpenAI `text-embedding-3-small` |
| LLM | Claude Sonnet 4.6 (API key separada del dashboard UY) |
| Backoffice | Streamlit |
| Frontend chat | Web component vanilla embebible |
| Hosting backend | Render |
| Cron re-ingestion | GitHub Actions diario |

## Cómo deployar (sub-fase 1.7)

Dos servicios separados: **backend en Render** + **frontend en GitHub Pages**.

### Backend (Render)

1. Ir a https://dashboard.render.com → New → Blueprint.
2. Conectar el repo `bondi`. Render detecta `render.yaml` y arma el servicio.
3. En **Environment**, configurar los 2 secrets (sync = false en yaml, hay que pegarlos en el dashboard):
   - `ANTHROPIC_API_KEY`
   - `OPENAI_API_KEY`
4. Click "Create Service". El primer deploy tarda ~3 minutos (instala deps + ingesta catálogo + construye FAISS index).
5. URL del servicio: `https://bondi-api.onrender.com` (Render asigna el slug; si pidió otro nombre, ajustar `BONDI_API_PROD` en `frontend/index.html` y `docs/index.html`).
6. Validar: `https://bondi-api.onrender.com/healthz` → debe devolver `engine_loaded: true`, `products_loaded: 693`.

Caveats del free tier:
- Duerme tras 15 min sin tráfico → cold start ~30-60s al despertar.
- Si crece el uso, escalar a Starter ($7/mes) elimina el sleep.

### Frontend (GitHub Pages)

1. En el repo bondi → Settings → Pages.
2. Source: "Deploy from a branch".
3. Branch: `main`, folder: `/docs`. Save.
4. URL: `https://mariano-git88.github.io/bondi/`.
5. (Opcional) Custom domain `chat.suprabond.com` o similar — configurar CNAME en GoDaddy / DNS apuntando a `mariano-git88.github.io`.

### Cron de re-ingestion

`.github/workflows/cron-reindex.yml` corre todos los días a las 06:00 UTC y dispara un redeploy de Render. Setup:

1. En Render → tu servicio → Settings → Deploy Hook URL → copiar URL.
2. En GitHub → repo bondi → Settings → Secrets and variables → Actions → New repository secret.
3. Nombre: `RENDER_DEPLOY_HOOK_URL`. Valor: la URL.
4. Commit + push. Disparable también manualmente desde Actions → Run workflow.

## Cómo correr el frontend (sub-fase 1.4)

Pre-requisito: backend levantado en `localhost:8000` (sub-fase 1.3).

En otra terminal, desde la raíz del repo:

```bash
python -m http.server 5000 -d frontend
```

Abrí `http://localhost:5000/` en el browser. Vas a ver el chat con
ejemplos clicables. La conversación persiste en localStorage entre
refreshes.

Para producción, cuando deployemos el backend, hay que cambiar
`API_URL` en `frontend/index.html:184` por la URL pública del Render.

## Cómo correr el backend (sub-fase 1.3)

Pre-requisitos: ya corriste `ingestion/ingest_shopify.py` y
`embeddings/build_index.py` (sub-fases 1.1 y 1.2).

```bash
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
uvicorn backend.main:app --reload --port 8000
```

Endpoint principal:

```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "qué adhesivo me sirve para pegar madera?", "history": []}'
```

El response incluye: `response` (texto natural), `history` (para mantener
contexto en el próximo turno) y `tool_calls` (debugging).

Healthcheck:

```bash
curl http://localhost:8000/healthz
```

## Cómo correr la ingestion (sub-fase 1.1)

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python ingestion/ingest_shopify.py
```

Output: `data/products.jsonl` con 691 productos normalizados.

Cada producto trae:
- `id`, `handle`, `url` (canónica `tienda.suprabond.com/products/<handle>`).
- `title`, `body_html`, `body_text` (HTML cleaneado para embedding).
- `vendor` (Bulit / Suprabond / Somerset / Tienda Suprabond).
- `product_type` (jerarquía Google taxonomy).
- `tags` (lista semántica).
- `variants` con `sku`, `price`, `available`.
- `image_url`, `images_count`.
- timestamps.

## Operadores del backoffice

2 personas — 1 AR + 1 UY (Mariano).

## Catálogo del corpus (snapshot 2026-05-07)

- 691 productos
- 3 marcas (470 Bulit + 213 Suprabond + 7 Somerset + 1 Tienda Suprabond)
- 161 tags únicos (top: Herramientas de Mano, Destornilladores, Candados, Selladores, Adhesivos)
- Body text avg 518 chars, max 2914 chars
- 0 productos sin descripción ✅
- 26 productos sin SKU en variantes (3.7% — caveat menor)
