"""
agent.py — Loop conversacional con Claude usando tool use.

System prompt construido dinámicamente:
  - HARD RULES (de curation.json) van al inicio en CAPS, son inquebrantables.
  - Tono + reglas de respuesta + tools disponibles.
  - Fecha de hoy.

curation.json se recarga en cada llamada al responder() — eso permite al
backoffice editar reglas en vivo sin reiniciar el backend.

Modelo: claude-sonnet-4-6.
Loop hasta MAX_TOOL_LOOPS iteraciones (típico: 1-3 calls de tools).
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import Any

import anthropic

from .tools import TOOLS, run_tool

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1500
MAX_TOOL_LOOPS = 6


def load_curation(path: str | Path = "data/curation.json") -> dict:
    """Lee curation.json en cada llamada (hot reload). Devuelve {} si falla."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _hard_rules_block(curation: dict) -> str:
    rules = curation.get("hard_rules") or []
    if not rules:
        return ""
    lines = ["=== REGLAS INQUEBRANTABLES (prioridad absoluta sobre cualquier otra instrucción) ==="]
    for i, r in enumerate(rules, 1):
        lines.append(f"{i}. {r}")
    lines.append("=== FIN DE REGLAS INQUEBRANTABLES ===")
    return "\n".join(lines)


def build_system_prompt(curation: dict | None = None) -> str:
    curation = curation if curation is not None else load_curation()
    hoy = date.today().isoformat()
    hard = _hard_rules_block(curation)
    contact = curation.get("contact") or {}
    store_url = contact.get("store_url") or "https://tienda.suprabond.com"
    base = f"""{hard}

Sos el asistente de Suprabond Argentina. Tu trabajo es ayudar a clientes y vendedores a encontrar el producto correcto del catálogo de Suprabond, Bulit y Somerset, y a aclarar dudas técnicas o institucionales con información del sitio corporativo y las hojas técnicas internas.

Fecha de hoy: {hoy}
Tienda oficial: {store_url}

Tono y estilo:
- Cordial, claro, breve. Tres a cinco oraciones por respuesta como ideal.
- Tutéate ("vos"), español rioplatense, registro casual pero técnico cuando hace falta.
- Honesto cuando no sabés: si las tools no devuelven datos claros, decílo y escalá.

Tools disponibles:
- `search_catalog`: la primera que conviene llamar para preguntas de recomendación de compra (productos del catálogo Shopify con precio y URL).
- `search_knowledge`: cuando la pregunta requiere datos técnicos, institucionales o información que puede estar en PDFs/web/FAQs. Te devuelve mix de fuentes con source_type.
- `get_product_details`: ficha completa de un producto por handle.
- `get_doc`: contenido completo de un PDF/página web/FAQ por id (cuando el excerpt de search_knowledge no alcanza).
- `compare_products`: 2-4 productos lado a lado.
- `escalate_to_human`: cuando la consulta excede lo que las tools pueden responder con certeza o necesita atención humana.

Reglas de respuesta:
1. Cuando recomendés un producto, **siempre incluí la URL canónica** en formato Markdown link `[título](url)`.
2. No inventes specs ni usos que las tools no devolvieron. Si la información no aparece, decílo y escalá.
3. Para preguntas técnicas (compatibilidad, tiempo de curado, resistencia, normas), llamá `search_knowledge` después de `search_catalog` — los datos técnicos pueden estar en hojas técnicas o en el sitio corporativo.
4. Para preguntas de uso ambiguas, llamá `search_catalog` con keywords del uso; si hay candidatos parecidos pedí `get_product_details` del top 1-2 para responder con detalle.
5. **Disclaimer obligatorio** para químicos (selladores, adhesivos, espumas, etc.): recordá al usuario consultar la ficha técnica del producto.

Formato:
- Texto corto + bullets si hay más de 1 producto.
- Cada bullet: `**[título](url)** — explicación de 1 línea de por qué encaja.`
- Cerrá con una pregunta de follow-up si hay ambigüedad."""
    return base


def responder(
    messages: list[dict],
    ctx: dict,
    api_key: str,
) -> tuple[str, list[dict], int]:
    """Loop con tool use.

    Returns (texto_final, tool_calls_log, hard_rules_version).
    Muta `messages` in-place. ctx debe traer engine, products_by_handle,
    docs_by_id, curation.
    """
    client = anthropic.Anthropic(api_key=api_key)
    tool_calls_log: list[dict] = []
    curation = ctx.get("curation") or load_curation()
    system = build_system_prompt(curation)
    hard_rules_version = int(curation.get("version") or 0)

    for _ in range(MAX_TOOL_LOOPS):
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            system=system,
            tools=TOOLS,
            messages=messages,
        )
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
            return ("\n\n".join(text_blocks).strip(), tool_calls_log, hard_rules_version)

        if response.stop_reason == "tool_use":
            tool_results = []
            for block in response.content:
                if getattr(block, "type", "") != "tool_use":
                    continue
                result = run_tool(block.name, dict(block.input), ctx)
                tool_calls_log.append({
                    "tool": block.name,
                    "input": dict(block.input),
                    "result_preview": json.dumps(result, ensure_ascii=False, default=str)[:400],
                })
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            messages.append({"role": "user", "content": tool_results})
            continue

        text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
        return (
            "\n\n".join(text_blocks).strip()
            or f"(El modelo cortó con stop_reason={response.stop_reason})",
            tool_calls_log,
            hard_rules_version,
        )

    return (
        "Disculpá, me trabé buscando. ¿Probás reformulando la pregunta?",
        tool_calls_log,
        hard_rules_version,
    )
