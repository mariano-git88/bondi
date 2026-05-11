"""
search.py — Carga el FAISS multi-source y permite query por texto.

El index unifica productos Shopify + PDFs + páginas web + FAQs (ver
build_index.py). Cada entry de metadata trae 'source_type' que permite
al caller filtrar o priorizar.

Uso programático:
    from embeddings.search import SearchEngine
    engine = SearchEngine()
    results = engine.search("adhesivo madera", k=5)
    for r in results:
        print(r["source_type"], r["title"], r["score"])

CLI smoke test:
    export OPENAI_API_KEY=sk-...
    python -m embeddings.search "adhesivo para madera"
    python -m embeddings.search "adhesivo" --sources product,faq
"""

from __future__ import annotations

import argparse
import os
import pickle
import sys
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI

EMBED_MODEL = "text-embedding-3-small"
DEFAULT_INDEX = "data/products.faiss"
DEFAULT_META = "data/products_metadata.pkl"


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

    def reload(self) -> None:
        """Re-cargar index + metadata desde disco (después de un rebuild)."""
        self.index = faiss.read_index(str(self.index_path))
        with open(self.meta_path, "rb") as f:
            self.metadata = pickle.load(f)

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
    ) -> list[dict]:
        """Top-k docs.

        sources: lista de source_type aceptados (ej. ['product'], ['pdf','web']).
                 None = todas las fuentes.
        filter_vendor / filter_tag / only_available aplican solo a productos.
        Filtros se aplican post-retrieval; si pasás filtros tomamos k*5 candidatos.
        """
        sources_set = set(sources) if sources else None
        has_filters = bool(sources or filter_vendor or filter_tag or only_available)
        candidates_k = min(k * 5, self.index.ntotal) if has_filters else k
        query_vec = self._embed_query(query)
        scores, indices = self.index.search(query_vec, candidates_k)

        results: list[dict] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
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
    parser = argparse.ArgumentParser(description="Smoke test del search.")
    parser.add_argument("query", type=str)
    parser.add_argument("--k", type=int, default=5)
    parser.add_argument("--sources", type=str, default=None,
                        help="Lista CSV de source_type (product,pdf,web,faq).")
    parser.add_argument("--vendor", type=str, default=None)
    parser.add_argument("--tag", type=str, default=None)
    parser.add_argument("--only-available", action="store_true")
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
    )

    print(f'Query: "{args.query}"')
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
            print(f"   {r.get('vendor')} | {r.get('product_type', '')[:60]}")
        print(f"   {url}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
