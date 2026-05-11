"""
tutorial.py — Contenido del tutorial del backoffice de Bondi.

Se pinta dentro de un st.dialog (modal) cuando el operador toca el
botón "Tutorial" del header.

Está pensado para que cualquiera del equipo Suprabond pueda abrir el
panel por primera vez y entender, sin que nadie le explique en vivo:

  1. Qué es Bondi y de dónde saca la información.
  2. Cuál es la diferencia entre Hard Rules y FAQs (cuándo aplica
     hot-reload y cuándo requiere rebuild).
  3. Cómo editar reglas y FAQs.
  4. Cómo subir PDFs de hojas técnicas.
  5. Cómo re-crawlear el sitio corporativo.
  6. Cómo ver y calificar conversaciones de usuarios reales.
  7. El "workflow correcto" para que un cambio llegue al chat.

El contenido vive solo en este módulo. Si hay que actualizarlo se edita
acá sin tocar app.py.
"""

import streamlit as st


def render() -> None:
    """Renderiza el contenido completo del tutorial dentro del modal."""

    # ----- Intro -----
    st.markdown(
        """
        ### ¿Qué es Bondi?

        Bondi es el **asistente conversacional público de Suprabond
        Argentina**. Responde preguntas de clientes y vendedores sobre el
        catálogo de Suprabond, Bulit y Somerset, recomienda productos
        con link directo a la tienda, y deriva a un asesor humano cuando
        la consulta lo amerita.

        Este panel sirve para que **vos como operador** mantengas a
        Bondi al día: editás reglas firmes, agregás preguntas
        frecuentes, subís hojas técnicas, re-crawleás el sitio
        corporativo, y revisás las conversaciones reales para detectar
        problemas o invenciones del modelo.
        """
    )

    st.divider()

    # ----- De dónde saca la información -----
    st.markdown(
        """
        ### ¿De dónde saca la información Bondi?

        El asistente combina **cuatro fuentes** que vos podés editar
        desde acá:

        | Fuente | Qué trae | Dónde se actualiza |
        |---|---|---|
        | **Catálogo Shopify** | Productos con precio, stock, URL, marca | Tab `🛒` o re-build del Render |
        | **Sitio corporativo** | Datos técnicos y operativos de www.suprabond.com | Tab `🌐 Web` |
        | **PDFs de hojas técnicas** | Fichas internas que sumás vos | Tab `📄 PDFs` |
        | **FAQs curadas** | Preguntas/respuestas escritas por vos | Tab `📋 FAQs` |

        Encima de las fuentes hay **Hard Rules** (tab `⚖️ Reglas`) que
        son instrucciones inquebrantables para el modelo, tipo "nunca
        recomendar marcas que no sean Suprabond, Bulit o Somerset".

        Cada conversación pasa por las hard rules **primero**, después
        por las fuentes, y devuelve la respuesta.
        """
    )

    st.divider()

    # ----- Hard Rules vs FAQs (clave) -----
    st.markdown(
        """
        ### ⚠️ Lo más importante: Hard Rules vs FAQs

        Esto es la trampa que más confunde, prestá atención.

        **Las Hard Rules son hot-reload.** Vos las editás, guardás, y
        el cambio impacta en la **próxima conversación** sin reiniciar
        nada. Ideal para reglas de tono, reglas de no-invención,
        prohibiciones, etc.

        **Las FAQs NO son hot-reload.** El texto de cada FAQ está
        **embebido en el vector store** (FAISS). Cuando editás una FAQ
        sin rebuild, el panel se actualiza pero el chat sigue
        respondiendo la versión vieja. Para que un cambio en FAQs
        llegue al chat necesitás dos pasos extra:

        1. Tab `🔧 Index` → **🔨 Rebuild Index** (regenera embeddings, ~15s, cuesta ~USD 0.005)
        2. Tab `🔧 Index` → **🔄 Reload Backend** (le pide al backend que cargue el index nuevo)

        Lo mismo aplica para **PDFs subidos** y **páginas crawleadas
        del sitio**: hay que rebuild + reload.

        > Regla mental: si tu cambio toca **texto que el modelo lee
        > como instrucción** (hard rules, system prompt), es
        > hot-reload. Si tu cambio toca **texto que el modelo
        > recupera** por similitud (FAQs, PDFs, web), necesita rebuild.
        """
    )

    st.divider()

    # ----- Curar FAQs -----
    st.markdown(
        """
        ### Editar FAQs — tab 📋

        1. Abrí el tab `📋 FAQs`.
        2. Editás las columnas directamente en la tabla: `question`,
           `answer`, `tags`. También podés agregar una fila nueva con
           el botón `+` que aparece al final.
        3. **CRÍTICO**: tocá `💾 Guardar FAQs` debajo de la tabla. Si
           no lo apretás, el cambio NO se persiste — vive solo en
           memoria de la sesión. Cuando guarda bien vas a ver un
           mensaje verde con `versión X` (la versión se incrementa en
           cada guardado).
        4. Andá a `🔧 Index` → Rebuild Index → Reload Backend.
        5. Probá en el chat la pregunta. **Limpiá el chat antes**
           (botón "Limpiar" en `bondi.suprabond.ai`) para que no use el
           history viejo.
        """
    )

    st.divider()

    # ----- Editar Hard Rules -----
    st.markdown(
        """
        ### Editar Hard Rules — tab ⚖️

        Las reglas se cargan en orden numerado dentro del system prompt
        del modelo. Cuanto más arriba, más prioridad mental tiene el
        modelo. Tips:

        - Escribilas en **imperativo claro**: "Nunca menciones marcas
          competidoras" funciona mejor que "Tratá de evitar las marcas
          competidoras".
        - Si la regla tiene una excepción, escribila explícita en la
          misma regla.
        - Para **borrar** una regla, marcá la checkbox `🗑️` a la
          derecha de la regla y guardá.

        Después de guardar, Bondi las usa en el próximo chat sin
        rebuild. No necesitás reload tampoco — el agent recarga
        curation.json automáticamente en cada conversación.
        """
    )

    st.divider()

    # ----- PDFs -----
    st.markdown(
        """
        ### Subir PDFs (hojas técnicas) — tab 📄

        1. Drag & drop o file picker → subís el PDF.
        2. (Opcional) Si el PDF es la ficha de **un producto puntual**,
           pegale el `handle` del producto (el slug que aparece en la
           URL de la tienda). Esto se guarda como metadata.
        3. `📥 Guardar PDFs subidos` → mueve los archivos a
           `data/pdfs/`.
        4. `🔄 Re-ingestar PDFs` → pasa todos los PDFs por pypdf,
           chunkea por página, escribe `data/docs_pdfs.jsonl`.
        5. `🔧 Index` → Rebuild Index → Reload Backend.

        > Tamaño recomendado: PDFs livianos (<5 MB). PDFs escaneados
        > sin OCR no funcionan — Bondi solo entiende texto extractable.
        """
    )

    st.divider()

    # ----- Crawl del sitio -----
    st.markdown(
        """
        ### Re-crawlear el sitio — tab 🌐

        Bondi puede leer páginas del sitio corporativo
        `www.suprabond.com` (no la tienda Shopify, esa va por otra
        vía). El crawler hace BFS depth-2 respetando robots.txt.

        1. Tab `🌐 Web`.
        2. Definir `Start URL` (default: prueba `www.suprabond.com` y
           variantes), `Depth` (default 2), `Max páginas` (default
           200).
        3. `🕸️ Correr crawl` → tarda 1-2 minutos.
        4. Cuando termina, vas a ver una tabla con las páginas
           capturadas.
        5. Después: `🔧 Index` → Rebuild → Reload.

        > Si querés que Bondi conozca una página nueva agregada al
        > sitio corporativo, re-crawleá. No detecta cambios automático.
        """
    )

    st.divider()

    # ----- Conversaciones -----
    st.markdown(
        """
        ### Ver conversaciones y dar feedback — tab 💬

        Cada interacción de un usuario con Bondi queda guardada en una
        base SQLite local (`data/bondi.db`). Acá podés revisar:

        1. Tab `💬 Conversaciones` muestra los turns más recientes con
           preview del mensaje del usuario y la respuesta.
        2. Ingresá el `turn_id` que querés ver en detalle.
        3. Vas a ver el mensaje completo, la respuesta, y las
           **tool calls** que hizo el modelo (qué tools usó, con qué
           argumentos).
        4. Dale `👍 Good` / `👎 Bad` / `🚩 Flag` según corresponda.
           También podés agregar una nota libre.

        Esto sirve para detectar problemas concretos: respuestas
        inventadas, recomendaciones equivocadas, casos donde el modelo
        debería haber escalado a humano y no lo hizo. Después podés
        traducir ese feedback en una nueva **Hard Rule** o **FAQ**
        para que no vuelva a pasar.
        """
    )

    st.divider()

    # ----- Workflow típico -----
    st.markdown(
        """
        ### Workflow típico semanal

        ```
        Lunes
          ↓ revisás Conversaciones (👍/👎 a los turns relevantes)
          ↓ detectás un patrón (ej: invenciones sobre stock)
          ↓ agregás una Hard Rule (instantáneo)
        Martes
          ↓ subís 2-3 PDFs nuevos de hojas técnicas
          ↓ Re-ingestar PDFs → Rebuild → Reload
        Cuando cambia el sitio
          ↓ Re-crawlear → Rebuild → Reload
        Cuando agregás una FAQ
          ↓ Editar y Guardar → Rebuild → Reload
        ```

        Hard Rules son cambios baratos y rápidos. FAQs / PDFs / Web
        son más caros (requieren rebuild + reload). Usá hard rules
        para "el modelo no debería" y FAQs para "el modelo no sabe".
        """
    )

    st.divider()

    # ----- Salud -----
    st.markdown(
        """
        ### Verificar que todo está OK — tab ❤️ Salud

        Si algo no responde como esperás, andá primero a `❤️ Salud`:

        - **Backend status**: tiene que decir `engine_loaded: true` y
          un `curation_version` que coincide con el que ves en `📋
          FAQs` (si difiere, falta hacer Reload Backend).
        - **Archivos**: tamaño + fecha de cada fuente. Si
          `docs_pdfs.jsonl` es `0 B`, no hay PDFs ingeridos.
        - **DB stats**: cantidad de conversaciones registradas y
          feedback acumulado.

        Si el backend no responde, fijate primero el `Backend URL` en
        la sidebar — apunta a tu local o al deploy de Render.
        """
    )
