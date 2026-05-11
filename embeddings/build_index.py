"""
build_index.py — Construye un único índice FAISS multi-source.

Fuentes (todas opcionales: si el archivo no existe, se ignora):
  data/products.jsonl       — catálogo Shopify (source_type='product')
  data/docs_pdfs.jsonl      — PDFs subidos por operadores (source_type='pdf')
  data/docs_web.jsonl       — páginas crawleadas del sitio (source_type='web')
  data/curation.json::faqs  — FAQs curados por operadores (source_type='faq')

Output (siempre los mismos paths, por compat con backend/search.py):
  data/products.faiss       — IndexFlatIP, 1536 dim, normalizado L2
  data/products_metadata.pkl — lista paralela de dicts con metadata

Cada entry de metadata tiene SIEMPRE estos campos:
  id, source_type, title, url, body_text_short, tags
Y los siguientes solo si aplican (product):
  vendor, product_type, variants, image_url

OpenAI text-embedding-3-small: USD 0.02 / 1M tokens.
Costo estimado para ~700 productos + ~50 docs ≈ USD 0.003.

Uso:
    export OPENAI_API_KEY=sk-...
    python -m embeddings.build_index
    python -m embeddings.build_index --skip-pdfs    # sin chunks de PDFs
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI

DEFAULT_INDEX = "data/products.faiss"
DEFAULT_META = "data/products_metadata.pkl"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 256

BODY_PREVIEW_CHARS = 600  # cuánto guardamos en metadata para devolver al LLM


# =====================================================================
# Carga + normalización por source
# =====================================================================

def _texto_product(p: dict) -> str:
    parts: list[str] = []
    if p.get("title"):
        parts.append(p["title"])
    if p.get("vendor"):
        parts.append(f"Marca: {p['vendor']}")
    if p.get("product_type"):
        parts.append(f"Categoría: {p['product_type']}")
    tags = [t for t in (p.get("tags") or []) if t.strip().lower() != "nuevo"]
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    if p.get("body_text"):
        parts.append(p["body_text"])
    return "\n".join(parts)


def cargar_products(path: Path) -> list[dict]:
    if not path.exists():
        print(f"  (sin {path}, salteado)")
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            p = json.loads(line)
            body = p.get("body_text") or ""
            doc = {
                "id": f"product-{p.get('handle') or p.get('id')}",
                "source_type": "product",
                "title": p.get("title"),
                "url": p.get("url"),
                "_text_for_embed": _texto_product(p),
                "body_text_short": body[:BODY_PREVIEW_CHARS],
                "tags": p.get("tags") or [],
                "vendor": p.get("vendor"),
                "product_type": p.get("product_type"),
                "variants": p.get("variants") or [],
                "image_url": p.get("image_url"),
                "handle": p.get("handle"),
            }
            out.append(doc)
    print(f"  products: {len(out)}")
    return out


def _texto_doc(d: dict) -> str:
    parts: list[str] = []
    if d.get("title"):
        parts.append(d["title"])
    if d.get("body_text"):
        parts.append(d["body_text"])
    return "\n".join(parts)


def cargar_jsonl_docs(path: Path, source_type_filter: str | None = None) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        print(f"  (sin {path} o vacío, salteado)")
        return []
    out: list[dict] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            st = d.get("source_type")
            if source_type_filter and st != source_type_filter:
                continue
            body = d.get("body_text") or ""
            out.append({
                "id": d.get("id"),
                "source_type": st,
                "title": d.get("title"),
                "url": d.get("url"),
                "_text_for_embed": _texto_doc(d),
                "body_text_short": body[:BODY_PREVIEW_CHARS],
                "tags": d.get("metadata", {}).get("tags", []) if isinstance(d.get("metadata"), dict) else [],
                "metadata": d.get("metadata") or {},
            })
    print(f"  {source_type_filter or path.name}: {len(out)}")
    return out


def cargar_faqs(curation_path: Path) -> list[dict]:
    if not curation_path.exists():
        print(f"  (sin {curation_path}, salteado)")
        return []
    try:
        data = json.loads(curation_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"  ! curation.json inválido: {exc}", file=sys.stderr)
        return []
    faqs = data.get("faqs") or []
    out: list[dict] = []
    for f in faqs:
        q = f.get("question") or ""
        a = f.get("answer") or ""
        body = f"Pregunta frecuente: {q}\n\nRespuesta: {a}"
        out.append({
            "id": f"faq-{f.get('id') or len(out)}",
            "source_type": "faq",
            "title": q,
            "url": None,
            "_text_for_embed": body,
            "body_text_short": body[:BODY_PREVIEW_CHARS],
            "tags": f.get("tags") or [],
            "metadata": {"faq_id": f.get("id")},
        })
    print(f"  faqs: {len(out)}")
    return out


# =====================================================================
# Embedding + FAISS
# =====================================================================

def embed_batch(client: OpenAI, texts: list[str]) -> np.ndarray:
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    return np.array([d.embedding for d in resp.data], dtype=np.float32)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--products", default="data/products.jsonl")
    parser.add_argument("--pdfs", default="data/docs_pdfs.jsonl")
    parser.add_argument("--web", default="data/docs_web.jsonl")
    parser.add_argument("--curation", default="data/curation.json")
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--meta", default=DEFAULT_META)
    parser.add_argument("--skip-products", action="store_true")
    parser.add_argument("--skip-pdfs", action="store_true")
    parser.add_argument("--skip-web", action="store_true")
    parser.add_argument("--skip-faqs", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: falta OPENAI_API_KEY.", file=sys.stderr)
        return 1
    client = OpenAI(api_key=api_key)

    print("Cargando fuentes:")
    docs: list[dict] = []
    if not args.skip_products:
        docs += cargar_products(Path(args.products))
    if not args.skip_pdfs:
        docs += cargar_jsonl_docs(Path(args.pdfs), source_type_filter="pdf")
    if not args.skip_web:
        docs += cargar_jsonl_docs(Path(args.web), source_type_filter="web")
    if not args.skip_faqs:
        docs += cargar_faqs(Path(args.curation))

    if args.limit:
        docs = docs[:args.limit]

    if not docs:
        print("ERROR: no hay docs para indexar.", file=sys.stderr)
        return 1

    print(f"\nTotal docs a indexar: {len(docs)}")
    texts = [d["_text_for_embed"] for d in docs]
    total_chars = sum(len(t) for t in texts)
    print(f"Caracteres totales: {total_chars:,} (~{total_chars // 4:,} tokens)")

    print(f"\nEmbedding con {EMBED_MODEL}, batch={BATCH_SIZE}...")
    t0 = time.time()
    all_vectors: list[np.ndarray] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        try:
            vecs = embed_batch(client, batch)
        except Exception as exc:
            print(f"ERROR en batch {i // BATCH_SIZE + 1}: {exc}", file=sys.stderr)
            return 1
        all_vectors.append(vecs)
        print(f"  batch {i // BATCH_SIZE + 1}: {len(batch)} (acum {sum(v.shape[0] for v in all_vectors)})")
    matrix = np.vstack(all_vectors)
    elapsed = time.time() - t0
    print(f"Embeddings listos: shape={matrix.shape}, {elapsed:.1f}s")

    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(matrix)
    print(f"FAISS: {index.ntotal} vectores indexados")

    Path(args.index).parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, args.index)
    print(f"  → {args.index}")

    # Metadata: TODO menos el _text_for_embed (no se necesita en runtime).
    metadata = []
    for d in docs:
        m = {k: v for k, v in d.items() if k != "_text_for_embed"}
        metadata.append(m)
    with open(args.meta, "wb") as f:
        pickle.dump(metadata, f)
    print(f"  → {args.meta}")

    # Resumen por source.
    by_source: dict[str, int] = {}
    for m in metadata:
        st = m.get("source_type") or "(unknown)"
        by_source[st] = by_source.get(st, 0) + 1
    print("\nDistribución por source_type:")
    for st, n in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {n:5}  {st}")

    print(f"\n✅ Index built. {len(docs)} docs indexados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
