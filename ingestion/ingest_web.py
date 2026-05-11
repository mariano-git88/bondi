"""
ingest_web.py — Crawler del sitio corporativo de Suprabond.

BFS depth-2 desde www.suprabond.com (con fallback a .com.ar y bare domain).
Filtra a same-site (acepta subdominios del registrable). Excluye la tienda
Shopify (tienda.suprabond.com) para no duplicar el catálogo. Respeta
robots.txt.

Output: data/docs_web.jsonl con un doc por página en schema unificado:
  id          — "web-<slug-del-path>"
  source_type — "web"
  title       — <h1> o <title>
  url         — URL canónica
  body_text   — texto principal (prefiere <main>/<article>, fallback body)
  metadata    — {depth, fetched_at, length}

Uso:
    python -m ingestion.ingest_web
    python -m ingestion.ingest_web --start https://www.suprabond.com.ar --depth 2
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urldefrag
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

DEFAULT_STARTS = [
    "https://www.suprabond.com",
    "https://www.suprabond.com.ar",
    "https://suprabond.com",
    "https://suprabond.com.ar",
]
DEFAULT_OUTPUT = "data/docs_web.jsonl"
DEFAULT_DEPTH = 2
TIMEOUT = 20
USER_AGENT = "BondiBot/0.2 (+https://www.suprabond.com)"
MAX_PAGES = 200
SKIP_HOSTS = {"tienda.suprabond.com"}
SKIP_PATH_PATTERNS = [
    re.compile(r"\.(jpg|jpeg|png|gif|svg|webp|pdf|zip|rar|css|js|ico|mp4|mp3|woff2?|xml)$", re.I),
    re.compile(r"^/(cart|checkout|account|login|wp-login|wp-admin)", re.I),
]


def _is_same_site(url: str, allowed_domains: set[str]) -> bool:
    host = urlparse(url).hostname or ""
    return any(host == d or host.endswith("." + d) for d in allowed_domains)


def _normalize(url: str) -> str:
    url, _ = urldefrag(url)
    return url.rstrip("/")


def _skip_path(url: str) -> bool:
    path = urlparse(url).path or "/"
    for pat in SKIP_PATH_PATTERNS:
        if pat.search(path):
            return True
    return False


def _allowed_by_robots(url: str, robots_cache: dict[str, RobotFileParser]) -> bool:
    parsed = urlparse(url)
    base = f"{parsed.scheme}://{parsed.netloc}"
    if base not in robots_cache:
        rp = RobotFileParser()
        rp.set_url(urljoin(base, "/robots.txt"))
        try:
            rp.read()
        except Exception:
            pass
        robots_cache[base] = rp
    rp = robots_cache[base]
    try:
        return rp.can_fetch(USER_AGENT, url)
    except Exception:
        return True


def _extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    h1 = soup.find("h1")
    title = (h1.get_text(strip=True) if h1 else None) or (
        soup.title.get_text(strip=True) if soup.title else ""
    )
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]):
        tag.decompose()
    main = soup.find("main") or soup.find("article") or soup.body or soup
    text = main.get_text(separator="\n")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    body_text = "\n".join(lines)
    return title, body_text


def _slug_from_path(path: str) -> str:
    if not path or path == "/":
        return "home"
    s = path.strip("/").lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-") or "page"


def _fetch_sitemap_urls(client: httpx.Client, base_url: str) -> list[str]:
    """Intentar leer /sitemap.xml. Soporta sitemap index recursivo (un sitemap
    que contiene refs a otros sitemaps). Devuelve lista de URLs encontradas.

    Si el sitemap no existe o el parse falla, devuelve []."""
    try:
        sitemap_url = base_url.rstrip("/") + "/sitemap.xml"
        r = client.get(sitemap_url)
        if r.status_code != 200:
            return []
        urls: list[str] = []
        # Strip namespace para simplificar el parsing.
        text = re.sub(r'\sxmlns="[^"]+"', "", r.text, count=1)
        root = ET.fromstring(text)
        # Caso A: <sitemapindex> con refs a otros sitemaps.
        for sm in root.findall("sitemap"):
            loc = sm.find("loc")
            if loc is not None and loc.text:
                # Recursión a 1 nivel: bajar los URLs del sub-sitemap.
                try:
                    sub = client.get(loc.text.strip())
                    if sub.status_code == 200:
                        sub_text = re.sub(r'\sxmlns="[^"]+"', "", sub.text, count=1)
                        sub_root = ET.fromstring(sub_text)
                        for u in sub_root.findall("url"):
                            uloc = u.find("loc")
                            if uloc is not None and uloc.text:
                                urls.append(uloc.text.strip())
                except Exception:
                    continue
        # Caso B: <urlset> directo.
        for u in root.findall("url"):
            uloc = u.find("loc")
            if uloc is not None and uloc.text:
                urls.append(uloc.text.strip())
        return urls
    except Exception as exc:
        print(f"  ! sitemap parse falló para {base_url}: {exc}", file=sys.stderr)
        return []


def crawl(start_urls: list[str], depth: int = DEFAULT_DEPTH, max_pages: int = MAX_PAGES) -> list[dict]:
    valid_starts: list[str] = []
    with httpx.Client(timeout=TIMEOUT, headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for u in start_urls:
            try:
                r = client.get(u)
                ct = r.headers.get("content-type", "")
                if r.status_code == 200 and ct.startswith("text/html"):
                    final = _normalize(str(r.url))
                    if final not in valid_starts:
                        valid_starts.append(final)
                        print(f"  ✓ start válido: {u} → {r.url}")
            except Exception as exc:
                print(f"  ✗ start falló {u}: {exc}")
        if not valid_starts:
            print("No se encontró ningún start URL válido.", file=sys.stderr)
            return []

        allowed_domains: set[str] = set()
        for u in valid_starts:
            host = urlparse(u).hostname
            if host:
                parts = host.split(".")
                if len(parts) >= 2:
                    allowed_domains.add(".".join(parts[-2:]))
                allowed_domains.add(host)

        # Intentar sitemap antes del BFS. Si hay sitemap, usamos esas URLs
        # como seeds adicionales (depth=0) — más completo y rápido.
        sitemap_urls: list[str] = []
        for s in valid_starts:
            parsed = urlparse(s)
            base = f"{parsed.scheme}://{parsed.netloc}"
            found = _fetch_sitemap_urls(client, base)
            if found:
                print(f"  📄 sitemap.xml encontrado en {base}: {len(found)} URLs")
                sitemap_urls.extend(found)

        visited: set[str] = set()
        queue: list[tuple[str, int]] = [(u, 0) for u in valid_starts]
        for su in sitemap_urls:
            queue.append((_normalize(su), 0))
        docs: list[dict] = []
        robots_cache: dict[str, RobotFileParser] = {}
        seen_titles: set[str] = set()

        while queue and len(docs) < max_pages:
            url, d = queue.pop(0)
            url = _normalize(url)
            if url in visited:
                continue
            visited.add(url)
            if urlparse(url).hostname in SKIP_HOSTS:
                continue
            if _skip_path(url):
                continue
            if not _is_same_site(url, allowed_domains):
                continue
            if not _allowed_by_robots(url, robots_cache):
                print(f"  ⊘ robots.txt bloquea {url}")
                continue
            try:
                r = client.get(url)
            except Exception as exc:
                print(f"  ! error {url}: {exc}")
                continue
            if r.status_code != 200:
                continue
            ct = r.headers.get("content-type", "")
            if not ct.startswith("text/html"):
                continue
            title, body_text = _extract_text(r.text)
            if len(body_text) >= 80:
                # Dedupe por (title + first 200 chars) para evitar páginas casi-idénticas.
                fingerprint = (title or "") + "|" + body_text[:200]
                if fingerprint not in seen_titles:
                    seen_titles.add(fingerprint)
                    path = urlparse(url).path or "/"
                    docs.append({
                        "id": f"web-{_slug_from_path(path)}",
                        "source_type": "web",
                        "title": title or url,
                        "url": url,
                        "body_text": body_text[:8000],
                        "metadata": {
                            "depth": d,
                            "fetched_at": datetime.now(timezone.utc).isoformat(),
                            "length": len(body_text),
                        },
                    })
                    print(f"  [{d}] {url} ({len(body_text)} chars) — {title[:60]}")
            if d < depth:
                soup = BeautifulSoup(r.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    nxt = urljoin(url, a["href"])
                    nxt = _normalize(nxt)
                    if nxt not in visited:
                        queue.append((nxt, d + 1))
            time.sleep(0.3)

        return docs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", action="append", default=None,
                        help="URL inicial. Repetible. Default: prueba múltiples Suprabond.")
    parser.add_argument("--depth", type=int, default=DEFAULT_DEPTH)
    parser.add_argument("--max-pages", type=int, default=MAX_PAGES)
    parser.add_argument("--output", default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    starts = args.start or DEFAULT_STARTS
    print(f"Crawl desde {starts} (depth={args.depth}, max_pages={args.max_pages})")
    t0 = time.time()
    docs = crawl(starts, depth=args.depth, max_pages=args.max_pages)
    elapsed = time.time() - t0

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    print(f"\n→ {len(docs)} páginas en {out} ({elapsed:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
