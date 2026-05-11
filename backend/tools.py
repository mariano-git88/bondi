"""
tools.py — Definición + ejecución de las tools que Claude invoca.

Tools v2 (multi-source):
  search_catalog       — solo productos Shopify (mismo comportamiento previo).
  search_knowledge     — busca en TODO el corpus: productos + PDFs + web + FAQs.
  get_product_details  — ficha completa de un producto por handle.
  get_doc              — contenido completo de un doc no-product (pdf/web/faq) por id.
  compare_products     — tabla comparativa 2-4 productos.
  escalate_to_human    — derivar a un asesor con contact info de curation.json.

Cada función Python recibe (args: dict, ctx: dict) y devuelve dict JSON-safe.

ctx debe traer:
  engine             — SearchEngine cargado
  products_by_handle — dict[str, dict] del JSONL de productos
  docs_by_id         — dict[str, dict] de docs no-product (de metadata del index)
  curation           — dict del curation.json cargado
"""

from __future__ import annotations

from typing import Any


TOOLS: list[dict] = [
    {
        "name": "search_catalog",
        "description": (
            "Busca productos del catálogo Shopify de Suprabond por similitud semántica. "
            "Devuelve top-K productos con título, handle, URL canónica, marca, categoría y score. "
            "Usar para preguntas de recomendación de compra y consultas sobre precio o disponibilidad. "
            "Filtros opcionales por marca, tag o stock."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto de búsqueda (pregunta de uso o keyword)."},
                "k": {"type": "integer", "default": 5, "description": "Cantidad (1-20)."},
                "filter_vendor": {"type": "string", "description": "Filtrar a Suprabond/Bulit/Somerset."},
                "filter_tag": {"type": "string", "description": "Filtrar a un tag exacto."},
                "only_available": {"type": "boolean", "default": False, "description": "Solo con stock."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "search_knowledge",
        "description": (
            "Busca en TODO el corpus de conocimiento: productos del catálogo + páginas del sitio "
            "corporativo (datos técnicos, institucional) + PDFs de hojas técnicas subidas por operadores "
            "+ FAQs curados. Usar cuando la pregunta requiere datos técnicos o información del sitio "
            "que no esté en la descripción del producto. Devuelve mix de fuentes con source_type "
            "explícito y un excerpt del contenido."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Texto de búsqueda."},
                "k": {"type": "integer", "default": 5, "description": "Cantidad (1-20)."},
                "sources": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["product", "pdf", "web", "faq"]},
                    "description": "Restringir a estas fuentes. Default: todas."
                }
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_product_details",
        "description": (
            "Devuelve la ficha completa de un producto por su handle: body_text completo, "
            "variantes con SKU/precio/stock, imagen y URL. Llamar después de search_catalog "
            "cuando necesites más detalle."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Handle del producto (slug)."}
            },
            "required": ["handle"]
        }
    },
    {
        "name": "get_doc",
        "description": (
            "Devuelve el contenido completo de un documento no-producto (PDF, página web, FAQ) "
            "identificado por su id (que viene en search_knowledge). Usar cuando el excerpt "
            "no alcanza y necesitás el texto entero del doc."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "id del doc (pdf-*, web-*, faq-*)."}
            },
            "required": ["id"]
        }
    },
    {
        "name": "compare_products",
        "description": (
            "Compara 2-4 productos lado a lado. Útil cuando hay varios candidatos relevantes "
            "para una misma necesidad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de 2-4 handles."
                }
            },
            "required": ["handles"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Indica que la consulta requiere atención humana especializada: seguridad técnica "
            "delicada, queja de pedido, consulta estructural, o cuando ninguna tool dio "
            "información suficiente. Devuelve datos de contacto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Motivo de la escalación."}
            },
            "required": ["reason"]
        }
    },
]


# =====================================================================
# Helpers
# =====================================================================

def _producto_a_resumen(p: dict) -> dict:
    return {
        "handle": p.get("handle"),
        "url": p.get("url"),
        "title": p.get("title"),
        "vendor": p.get("vendor"),
        "product_type": p.get("product_type"),
        "tags": p.get("tags") or [],
        "image_url": p.get("image_url"),
        "variants": [
            {
                "sku": v.get("sku") or "",
                "title": v.get("title"),
                "price": v.get("price"),
                "available": v.get("available"),
            }
            for v in (p.get("variants") or [])
        ],
    }


def _doc_a_resumen(d: dict) -> dict:
    """Dict-resumen de un doc no-product para devolver al LLM."""
    return {
        "id": d.get("id"),
        "source_type": d.get("source_type"),
        "title": d.get("title"),
        "url": d.get("url"),
        "tags": d.get("tags") or [],
        "metadata": d.get("metadata") or {},
    }


# =====================================================================
# Implementaciones
# =====================================================================

def tool_search_catalog(args: dict, ctx: dict) -> dict:
    engine = ctx.get("engine")
    if engine is None:
        return {"error": "Search engine no inicializado."}
    query = args.get("query")
    if not query:
        return {"error": "Falta query."}
    k = max(1, min(int(args.get("k") or 5), 20))
    try:
        results = engine.search(
            query,
            k=k,
            sources=["product"],
            filter_vendor=args.get("filter_vendor"),
            filter_tag=args.get("filter_tag"),
            only_available=bool(args.get("only_available", False)),
        )
    except Exception as exc:
        return {"error": f"Search falló: {exc}"}
    return {
        "query": query,
        "k": k,
        "filters": {
            "vendor": args.get("filter_vendor"),
            "tag": args.get("filter_tag"),
            "only_available": args.get("only_available"),
        },
        "results": [
            {
                "handle": r.get("handle"),
                "title": r.get("title"),
                "url": r.get("url"),
                "vendor": r.get("vendor"),
                "product_type": r.get("product_type"),
                "tags": r.get("tags") or [],
                "score": round(r.get("score", 0.0), 3),
            }
            for r in results
        ],
    }


def tool_search_knowledge(args: dict, ctx: dict) -> dict:
    engine = ctx.get("engine")
    if engine is None:
        return {"error": "Search engine no inicializado."}
    query = args.get("query")
    if not query:
        return {"error": "Falta query."}
    k = max(1, min(int(args.get("k") or 5), 20))
    sources = args.get("sources") or None
    try:
        results = engine.search(query, k=k, sources=sources)
    except Exception as exc:
        return {"error": f"Search falló: {exc}"}
    return {
        "query": query,
        "k": k,
        "sources": sources,
        "results": [
            {
                "id": r.get("id"),
                "source_type": r.get("source_type"),
                "title": r.get("title"),
                "url": r.get("url"),
                "handle": r.get("handle"),  # si es product, viene; sino None
                "vendor": r.get("vendor"),
                "tags": r.get("tags") or [],
                "score": round(r.get("score", 0.0), 3),
                "excerpt": (r.get("body_text_short") or "")[:400],
            }
            for r in results
        ],
    }


def tool_get_product_details(args: dict, ctx: dict) -> dict:
    handle = args.get("handle")
    if not handle:
        return {"error": "Falta handle."}
    products_by_handle: dict = ctx.get("products_by_handle") or {}
    p = products_by_handle.get(handle)
    if not p:
        return {"error": f"No encontré producto con handle '{handle}'."}
    return {
        **_producto_a_resumen(p),
        "body_text": p.get("body_text") or "",
    }


def tool_get_doc(args: dict, ctx: dict) -> dict:
    doc_id = args.get("id")
    if not doc_id:
        return {"error": "Falta id."}
    docs_by_id: dict = ctx.get("docs_by_id") or {}
    d = docs_by_id.get(doc_id)
    if not d:
        return {"error": f"No encontré doc con id '{doc_id}'."}
    return {
        **_doc_a_resumen(d),
        "body_text": d.get("body_text_short") or "",
    }


def tool_compare_products(args: dict, ctx: dict) -> dict:
    handles = args.get("handles") or []
    if len(handles) < 2 or len(handles) > 4:
        return {"error": "compare_products necesita entre 2 y 4 handles."}
    products_by_handle: dict = ctx.get("products_by_handle") or {}
    found, not_found = [], []
    for h in handles:
        p = products_by_handle.get(h)
        if p:
            found.append({
                **_producto_a_resumen(p),
                "body_text_excerpt": (p.get("body_text") or "")[:300],
            })
        else:
            not_found.append(h)
    return {"compared": found, "not_found_handles": not_found}


def tool_escalate_to_human(args: dict, ctx: dict) -> dict:
    reason = (args.get("reason") or "(sin motivo)")[:500]
    curation = ctx.get("curation") or {}
    contact = curation.get("contact") or {}
    return {
        "escalated": True,
        "reason": reason,
        "user_message": (
            "Te derivamos a un asesor humano de Suprabond. Podés escribirnos por "
            "WhatsApp o mail al equipo comercial — alguien va a responderte en horario hábil."
        ),
        "contact_info": {
            "whatsapp": contact.get("whatsapp"),
            "email": contact.get("email"),
        },
    }


_DISPATCH = {
    "search_catalog": tool_search_catalog,
    "search_knowledge": tool_search_knowledge,
    "get_product_details": tool_get_product_details,
    "get_doc": tool_get_doc,
    "compare_products": tool_compare_products,
    "escalate_to_human": tool_escalate_to_human,
}


def run_tool(name: str, args: dict, ctx: dict) -> dict:
    fn = _DISPATCH.get(name)
    if fn is None:
        return {"error": f"Tool desconocida: {name}"}
    try:
        return fn(args, ctx)
    except Exception as exc:
        return {"error": f"Excepción en {name}: {exc}"}
