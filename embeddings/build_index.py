"""
build_index.py — Genera embeddings OpenAI del catálogo y persiste un
índice FAISS + metadata.

Lee `data/products.jsonl` (output de ingestion/ingest_shopify.py),
construye el texto a embeber concatenando title + product_type + tags
+ body_text, llama OpenAI `text-embedding-3-small` en batch, y guarda:
  - data/products.faiss — índice FAISS (IndexFlatIP, 1536 dim)
  - data/products_metadata.pkl — lista paralela con metadata por producto
    (id, handle, url, title, vendor, product_type, tags, etc.)

OpenAI text-embedding-3-small:
  - 1536 dimensiones
  - USD 0.02 / 1M tokens (~88K tokens para 691 productos = ~USD 0.002)
  - Batch limit: 2048 inputs por call

Uso:
    export OPENAI_API_KEY=sk-...
    python embeddings/build_index.py
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

DEFAULT_INPUT = "data/products.jsonl"
DEFAULT_INDEX = "data/products.faiss"
DEFAULT_META = "data/products_metadata.pkl"
EMBED_MODEL = "text-embedding-3-small"
EMBED_DIM = 1536
BATCH_SIZE = 256  # OpenAI permite hasta 2048, vamos conservador


def texto_para_embed(p: dict) -> str:
    """Texto que se embebe por producto. Concatena los campos más
    relevantes para que el vector capture semántica de uso, marca y
    categoría a la vez."""
    parts: list[str] = []
    if p.get("title"):
        parts.append(p["title"])
    if p.get("vendor"):
        parts.append(f"Marca: {p['vendor']}")
    if p.get("product_type"):
        parts.append(f"Categoría: {p['product_type']}")
    tags = p.get("tags") or []
    # Ignorar tag "nuevo" que es marketing puro.
    tags = [t for t in tags if t.strip().lower() != "nuevo"]
    if tags:
        parts.append("Tags: " + ", ".join(tags))
    if p.get("body_text"):
        parts.append(p["body_text"])
    return "\n".join(parts)


def embed_batch(client: OpenAI, texts: list[str]) -> np.ndarray:
    """Llama OpenAI embeddings con un batch de textos."""
    resp = client.embeddings.create(model=EMBED_MODEL, input=texts)
    arr = np.array([d.embedding for d in resp.data], dtype=np.float32)
    return arr


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--input", default=DEFAULT_INPUT)
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--meta", default=DEFAULT_META)
    parser.add_argument("--limit", type=int, default=None,
                        help="Limitar a N productos para test rápido.")
    args = parser.parse_args()

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: falta OPENAI_API_KEY en el entorno.", file=sys.stderr)
        return 1
    client = OpenAI(api_key=api_key)

    in_path = Path(args.input)
    if not in_path.exists():
        print(f"ERROR: no existe {in_path}. Corré ingestion/ingest_shopify.py primero.", file=sys.stderr)
        return 1

    products: list[dict] = []
    with open(in_path, encoding="utf-8") as f:
        for line in f:
            products.append(json.loads(line))
            if args.limit and len(products) >= args.limit:
                break
    print(f"Leídos {len(products)} productos desde {in_path}")

    texts = [texto_para_embed(p) for p in products]
    total_chars = sum(len(t) for t in texts)
    print(f"Texto total a embeber: {total_chars:,} chars (~{total_chars // 4:,} tokens estimados)")

    print(f"\nEmbedding con {EMBED_MODEL}, batch={BATCH_SIZE}...")
    t0 = time.time()
    all_vectors: list[np.ndarray] = []
    for i in range(0, len(texts), BATCH_SIZE):
        batch = texts[i:i + BATCH_SIZE]
        vecs = embed_batch(client, batch)
        all_vectors.append(vecs)
        print(f"  batch {i // BATCH_SIZE + 1}: {len(batch)} embeddings (acum {sum(v.shape[0] for v in all_vectors)})")
    matrix = np.vstack(all_vectors)
    elapsed = time.time() - t0
    print(f"Embeddings listos: shape={matrix.shape}, {elapsed:.1f}s")

    # FAISS: usar IndexFlatIP con vectores normalizados → equivalente a cosine.
    faiss.normalize_L2(matrix)
    index = faiss.IndexFlatIP(EMBED_DIM)
    index.add(matrix)
    print(f"FAISS index: {index.ntotal} vectores indexados")

    Path(args.index).parent.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, args.index)
    print(f"  → {args.index}")

    # Metadata paralela al index — solo lo necesario para hidratar
    # respuestas; el body_text completo no hace falta acá (ya está
    # en el JSONL si se necesita para mostrar al usuario).
    metadata = [
        {
            "id": p.get("id"),
            "handle": p.get("handle"),
            "url": p.get("url"),
            "title": p.get("title"),
            "vendor": p.get("vendor"),
            "product_type": p.get("product_type"),
            "tags": p.get("tags") or [],
            "image_url": p.get("image_url"),
            "variants": p.get("variants") or [],
        }
        for p in products
    ]
    with open(args.meta, "wb") as f:
        pickle.dump(metadata, f)
    print(f"  → {args.meta}")

    print(f"\n✅ Index built. {len(products)} productos indexados.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
