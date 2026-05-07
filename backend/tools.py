"""
tools.py — Definiciones y ejecución de las 4 tools que Claude puede
invocar para responder preguntas sobre el catálogo Suprabond AR.

Cada tool tiene:
- Una entrada en TOOLS con name, description, input_schema (formato Anthropic).
- Una función Python que la ejecuta y devuelve dict serializable.

El executor (`run_tool`) recibe el contexto con `engine` (SearchEngine
ya cargado) y `products_by_handle` (dict para resolver handle → producto
completo, leído del JSONL al startup).

Diseño:
- Si una tool no encuentra datos, devuelve {"error": "..."} en lugar de
  lanzar — el LLM lo recibe como tool_result y razona sobre el error.
- El LLM nunca ve el JSONL completo, solo lo que las tools devuelven.
"""

from __future__ import annotations

from typing import Any


TOOLS: list[dict] = [
    {
        "name": "search_catalog",
        "description": (
            "Busca productos en el catálogo de Suprabond Argentina por similitud "
            "semántica. Devuelve los top-K productos más relevantes para la query, "
            "con título, handle, URL, marca, categoría y score. Usar para casi cualquier "
            "pregunta de recomendación. Filtros opcionales por marca o por tag exacto."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Texto de búsqueda. Puede ser una pregunta de uso ('adhesivo para madera') o una keyword ('destornillador phillips')."
                },
                "k": {"type": "integer", "default": 5, "description": "Cantidad de resultados (default 5, máx 20)."},
                "filter_vendor": {"type": "string", "description": "Opcional: filtrar a una marca específica (Suprabond, Bulit, Somerset)."},
                "filter_tag": {"type": "string", "description": "Opcional: filtrar a un tag exacto (ej. 'Adhesivos', 'Selladores')."},
                "only_available": {"type": "boolean", "default": False, "description": "Si true, solo trae productos con stock disponible."}
            },
            "required": ["query"]
        }
    },
    {
        "name": "get_product_details",
        "description": (
            "Devuelve la ficha completa de un producto identificado por su handle. "
            "Incluye body_text (descripción larga), variantes con SKU/precio/stock, "
            "imagen y URL canónica. Llamar después de search_catalog cuando necesites "
            "más detalle de un producto puntual."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handle": {"type": "string", "description": "Handle del producto (slug que viene en URL y en search_catalog)."}
            },
            "required": ["handle"]
        }
    },
    {
        "name": "compare_products",
        "description": (
            "Compara N productos lado a lado. Devuelve todas las fichas en formato "
            "tabla. Usar cuando el usuario pregunta diferencias entre productos o "
            "cuando hay 2-4 candidatos relevantes para una misma necesidad."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "handles": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de 2-4 handles a comparar."
                }
            },
            "required": ["handles"]
        }
    },
    {
        "name": "escalate_to_human",
        "description": (
            "Indica que la consulta excede lo que las tools pueden responder con "
            "certeza, o que el usuario necesita atención humana especializada (ej. "
            "consulta técnica de seguridad sobre químicos, problema con un pedido, "
            "queja). Devuelve confirmación de derivación con datos de contacto. "
            "USAR CUANDO no estés seguro o la consulta es de riesgo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "reason": {"type": "string", "description": "Motivo de la escalación (visible para registro interno)."}
            },
            "required": ["reason"]
        }
    },
]


# =====================================================================
# Implementaciones
# =====================================================================

def _producto_a_resumen(p: dict) -> dict:
    """Compacta un producto a los campos más relevantes para devolver al LLM."""
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


def tool_get_product_details(args: dict, ctx: dict) -> dict:
    handle = args.get("handle")
    if not handle:
        return {"error": "Falta handle."}
    products_by_handle: dict = ctx.get("products_by_handle") or {}
    p = products_by_handle.get(handle)
    if not p:
        return {"error": f"No encontré producto con handle '{handle}'. ¿Lo escribiste exactamente como vino en search_catalog?"}
    return {
        **_producto_a_resumen(p),
        "body_text": p.get("body_text") or "",
    }


def tool_compare_products(args: dict, ctx: dict) -> dict:
    handles = args.get("handles") or []
    if len(handles) < 2 or len(handles) > 4:
        return {"error": "compare_products necesita entre 2 y 4 handles."}
    products_by_handle: dict = ctx.get("products_by_handle") or {}
    found = []
    not_found = []
    for h in handles:
        p = products_by_handle.get(h)
        if p:
            found.append({
                **_producto_a_resumen(p),
                "body_text_excerpt": (p.get("body_text") or "")[:300],
            })
        else:
            not_found.append(h)
    return {
        "compared": found,
        "not_found_handles": not_found,
    }


def tool_escalate_to_human(args: dict, ctx: dict) -> dict:
    reason = args.get("reason") or "(sin motivo especificado)"
    # En el MVP solo registramos. En producción esto puede triggerar
    # email a vendedores, ticket en CRM, alert en Slack, etc.
    return {
        "escalated": True,
        "reason": reason[:500],
        "user_message": (
            "Te derivamos a un asesor humano de Suprabond. Podés escribirnos "
            "por WhatsApp o mail al equipo comercial — alguien va a "
            "responderte en horario hábil."
        ),
        "contact_info": {
            "whatsapp": "https://wa.me/5491123456789",  # actualizar con número real
            "email": "ventas@suprabond.com",            # actualizar con email real
        },
    }


_DISPATCH = {
    "search_catalog": tool_search_catalog,
    "get_product_details": tool_get_product_details,
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
        return {"error": f"Excepción ejecutando {name}: {exc}"}
