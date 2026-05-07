"""
agent.py — Loop conversacional con Claude usando tool use.

Recibe historia de mensajes + contexto (engine, products_by_handle) y
ejecuta el loop hasta que Claude termine con respuesta final o se exceda
el cap de iteraciones.

Modelo: claude-sonnet-4-6 — buen ratio costo/calidad para tool use.
Costo típico por consulta: USD 0.005-0.02.
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import anthropic

from .tools import TOOLS, run_tool

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1500
MAX_TOOL_LOOPS = 6


def _system_prompt() -> str:
    """System prompt dinámico: incluye fecha del día.

    Personalidad: cordial pero técnico. Honesto cuando no sabe.
    Siempre da URL canónica del producto cuando lo recomienda.
    """
    hoy = date.today().isoformat()
    return f"""Sos el asistente de Suprabond Argentina. Tu trabajo es ayudar a clientes y vendedores a encontrar el producto correcto del catálogo de Suprabond, Bulit y Somerset.

Fecha de hoy: {hoy}

Tono y estilo:
- Cordial, claro, breve. Tres a cinco oraciones por respuesta es el ideal.
- Tutéate ("vos"), español rioplatense, registro casual pero técnico cuando hace falta.
- Honesto cuando no sabés: si las tools no devuelven match claro, decílo y escalá.

Tools disponibles:
- `search_catalog`: la primera que casi siempre conviene llamar. Usás la pregunta del usuario como query.
- `get_product_details`: cuando el usuario pide más info de un producto puntual o necesitás el body_text completo para responder bien.
- `compare_products`: cuando hay 2-4 candidatos parecidos y conviene mostrar lado a lado.
- `escalate_to_human`: cuando la consulta es de seguridad técnica delicada (productos químicos, riesgo de uso incorrecto), o cuando ninguna tool da resultado satisfactorio.

Reglas de respuesta:
1. Cuando recomiendes un producto, **siempre incluí la URL canónica** (`url` que viene en search_catalog) en formato Markdown link `[título](url)`.
2. No inventes specs ni usos que las tools no devolvieron. Si una pregunta requiere specs que no aparecen en body_text, decí que necesitás ver la ficha técnica y escalá.
3. Para preguntas de uso ambiguas (ej. "qué adhesivo para madera"), llamá search_catalog con keywords del uso, después si hay varios candidatos parecidos podés llamar get_product_details del top 1-2 para responder con detalle.
4. Si el usuario pregunta algo fuera del catálogo (ej. preguntas generales sobre construcción, consejos no relacionados a productos Suprabond), respondé brevemente y dirigílo al producto más cercano que tengamos.
5. **Disclaimer cuando aplica**: para productos químicos (selladores, adhesivos, espumas) que tengan condiciones de uso específicas, recordá al usuario consultar la ficha técnica del producto y/o un profesional.

Formato de las respuestas:
- Texto corto + bullets si hay más de 1 producto.
- Cada bullet: `**[título](url)** — explicación de 1 línea de por qué encaja.`
- Cerrá con una pregunta de follow-up si hay ambigüedad ("¿es para uso interior o exterior?", "¿qué tipo de superficie?")."""


def responder(
    messages: list[dict],
    ctx: dict,
    api_key: str,
) -> tuple[str, list[dict]]:
    """Loop con tool use. Devuelve (texto_final, tool_calls_log).

    `messages` se muta in-place para reflejar la conversación tras el loop.
    `ctx` debe traer:
        - engine: SearchEngine ya cargado
        - products_by_handle: dict[str, dict] con todos los productos del JSONL
    """
    client = anthropic.Anthropic(api_key=api_key)
    tool_calls_log: list[dict] = []
    system = _system_prompt()

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
            return "\n\n".join(text_blocks).strip(), tool_calls_log

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

        # stop_reason inesperado: cortamos.
        text_blocks = [b.text for b in response.content if getattr(b, "type", "") == "text"]
        return (
            "\n\n".join(text_blocks).strip()
            or f"(El modelo cortó con stop_reason={response.stop_reason})",
            tool_calls_log,
        )

    return (
        "Disculpá, me trabé buscando. ¿Probás reformulando la pregunta?",
        tool_calls_log,
    )
