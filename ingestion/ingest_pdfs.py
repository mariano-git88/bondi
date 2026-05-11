"""
ingest_pdfs.py — Extracción de texto de PDFs subidos por operadores.

Lee data/pdfs/*.pdf, extrae texto con pypdf, chunkea por página (split si
la página supera CHUNK_MAX_CHARS), escribe data/docs_pdfs.jsonl.

Sidecar opcional: si existe data/pdfs/<nombre>.meta.json, se lee y se
usa para enriquecer metadata (típicamente product_handle).

Schema del chunk (unificado con docs_web y FAQs):
  id           — "pdf-<slug>-p<page>[#<sub>]"
  source_type  — "pdf"
  title        — "<filename> (pág. N)"
  url          — null (PDFs son internos al backoffice)
  body_text    — texto del chunk
  metadata     — {filename, page, total_pages, product_handle?, chunk_sub?}

Uso:
    python -m ingestion.ingest_pdfs
    python -m ingestion.ingest_pdfs --pdfs-dir data/pdfs --output data/docs_pdfs.jsonl
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from pypdf import PdfReader

CHUNK_MAX_CHARS = 2000
DEFAULT_PDFS_DIR = "data/pdfs"
DEFAULT_OUTPUT = "data/docs_pdfs.jsonl"


def _slugify(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "pdf"


def _chunk(text: str, max_chars: int) -> list[str]:
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    buf = ""
    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(buf) + len(para) + 2 <= max_chars:
            buf = (buf + "\n\n" + para).strip()
        else:
            if buf:
                chunks.append(buf)
            if len(para) <= max_chars:
                buf = para
            else:
                # Párrafo gigante → split duro por max_chars.
                for i in range(0, len(para), max_chars):
                    chunks.append(para[i:i + max_chars])
                buf = ""
    if buf:
        chunks.append(buf)
    return chunks


def extraer_pdf(path: Path, sidecar_meta: dict | None = None) -> list[dict]:
    """Devuelve lista de chunks del PDF en schema unificado."""
    try:
        reader = PdfReader(str(path))
    except Exception as exc:
        print(f"  ! no pude abrir {path.name}: {exc}", file=sys.stderr)
        return []
    total_pages = len(reader.pages)
    out: list[dict] = []
    slug = _slugify(path.stem)
    product_handle = (sidecar_meta or {}).get("product_handle")
    title_override = (sidecar_meta or {}).get("title")
    for i, page in enumerate(reader.pages, 1):
        try:
            txt = page.extract_text() or ""
        except Exception as exc:
            print(f"  ! error pág {i} de {path.name}: {exc}", file=sys.stderr)
            txt = ""
        sub_chunks = _chunk(txt, CHUNK_MAX_CHARS)
        for j, body in enumerate(sub_chunks):
            sub_suffix = f"#{j}" if len(sub_chunks) > 1 else ""
            base_title = title_override or path.stem
            out.append({
                "id": f"pdf-{slug}-p{i}{sub_suffix}",
                "source_type": "pdf",
                "title": f"{base_title} (pág. {i})",
                "url": None,
                "body_text": body,
                "metadata": {
                    "filename": path.name,
                    "page": i,
                    "total_pages": total_pages,
                    "product_handle": product_handle,
                    "chunk_sub": j if len(sub_chunks) > 1 else None,
                },
            })
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdfs-dir", default=DEFAULT_PDFS_DIR)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    pdfs_dir = Path(args.pdfs_dir)
    pdfs_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    pdfs = sorted([p for p in pdfs_dir.glob("*.pdf") if p.is_file()])
    if not pdfs:
        print(f"No hay PDFs en {pdfs_dir}. Escribo JSONL vacío.")
        out_path.write_text("", encoding="utf-8")
        return 0

    print(f"Procesando {len(pdfs)} PDFs desde {pdfs_dir}")
    all_chunks: list[dict] = []
    for p in pdfs:
        sidecar = p.with_suffix(".meta.json")
        sidecar_meta = {}
        if sidecar.exists():
            try:
                sidecar_meta = json.loads(sidecar.read_text(encoding="utf-8"))
            except Exception as exc:
                print(f"  ! sidecar inválido {sidecar.name}: {exc}", file=sys.stderr)
        chunks = extraer_pdf(p, sidecar_meta)
        print(f"  {p.name}: {len(chunks)} chunks")
        all_chunks.extend(chunks)

    with out_path.open("w", encoding="utf-8") as f:
        for c in all_chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\nOK. {len(all_chunks)} chunks escritos en {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
