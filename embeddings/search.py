"""
search.py — Hybrid search (FAISS + BM25) sobre el corpus unificado.

El index unifica productos Shopify + PDFs + páginas web + FAQs (ver
build_index.py). Cada query combina dos rankings:

  - Vector similarity (FAISS): cosine sobre embeddings OpenAI
    text-embedding-3-small. Bueno para semántica y sinónimos.
  - BM25 (rank_bm25): TF-IDF clásico sobre el texto del doc. Bueno
    para keywords exactas, SKUs, números, nombres puntuales.

Los scores de ambos se normalizan a [0, 1] y se combinan con el
parámetro `alpha` (default 0.7 vector / 0.3 BM25). Filtros se aplican
post-ranking.

Uso programático:
    from embeddings.search import SearchEngine
    engine = SearchEngine()
    results = engine.search("adhesivo madera", k=5)

CLI smoke test:
    python -m embeddings.search "adhesivo madera"
    python -m embeddings.search "adhesivo" --sources product,faq --alpha 0.5
"""

from __future__ import annotations

import argparse
import os
import pickle
import re
import sys
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI
from rank_bm25 import BM25Okapi

EMBED_MODEL = "text-embedding-3-small"
DEFAULT_INDEX = "data/products.faiss"
DEFAULT_META = "data/products_metadata.pkl"
DEFAULT_ALPHA = 0.7  # peso del vector. BM25 = 1 - alpha.


def _tokenize(text: str) -> list[str]:
    """Tokenizer simple para BM25 — lowercase + alphanum, ignora tokens muy cortos."""
    return [t.lower() for t in re.findall(r"\w+", text or "") if len(t) > 1]


def _bm25_text(meta: dict) -> str:
    """Texto a indexar en BM25 para un doc. Concatena title + body short + vendor + tags."""
    parts: list[str] = []
    if meta.get("title"):
        parts.append(str(meta["title"]))
    if meta.get("body_text_short"):
        parts.append(str(meta["body_text_short"]))
    if meta.get("vendor"):
        parts.append(str(meta["vendor"]))
    if meta.get("product_type"):
        parts.append(str(meta["product_type"]))
    tags = meta.get("tags") or []
    if tags:
        parts.append(" ".join(str(t) for t in tags))
    return " ".join(parts)


class SearchEngine:
    def __init__(
        self,
        index_path: str = DEFAULT_INDEX,
        meta_path: str = DEFAULT_META,
        api_key: str | None = None,
    ):
        self.index_path = Path(index_path)
        self.meta_path = Path(meta_path)
        if not self.index_path.exists() or not self.meta_path.exists():
            raise FileNotFoundError(
                f"No existe {self.index_path} o {self.meta_path}. "
                "Corré `python -m embeddings.build_index`."
            )
        self.index = faiss.read_index(str(self.index_path))
        with open(self.meta_path, "rb") as f:
            self.metadata: list[dict] = pickle.load(f)
        if self.index.ntotal != len(self.metadata):
            raise RuntimeError(
                f"Mismatch: index tiene {self.index.ntotal} vectores, "
                f"metadata tiene {len(self.metadata)} entradas."
            )
        self.client = OpenAI(api_key=api_key or os.environ.get("OPENAI_API_KEY"))
        # BM25 sobre el texto de cada doc. Se construye una sola vez al
        # cargar el engine — costo amortizado en queries.
        self._build_bm25()

    def _build_bm25(self) -> None:
        tokenized = [_tokenize(_bm25_text(m)) for m in self.metadata]
        # Si todos vacíos por algún motivo raro, no construimos BM25
        # (el search devuelve solo vector).
        if any(tokenized):
            self.bm25: BM25Okapi | None = BM25Okapi(tokenized)
        else:
            self.bm25 = None

    def reload(self) -> None:
        """Re-cargar index + metadata + BM25 desde disco (post rebuild)."""
        self.index = faiss.read_index(str(self.index_path))
        with open(self.meta_path, "rb") as f:
            self.metadata = pickle.load(f)
        self._build_bm25()

    def _embed_query(self, query: str) -> np.ndarray:
        resp = self.client.embeddings.create(model=EMBED_MODEL, input=[query])
        v = np.array(resp.data[0].embedding, dtype=np.float32).reshape(1, -1)
        faiss.normalize_L2(v)
        return v

    def search(
        self,
        query: str,
        k: int = 5,
        sources: list[str] | None = None,
        filter_vendor: str | None = None,
        filter_tag: str | None = None,
        only_available: bool = False,
        alpha: float = DEFAULT_ALPHA,
    ) -> list[dict]:
        """Hybrid search: combina vector + BM25.

        alpha: peso del vector (0.0 = solo BM25, 1.0 = solo vector).
        Filtros aplicados post-ranking.
        """
        n = self.index.ntotal
        if n == 0:
            return []

        # Vector scores (todos los docs).
        query_vec = self._embed_query(query)
        v_scores, v_indices = self.index.search(query_vec, n)
        v_raw: dict[int, float] = {}
        for s, i in zip(v_scores[0], v_indices[0]):
            if i >= 0:
                v_raw[int(i)] = float(s)

        # BM25 scores (todos los docs).
        b_raw: dict[int, float] = {}
        if self.bm25 is not None:
            q_tokens = _tokenize(query)
            if q_tokens:
                scores_arr = self.bm25.get_scores(q_tokens)
                for i, s in enumerate(scores_arr):
                    b_raw[i] = float(s)

        # Normalizar a [0, 1] usando min-max.
        def _norm(d: dict[int, float]) -> dict[int, float]:
            if not d:
                return {}
            vals = list(d.values())
            mn, mx = min(vals), max(vals)
            if mx <= mn:
                return {k: 0.0 for k in d}
            return {k: (v - mn) / (mx - mn) for k, v in d.items()}

        v_norm = _norm(v_raw)
        b_norm = _norm(b_raw)

        # Combinar. Si BM25 no está disponible (corpus vacío) o alpha=1, solo vector.
        if not b_norm:
            combined = v_norm
        else:
            all_ids = set(v_norm.keys()) | set(b_norm.keys())
            combined = {
                i: alpha * v_norm.get(i, 0.0) + (1.0 - alpha) * b_norm.get(i, 0.0)
                for i in all_ids
            }

        # Ranking + filtros post.
        sources_set = set(sources) if sources else None
        ranked = sorted(combined.items(), key=lambda x: x[1], reverse=True)
        results: list[dict] = []
        for idx, score in ranked:
            meta = self.metadata[idx]
            st = meta.get("source_type")
            if sources_set and st not in sources_set:
                continue
            if filter_vendor and st == "product":
                if (meta.get("vendor") or "").lower() != filter_vendor.lower():
                    continue
            if filter_tag:
                tags_lc = [t.lower() for t in (meta.get("tags") or [])]
                if filter_tag.lower() not in tags_lc:
                    continue
            if only_available and st == "product":
                variants = meta.get("variants") or []
                if not any(v.get("available") for v in variants):
                    continue
            results.append({**meta, "score": float(score)})
            if len(results) >= k:
                break
        return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test del search hybrid.")
    parser.add_argument("query", type=str)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--sources", type=str, default=None,
                        help="Lista CSV de source_type (product,pdf,web,faq).")
    parser.add_argument("--vendor", type=str, default=None)
    parser.add_argument("--tag", type=str, default=None)
    parser.add_argument("--only-available", action="store_true")
    parser.add_argument("--alpha", type=float, default=DEFAULT_ALPHA,
                        help="Peso del vector (0=BM25, 1=solo vector).")
    parser.add_argument("--index", default=DEFAULT_INDEX)
    parser.add_argument("--meta", default=DEFAULT_META)
    args = parser.parse_args()

    sources = args.sources.split(",") if args.sources else None
    engine = SearchEngine(index_path=args.index, meta_path=args.meta)
    results = engine.search(
        args.query,
        k=args.k,
        sources=sources,
        filter_vendor=args.vendor,
        filter_tag=args.tag,
        only_available=args.only_available,
        alpha=args.alpha,
    )

    print(f'Query: "{args.query}" (alpha={args.alpha})')
    if sources:
        print(f'  sources: {sources}')
    if args.vendor:
        print(f'  vendor: {args.vendor}')
    if args.tag:
        print(f'  tag: {args.tag}')
    print(f'  k: {args.k}\n')

    if not results:
        print("(sin resultados)")
        return 0
    for i, r in enumerate(results, 1):
        st = r.get("source_type")
        url = r.get("url") or "(sin URL)"
        print(f"{i}. [{r['score']:.3f}] [{st}] {r.get('title')}")
        if st == "product":
            print(f"   {r.get('vendor')} | {(r.get('product_type') or '')[:60]}")
        print(f"   {url}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
