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
- [ ] **1.2 — Vector store FAISS + embeddings OpenAI**: indexar el JSONL
  y validar retrieval con queries reales.
- [ ] **1.3 — Backend FastAPI con Claude tool use**: 4 tools (search,
  get_details, compare, escalate).
- [ ] **1.4 — Frontend chat embebible** (web component vanilla).
- [ ] **1.5 — Backoffice Streamlit** (auth + curaduría + insights + upload PDFs).
- [ ] **1.6 — Pipeline de PDFs subidos → re-ingestion**.
- [ ] **1.7 — Deploy + monitoreo**.

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
