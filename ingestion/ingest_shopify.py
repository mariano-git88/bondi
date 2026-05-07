"""
ingest_shopify.py — Pull del catálogo público de tienda.suprabond.com.

Recorre el feed `/products.json` (paginado, hasta 250 por página) y
guarda un JSONL en `data/products.jsonl` con los campos relevantes para
el RAG. body_html se mantiene original + se extrae body_text plano para
embeddings.

Endpoint: público, sin auth, sin rate limit declarado (Shopify estándar).

Uso:
    python ingest_shopify.py
    python ingest_shopify.py --base-url https://otra-tienda.com --output otro.jsonl

Salida típica para Suprabond AR (~430 productos):
    [page 1] 250 productos
    [page 2] ~180 productos
    [page 3] 0 productos → fin
    Total: 430 productos guardados en data/products.jsonl

Si en el futuro Shopify rate-limita, agregar `--sleep` entre pages.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup

DEFAULT_BASE_URL = "https://tienda.suprabond.com"
DEFAULT_OUTPUT = "data/products.jsonl"
PAGE_SIZE = 250
TIMEOUT = 30


def html_to_text(html: str | None) -> str:
    """Convierte body_html a texto plano. Quita tags, normaliza whitespace,
    preserva saltos de párrafo como dobles newlines."""
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    # Cada bloque (p, li, h1-h6, br) → newline. Inline tags se concatenan.
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text(separator="\n")
    # Normalizar: collapsar múltiples newlines a 2, strip de cada línea.
    lines = [ln.strip() for ln in text.splitlines()]
    out_lines: list[str] = []
    blank = False
    for ln in lines:
        if ln:
            out_lines.append(ln)
            blank = False
        elif not blank:
            out_lines.append("")
            blank = True
    return "\n".join(out_lines).strip()


def normalizar_producto(p: dict, base_url: str) -> dict:
    """Mapea un producto Shopify al schema del RAG."""
    body_html = p.get("body_html") or ""
    handle = p.get("handle") or ""
    return {
        "id": p.get("id"),
        "handle": handle,
        "url": f"{base_url}/products/{handle}" if handle else None,
        "title": p.get("title"),
        "body_html": body_html,
        "body_text": html_to_text(body_html),
        "vendor": p.get("vendor"),
        "product_type": p.get("product_type"),
        "tags": p.get("tags") or [],
        "variants": [
            {
                "id": v.get("id"),
                "sku": v.get("sku") or "",
                "title": v.get("title"),
                "price": v.get("price"),
                "compare_at_price": v.get("compare_at_price"),
                "available": v.get("available"),
                "option1": v.get("option1"),
                "option2": v.get("option2"),
                "option3": v.get("option3"),
            }
            for v in (p.get("variants") or [])
        ],
        "options": p.get("options") or [],
        "image_url": (
            (p.get("images") or [{}])[0].get("src") if p.get("images") else None
        ),
        "images_count": len(p.get("images") or []),
        "created_at": p.get("created_at"),
        "updated_at": p.get("updated_at"),
        "published_at": p.get("published_at"),
    }


def pull_paginado(base_url: str, sleep_between: float = 0.0) -> list[dict]:
    """Recorre /products.json paginando hasta encontrar página vacía."""
    all_products: list[dict] = []
    page = 1
    with httpx.Client(timeout=TIMEOUT) as client:
        while True:
            url = f"{base_url}/products.json"
            params = {"limit": PAGE_SIZE, "page": page}
            r = client.get(url, params=params)
            if r.status_code != 200:
                raise RuntimeError(
                    f"HTTP {r.status_code} en page {page}: {r.text[:200]}"
                )
            payload = r.json()
            products = payload.get("products") or []
            if not products:
                print(f"[page {page}] vacía → fin")
                break
            all_products.extend(products)
            print(f"[page {page}] {len(products)} productos (total acumulado: {len(all_products)})")
            if len(products) < PAGE_SIZE:
                # Última página parcial.
                break
            page += 1
            if sleep_between > 0:
                time.sleep(sleep_between)
    return all_products


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    parser.add_argument("--sleep", type=float, default=0.0,
                        help="Sleep entre páginas (segundos). Default 0.")
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/")
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Pull desde {base_url}/products.json (limit={PAGE_SIZE})")
    t0 = time.time()
    raw_products = pull_paginado(base_url, sleep_between=args.sleep)
    elapsed = time.time() - t0
    print(f"\nDescargados {len(raw_products)} productos en {elapsed:.1f}s\n")

    print(f"Normalizando + escribiendo JSONL en {output_path}...")
    with open(output_path, "w", encoding="utf-8") as f:
        for p in raw_products:
            f.write(json.dumps(normalizar_producto(p, base_url), ensure_ascii=False))
            f.write("\n")
    print(f"OK. {len(raw_products)} líneas escritas.\n")

    # Estadísticas rápidas.
    print("=== Estadísticas ===")
    vendors: dict[str, int] = {}
    types: dict[str, int] = {}
    body_lengths: list[int] = []
    sin_descripcion = 0
    sin_sku = 0
    for p in raw_products:
        v = (p.get("vendor") or "(sin vendor)").strip()
        vendors[v] = vendors.get(v, 0) + 1
        t = (p.get("product_type") or "(sin product_type)").strip()
        types[t] = types.get(t, 0) + 1
        body_text = html_to_text(p.get("body_html"))
        body_lengths.append(len(body_text))
        if not body_text:
            sin_descripcion += 1
        if not any((v.get("sku") or "").strip() for v in (p.get("variants") or [])):
            sin_sku += 1

    print(f"  Productos: {len(raw_products)}")
    print(f"  Sin descripción: {sin_descripcion}")
    print(f"  Sin SKU en variantes: {sin_sku}")
    print(f"  Body text: avg={sum(body_lengths)//max(1,len(body_lengths))} chars, "
          f"min={min(body_lengths)}, max={max(body_lengths)}")
    print(f"\n  Vendors:")
    for v, n in sorted(vendors.items(), key=lambda x: -x[1])[:10]:
        print(f"    {n:4} {v}")
    print(f"\n  Product types (top 15):")
    for t, n in sorted(types.items(), key=lambda x: -x[1])[:15]:
        print(f"    {n:4} {t}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
