# Bondi — Handover técnico y operativo

> Documento de transferencia del proyecto Bondi al rol de Jefa de
> Canales Digitales de Suprabond. Pensado para que la persona que
> recibe la responsabilidad pueda **operar, mantener y evolucionar el
> producto sin asistencia externa**. Última actualización: 2026-05-21.

---

## Bienvenida

Bondi es un asistente conversacional que ayuda a usuarios de Suprabond
Argentina a encontrar productos y resolver dudas técnicas.
A partir de esta semana es **tu proyecto**: vas a coordinar con
Sistemas, evangelizarlo internamente, recoger feedback de usuarios y
decidir el rumbo de las próximas iteraciones.

Este documento te explica todo lo que necesitás saber para arrancar.
Está pensado para leerse **de corrido en 1-2 horas**. Está organizado
en secciones independientes para que después puedas volver a una sin
tener que releer todo.

Si en cualquier punto algo no se entiende, anotá la duda y revisá la
sección **12. Contactos y soporte**.

---

## 1. Qué es Bondi y qué hace

### Qué es

Bondi es un **chat web** que responde preguntas de productos Suprabond
en lenguaje natural. Tiene dos productos:

- **Chat público** (`bondi.suprabond.ai`) — para usuarios.
  Pregunta sobre adhesivos, perfilería, accesorios, etc., y recibe
  respuestas con productos sugeridos, precios y enlaces.
- **Kitchen / backoffice** (`admin.suprabond.ai`) — para vos y los
  operadores internos. Te deja editar FAQs, reglas duras, subir PDFs
  técnicos, ver el historial de conversaciones, marcar respuestas como
  buenas o malas, y disparar actualizaciones del índice de búsqueda.

### Qué problema resuelve

Antes, un usuario con una duda específica (ej. "¿qué adhesivo uso para
pegar zócalos sobre cerámica?") podía:

1. Buscar en `tienda.suprabond.com` y filtrar a mano.
2. Llamar a un vendedor.
3. Buscar en Google.

Bondi unifica todo eso en un chat: cruza el catálogo, las hojas
técnicas, el sitio corporativo y las FAQs curadas para dar una
respuesta concreta con productos.

### Cómo lo logra (alto nivel)

1. **Tiene cargados ~691 productos** (Bulit, Suprabond, Somerset,
   Tienda Suprabond) con descripción, tags, variantes, precio, imagen.
2. **Hace búsqueda híbrida**: combina búsqueda por palabra clave (BM25)
   y por similitud semántica (embeddings vectoriales) sobre 4 fuentes:
   catálogo, PDFs técnicos, web corporativa y FAQs curadas por vos.
3. **Aplica "hard rules"** que vos definís: reglas inquebrantables del
   estilo "no recomendar marcas que no sean Suprabond / Bulit /
   Somerset", "disclaimers obligatorios para químicos", etc.
4. **Le pasa todo a un LLM** (Claude Sonnet 4.6 de Anthropic), que
   genera la respuesta final con las herramientas necesarias para
   buscar más contexto si hace falta.

### Estado actual (v0.2)

- **En producción y estable**. Última iteración mayor: 2026-05-11.
- **691 productos** en el catálogo (último build de index).
- Búsqueda **híbrida** activa (BM25 + vector, peso `alpha=0.7`).
- **Backoffice completo** con 8 tabs (ver sección 6).
- **Logs de conversaciones** persistidos en SQLite con feedback público
  inline (👍/👎) y feedback operador (good / bad / flag con notas).

---

## 2. Servicios de terceros (mapa completo)

Bondi depende de los siguientes servicios externos. Esta sección lista
cada uno con: **para qué se usa**, **a qué nivel necesitás acceso**, y
**dónde se configura**. La transferencia de cada uno se describe en el
documento ELI5 que tiene Mariano (ver el cronograma de la sección 12).

### 2.1 GitHub — Código fuente

| Concepto | Detalle |
|---|---|
| Repositorio | `github.com/mariano-git88/bondi` (durante el handover se transfiere a tu cuenta o a una cuenta corporativa de Suprabond) |
| Visibilidad | **Público** — no subir secrets ahí jamás. |
| Branching | `main` única. Cada push a `main` dispara redeploy automático en Render. |
| CI | `.github/workflows/` — actualmente vacío de jobs activos (el cron de re-index se eliminó porque ya hay auto-seed al startup del backend). |
| Acceso que necesitás | **Owner** (vas a aprobar PRs, manejar permisos, configurar branch protection si querés). |

### 2.2 Render — Hosting de los servicios

| Concepto | Detalle |
|---|---|
| Plataforma | `render.com` |
| Plan | Starter (USD ~7/mes por servicio). Total: ~USD 14/mes. |
| Servicios deployados | **`bondi-api`** (FastAPI, backend del chat, dominio `bondi.suprabond.ai`) + **`bondi-kitchen`** (Streamlit, backoffice, dominio `admin.suprabond.ai`) |
| Configuración | Definida en `render.yaml` del repo. Render lee ese archivo y construye los servicios automáticamente. |
| Disco persistente | **1 GB** montado en `bondi-api` (en `/opt/render/project/src/data`). Contiene: FAISS index, SQLite DB, PDFs subidos, `curation.json`. |
| Acceso que necesitás | **Owner** del workspace. |
| Operaciones típicas | Ver logs en vivo, reiniciar servicios, cambiar env vars, monitorear costos. Todo desde el dashboard web. |

### 2.3 Anthropic (Claude) — Cerebro del chat

| Concepto | Detalle |
|---|---|
| Plataforma | `console.anthropic.com` |
| Modelo usado | `claude-sonnet-4-6` (hard-coded en `backend/agent.py` constante `MODEL`) |
| Para qué | El chat público y la generación de respuestas con tool use. |
| Costo aproximado | USD 0.005 – 0.02 por conversación (depende de longitud y de cuántas tools llame). |
| API key | Configurada como env var `ANTHROPIC_API_KEY` en el servicio `bondi-api` de Render. |
| Acceso que necesitás | **Tu propia cuenta nueva** (decidido en el handover). Vas a crear la cuenta, generar tu API key, y reemplazar la actual en Render. |
| Tope de gasto | Activá un **spending limit** en Anthropic Console → Billing → Limits (recomendado: USD 100/mes para empezar). |

### 2.4 OpenAI — Embeddings (búsqueda vectorial)

| Concepto | Detalle |
|---|---|
| Plataforma | `platform.openai.com` |
| Modelo usado | `text-embedding-3-small` (1536 dimensiones) |
| Para qué | Convertir cada documento (producto, PDF, FAQ, fragmento de web) en un vector que se guarda en FAISS. Se usa **solo durante el build del index**, no en cada conversación. |
| Costo aproximado | USD ~0.005 por build completo del index. Si hacés un build por semana = USD ~0.02/mes. |
| API key | `OPENAI_API_KEY` en env var del servicio `bondi-api`. |
| Acceso que necesitás | Cuenta con billing configurado (mismo proyecto puede compartir con otras necesidades). |
| Tope de gasto | Recomendado: USD 10/mes (muy holgado para el uso real). |

### 2.5 GoDaddy — Registro de dominio y DNS

| Concepto | Detalle |
|---|---|
| Dominio | `suprabond.ai` (registrado para todo el ecosistema de productos Suprabond, no solo Bondi). |
| Subdominios usados por Bondi | `bondi.suprabond.ai` y `admin.suprabond.ai` |
| Tipo de DNS | Dos CNAMEs apuntando a los servicios de Render (Render provee el hostname `<service>.onrender.com` para cada uno). |
| Costo | Renovación anual del dominio (~USD 80/año) — ya pagado. |
| Acceso que necesitás | Acceso al panel de GoDaddy para editar DNS si en el futuro cambian los hostnames de Render. |
| SSL | Lo maneja Render automáticamente (cert Let's Encrypt). No tenés que tocar nada. |

### 2.6 Shopify — Catálogo público (lectura, sin auth)

| Concepto | Detalle |
|---|---|
| Tienda | `tienda.suprabond.com` |
| Tipo de acceso | **Público** (endpoint JSON sin auth). Bondi llama a `/products.json` y al sitemap. |
| API key | **No usa.** No hay env var ni configuración. |
| Para qué | Cada vez que se corre `ingestion/ingest_shopify.py`, Bondi baja el catálogo completo (variantes, precios, imágenes, tags) y lo guarda en `data/products.jsonl`. |
| Frecuencia | A criterio tuyo (no es automático). Recomendado: semanal o cuando sepas que hubo cambios grandes en Shopify. |
| Dependencia | Si Shopify cae o cambia el formato del JSON, el script va a fallar. Es robusto a cambios chicos. |

### 2.7 Sitio corporativo — Web crawl (lectura, sin auth)

| Concepto | Detalle |
|---|---|
| Sitio | `www.suprabond.com` |
| Tipo de acceso | **Público** (HTTP normal). |
| Estrategia | Primero intenta leer `sitemap.xml`. Si no existe o falla, hace BFS (breadth-first search) hasta profundidad 2. |
| Para qué | Indexar páginas institucionales: categorías, hojas técnicas en HTML, contacto. |
| Configuración | `python -m ingestion.ingest_web --depth 2 --max-pages 200` (default). |
| Frecuencia recomendada | Mensual o cuando sepas que cambió contenido del sitio. |

---

## 3. Arquitectura

### 3.1 Diagrama (en texto)

```
                ┌──────────────────────┐
                │   Usuario final      │
                │   (chat público)     │
                └──────────┬───────────┘
                           │
                       HTTPS
                           │
                           ▼
              ┌─────────────────────────┐
              │   bondi.suprabond.ai    │  ← DNS GoDaddy → CNAME Render
              │   (Render: bondi-api)   │
              │                         │
              │   FastAPI + agent       │
              │   • POST /chat          │
              │   • GET  /healthz       │
              │   • GET  /catalog/stats │
              │   • POST /feedback      │  (público — 👍/👎 inline)
              │   • /admin/* (con auth) │
              └────┬───────────┬────────┘
                   │           │
        ┌──────────┘           └──────────────────┐
        │                                         │
        ▼                                         ▼
  ┌──────────┐                          ┌────────────────┐
  │ Disk 1GB │                          │   Anthropic    │
  │ /data    │                          │  (Claude API)  │
  │          │                          └────────────────┘
  │ • FAISS  │                                  │
  │ • SQLite │                                  │
  │ • PDFs   │                          ┌────────────────┐
  │ • config │                          │     OpenAI     │
  └──────────┘                          │ (embeddings)   │
                                        │   solo en      │
                                        │   build del    │
                                        │   index        │
                                        └────────────────┘

                ┌──────────────────────┐
                │   Operadora interna  │
                │   (vos, equipo)      │
                └──────────┬───────────┘
                           │
                       HTTPS + password
                           │
                           ▼
              ┌─────────────────────────┐
              │  admin.suprabond.ai     │
              │  (Render: bondi-kitchen)│
              │                         │
              │  Streamlit. NO tiene    │
              │  disk propio: todo lo   │
              │  que hace va por HTTP   │
              │  a bondi-api/admin/*    │
              └─────────────────────────┘
```

### 3.2 Flujo del chat público (lo que pasa cuando un usuario pregunta)

1. Usuario escribe en `bondi.suprabond.ai`.
2. Frontend (HTML/JS vanilla embebido en `docs/index.html`) envía `POST /chat` con la historia de la conversación.
3. El backend:
   1. Carga las **hard rules** de `curation.json` (en disco).
   2. Arma el system prompt con esas reglas.
   3. Pasa el mensaje a Claude.
   4. Claude puede llamar a la tool **`search_catalog`** (la define el backend, ejecuta búsqueda híbrida y devuelve top-K documentos).
   5. Claude responde con texto + opcionalmente la lista de productos referenciados.
4. El backend **loggea el turn completo** en SQLite (`data/bondi.db`): pregunta, respuesta, tools llamadas, documentos retornados, tokens, latencia.
5. El frontend muestra la respuesta con botones 👍/👎 inline.

### 3.3 Las 4 fuentes RAG

Cada documento indexable tiene metadata uniforme con un campo
`source_type` que indica de cuál de las 4 fuentes viene:

| `source_type` | Origen | Cómo se ingesta |
|---|---|---|
| `product` | Catálogo Shopify | `ingestion/ingest_shopify.py` baja `tienda.suprabond.com/products.json` |
| `pdf` | PDFs subidos por operadores en el backoffice | `ingestion/ingest_pdfs.py` lee `/data/pdfs/`, chunkea por página |
| `web` | Páginas del sitio `www.suprabond.com` | `ingestion/ingest_web.py` con sitemap + BFS depth-2 |
| `faq` | FAQs editadas en el backoffice | Guardadas en `curation.json`, el script de ingest las incluye |

Cada documento tiene siempre estos campos en metadata: `id`,
`source_type`, `title`, `url`, `tags`, `body_text_short`. Los productos
agregan `vendor`, `product_type`, `variants`, `image_url`, `handle`.

### 3.4 Hybrid search — cómo combina BM25 con vectores

Cuando una query llega:

1. **BM25** (keyword) rankea los documentos por coincidencia léxica.
2. **Vector** (semántico) rankea por similitud coseno entre el
   embedding de la query y los embeddings de los documentos.
3. Los dos rankings se **normalizan a [0, 1]** y se combinan con un
   peso `alpha = 0.7` (default — más peso a vector que a BM25).

Esto da el mejor de los dos mundos: BM25 atrapa coincidencias exactas
de SKU o palabras técnicas, y vector atrapa similitudes semánticas
("para pegar madera" matchea con productos cuyo título dice "adhesivo
para carpintería").

### 3.5 Hard rules

Las hard rules viven en `curation.json` (en disco persistente del
backend). Se editan desde la tab **Hard Rules** del backoffice. Se
cargan **en cada request al endpoint `/chat`** — o sea: si las cambiás
en el backoffice, el siguiente mensaje del chat ya las usa (hot
reload).

Ejemplos típicos:
- "No recomendar productos de otras marcas. Solo Suprabond, Bulit y
  Somerset."
- "Para productos químicos, recordá siempre las hojas de seguridad."
- "Si el usuario pregunta por precios, redirigilo a la tienda."

### 3.6 Logging

Cada conversación se guarda en SQLite (`data/bondi.db`) con:

- `turn_id`, `conversation_id`, `timestamp`.
- Mensajes (usuario y asistente).
- Tools llamadas y resultados.
- Tokens usados (input/output).
- Latencia.
- Feedback público inline (👍/👎).
- Feedback operador (good/bad/flag) con nota opcional.

Lo ves desde la tab **Conversaciones** del backoffice. La DB queda en
el disco persistente — si Render reinicia el servicio, los logs no se
pierden.

---

## 4. Estructura del repositorio

```
bondi/
├── backend/                # FastAPI + agent (lo que sirve bondi-api)
│   ├── main.py             # endpoints HTTP
│   ├── agent.py            # llamada a Claude con tool use
│   ├── tools.py            # definición de tools (search_catalog)
│   ├── retrieval.py        # hybrid search (BM25 + vector)
│   ├── curation.py         # carga de FAQs + hard rules
│   ├── db.py               # SQLite (init, insertar turn, etc.)
│   └── pricing.py          # cálculo de costos por turn
├── backoffice/             # Streamlit (lo que sirve bondi-kitchen)
│   ├── app.py              # 8 tabs del backoffice
│   ├── theme.py            # estilos
│   └── api_client.py       # cliente HTTP del backend
├── frontend/               # chat público (HTML/JS vanilla)
│   └── (servido como static por backend)
├── ingestion/              # scripts de carga de fuentes
│   ├── ingest_shopify.py   # baja catálogo Shopify
│   ├── ingest_pdfs.py      # chunkea PDFs
│   └── ingest_web.py       # crawler web
├── embeddings/             # build + search del FAISS
│   ├── build_index.py      # llama a OpenAI, guarda FAISS
│   └── search.py           # SearchEngine class
├── data/                   # ⚠️ EN PRODUCCIÓN, NO EN REPO (gitignored)
│   ├── products.jsonl      # catálogo Shopify cacheado
│   ├── web.jsonl           # páginas web cacheadas
│   ├── index.faiss         # vector index
│   ├── index.meta.json     # metadata de los docs del index
│   ├── curation.json       # FAQs + hard rules
│   ├── bondi.db            # SQLite logs
│   └── pdfs/               # PDFs subidos por operadores
├── docs/                   # frontend embebido + docs varios
│   └── index.html          # HTML del chat público
├── assets/                 # imágenes y estáticos
├── .github/workflows/      # CI (actualmente sin jobs activos)
├── render.yaml             # blueprint Render (define los 2 services)
├── Procfile                # comando alternativo (no usado en Render)
├── requirements.txt        # dependencias Python
├── .env.example            # plantilla de env vars
├── README.md               # README técnico (referencia)
└── HANDOVER.md             # este documento
```

---

## 5. Operación día a día — el backoffice (kitchen)

### 5.1 Entrar al backoffice

1. Andá a `https://admin.suprabond.ai`.
2. Ingresá la password de operador (es la env var `BONDI_ADMIN_PASS`
   del servicio `bondi-kitchen` — Mariano te la pasa por canal seguro
   en el handover).
3. Una vez adentro, vas a ver **8 tabs** en la parte superior.

### 5.2 Las 8 tabs explicadas

#### Tab 📊 Dashboard

Vista de salud general:

- **Stats del backend**: si está vivo, latencia del healthcheck, versión.
- **Tamaño del catálogo**: cuántos productos, cuántas FAQs, cuántos PDFs.
- **Conversaciones de las últimas 24h** (cantidad).
- **Errores recientes** si hubo.

Si algo está rojo, mirá la tab Salud (la última) para más detalle.

#### Tab 💬 Conversaciones

Listado de cada turn del chat público. Cada fila tiene:

- Pregunta del usuario, respuesta del asistente.
- Documentos retornados por la búsqueda (los que Claude usó como contexto).
- Feedback público (👍/👎 que dejó el usuario final).
- **Botones de feedback operador**: `✓ buena`, `✗ mala`, `🚩 marcar`,
  con campo de nota.

**Para qué te sirve**: revisar qué pregunta la gente, identificar
respuestas malas, marcar para mejorar (típicamente: si una respuesta
fue mala, mirás qué FAQ o hard rule podría haberlo evitado, y la
agregás).

#### Tab 📋 Curaduría (FAQs)

CRUD de FAQs (preguntas frecuentes editadas a mano):

- **Agregar**: tipeás pregunta y respuesta, tags opcionales.
- **Editar**: tocar cualquier FAQ existente.
- **Borrar**: con confirmación.

Cada FAQ se vuelve un documento indexable con `source_type=faq`.

⚠️ **Después de agregar/editar FAQs, hay que hacer Rebuild Index** (tab
Index) para que el chat las vea.

#### Tab ⚖️ Hard Rules

Editor de las reglas inquebrantables del system prompt. Es un campo
de texto Markdown grande. Cada línea o bullet es una regla.

**Hot reload**: apenas guardás, el siguiente `/chat` ya las usa. **No
hace falta Rebuild Index** para hard rules.

#### Tab 📄 PDFs

Subir / borrar / re-ingestar PDFs:

- **Drag & drop** un PDF nuevo → se guarda en `data/pdfs/`.
- **Botón "Re-ingestar PDFs"** → corre `ingestion/ingest_pdfs.py` en el
  servidor, que chunkea por página y genera documentos.
- **Botón "Borrar"** por PDF.

⚠️ **Después de subir/borrar PDFs, hay que: 1) Re-ingestar PDFs, 2)
Rebuild Index, 3) Reload backend.**

#### Tab 🌐 Crawl Web

Re-crawl del sitio corporativo:

- Botón **"Re-crawlear"** dispara `ingestion/ingest_web.py`.
- Muestra cuántas páginas bajó y errores si hubo.

⚠️ Después: Rebuild Index + Reload backend.

#### Tab 🔧 Index

Operaciones del índice de búsqueda:

- **Rebuild Index**: corre `embeddings/build_index.py`. Genera nuevos
  vectores para todos los documentos (productos + PDFs + web + FAQs).
  Tarda ~15 segundos. **Costo: ~USD 0.005 a OpenAI.**
- **Reload Backend**: tras un rebuild, el backend tiene que recargar el
  índice nuevo en memoria. Este botón hace eso (llama al endpoint
  `/admin/reload`).

**Orden típico después de cambios**:

```
1. (cambios en backoffice — FAQs / PDFs / Web)
2. Rebuild Index
3. Reload Backend
```

#### Tab 🧪 Test

Probar una pregunta sin loguearla. Útil para experimentar:

- Tipeás una query.
- Te muestra los documentos retornados por hybrid search (con sus
  scores BM25 y vector).
- Opcionalmente, te muestra la respuesta del agent.

**No se guarda en logs.** Pensado para iterar sin contaminar las
conversaciones reales.

#### Tab 🩺 Salud

Diagnóstico técnico:

- Status detallado del backend (memoria, uptime, índice cargado).
- Tamaño de las tablas SQLite.
- Errores recientes.
- Versión del modelo Claude en uso.

---

## 6. Workflows típicos

### "Un usuario preguntó algo que el chat no supo responder"

1. Vas a tab **Conversaciones**.
2. Filtrás por feedback 👎 público o buscás por palabra clave.
3. Encontrás la conversación, leés.
4. Decidís qué falta:
   - **Falta una FAQ** → tab Curaduría → agregar → tab Index → Rebuild + Reload.
   - **Falta una regla** → tab Hard Rules → agregar línea → guardar (hot reload, listo).
   - **Falta un PDF técnico** → tab PDFs → subir → re-ingestar → tab Index → Rebuild + Reload.
   - **El catálogo no tiene el producto** → confirmar con Shopify, después tab Crawl Web o ingest_shopify si aplica.

### "Subo un PDF nuevo de un proveedor"

1. Tab PDFs → drag & drop.
2. Verificá que el nombre del archivo tenga sentido (queda como `pdf-<slug>` en el index).
3. Botón "Re-ingestar PDFs".
4. Tab Index → Rebuild → Reload.
5. Tab Test → probá una pregunta que el PDF debería responder.

### "El catálogo de Shopify se actualizó"

1. (Esto NO es automático.) Cuando sepas que hubo cambios grandes en
   Shopify, andá a la tab Crawl Web → ojo, ese botón es para el sitio
   corporativo, no Shopify. Para Shopify, hace falta correr el script
   `ingest_shopify.py` desde el backend o pedirle a Sistemas.
2. Después: Rebuild Index → Reload.

> Nota: hoy no hay un botón en el backoffice que dispare
> `ingest_shopify` directamente. Si lo necesitás como botón, es una
> mejora chica al backoffice — coordinar con Sistemas.

### "Quiero agregar una hard rule nueva"

1. Tab Hard Rules → editar el campo de texto.
2. Guardar.
3. Ya está. El próximo mensaje al `/chat` la usa.

### "Quiero probar cómo el chat respondería sin que quede en logs"

1. Tab Test → tipear la pregunta.
2. Ver documentos retornados y respuesta.

---

## 7. Setup local (opcional — si querés correrlo en tu máquina para debugging)

Sólo necesario si vas a modificar código. Para operar día a día, el
backoffice deployado en `admin.suprabond.ai` es suficiente.

```bash
# 1. Clonar el repo (ya con tu cuenta GitHub tras la transferencia)
git clone https://github.com/<tu-usuario>/bondi.git
cd bondi

# 2. Crear virtualenv
python -m venv .venv
source .venv/bin/activate         # Mac / Linux / WSL
# .venv\Scripts\activate          # Windows PowerShell

# 3. Instalar dependencias
pip install -r requirements.txt

# 4. Configurar variables de entorno
cp .env.example .env
# Editar .env y poner tus API keys (de tu cuenta Anthropic, OpenAI personal o del proyecto)

# 5. Buildear el corpus por primera vez
export OPENAI_API_KEY=sk-...
python ingestion/ingest_shopify.py
python -m ingestion.ingest_web --depth 2 --max-pages 200
python -m embeddings.build_index

# 6. Correr backend
uvicorn backend.main:app --reload --port 8000

# 7. En otra terminal, correr backoffice
export BONDI_BACKEND_URL=http://localhost:8000
streamlit run backoffice/app.py
```

Abrí `http://localhost:8501` para el backoffice y `http://localhost:8000`
para el chat.

---

## 8. Deploy en Render

Render redeploya automáticamente cada push a `main`. No tenés que hacer
nada manual. Si querés disparar un redeploy a mano (ej. tras editar
env vars):

1. Render → tu servicio → **Manual Deploy** → "Deploy latest commit".

### Ver logs en vivo

Render → tu servicio → tab **Logs**. Muestra stdout/stderr en streaming.

### Cambiar una env var

Render → tu servicio → **Environment** → editar/agregar → **Save** →
te pregunta si redeploya, decí que sí.

### Reiniciar un servicio

Render → tu servicio → **Manual Deploy** → "Clear build cache and
deploy" (si querés rebuild completo) o "Restart" (más rápido).

### Disco persistente

El disco de `bondi-api` está en `/opt/render/project/src/data`.
Contiene:

- `index.faiss` y `index.meta.json` (rebuild lo regenera).
- `bondi.db` (SQLite logs — NO regenerable, perderlo es perder
  historial).
- `pdfs/` (los PDFs subidos).
- `curation.json` (FAQs + hard rules — NO regenerable, perderlo es
  perder todo lo curado).

**Recomendación**: bajar periódicamente un backup de `bondi.db` y
`curation.json`. Render tiene snapshot del disco pero conviene
descargar copia local.

### Si Render se cae

1. Mirá `https://status.render.com`.
2. Si está caído, no podés hacer mucho.
3. Si está OK pero tu servicio no responde, mirá los logs (probable
   error en código o en startup).

---

## 9. Costos mensuales (referencia)

| Servicio | Costo aproximado |
|---|---|
| Render `bondi-api` (Starter) | USD 7 |
| Render `bondi-kitchen` (Starter) | USD 7 |
| Disco persistente 1 GB | incluido en Starter |
| Anthropic (Claude API) | USD 30-100 (depende del volumen de chat) |
| OpenAI (embeddings) | < USD 1 (sólo en builds) |
| GoDaddy (dominio anual) | USD ~80/año ≈ USD ~7/mes |
| **Total estimado** | **USD ~55-130/mes** |

Picos típicos: si el chat se viraliza o si hay errores que generan
muchos reintentos, el costo de Anthropic puede multiplicarse. **Tener
el spending limit configurado es importante.**

---

## 10. Troubleshooting común

### El chat no responde / muestra error

1. Mirá `bondi.suprabond.ai/healthz` → debe devolver `{"status":"ok"}`.
2. Si no: Render → `bondi-api` → Logs. Buscá el último error.
3. Causas típicas:
   - **API key vencida** (Anthropic o OpenAI revocó la key) → regenerar
     en consola del proveedor y actualizar env var en Render.
   - **Tope de gasto alcanzado** (en Anthropic) → ver Billing en
     Anthropic Console.
   - **Disk lleno** (poco probable con 1GB) → mirar tab Salud en
     backoffice.

### El backoffice no me deja entrar

1. Verificar la password.
2. Si la cambiaron recientemente, verificá que la env var
   `BONDI_ADMIN_PASS` esté actualizada en **ambos** servicios (api y
   kitchen).

### Rebuild Index falla

1. Mirá la salida del comando en el backoffice (debe mostrar el error).
2. Causas típicas:
   - OpenAI API key inválida o sin saldo.
   - Algún documento corrupto (PDF roto, FAQ con caracteres raros).

### Una FAQ que agregué no aparece en el chat

1. ¿Hiciste **Rebuild Index** después de agregarla?
2. ¿Hiciste **Reload Backend** después del rebuild?
3. Si las dos sí, probá la pregunta en la tab Test y mirá si la FAQ
   aparece en los documentos retornados (con score de BM25/vector).

---

## 11. Backlog conocido y ideas

Cosas que no están implementadas o tienen mejoras posibles. Tomalo
como base para tu propio backlog:

### Operativas

- **Botón en el backoffice para re-ingestar Shopify** (hoy hay que
  pedirlo por código). 1-2 hs de trabajo.
- **Backup automático** de `bondi.db` y `curation.json` a un bucket
  externo (S3, R2, Google Drive). Render no lo hace solo.
- **Métricas más ricas** en el dashboard: trends de feedback por
  semana, top queries no resueltas, etc.

### Producto

- **Memoria conversacional persistente** entre sesiones (hoy el chat
  es stateless: el usuario final no tiene perfil).
- **Versionado de hard rules** (hoy se sobreescriben sin historial).
- **Multi-idioma** (hoy responde sólo en español).
- **Integración con WhatsApp** o canal alternativo además del chat web.

### Técnicas

- Migrar SQLite a Postgres si el volumen sube fuerte (>10k turns/día).
- Cachear las respuestas del agent para queries frecuentes (reduce
  costo de Claude).
- Reemplazar `text-embedding-3-small` por algo más nuevo si OpenAI
  saca un mejor modelo.

---

## 12. Contactos y soporte

### Equipo Suprabond

- **Vos**: Jefa de Canales Digitales — owner del proyecto.
- **Sistemas Suprabond**: para integraciones con otros sistemas
  internos, accesos, y dudas de infraestructura corporativa.
- **Mariano Pappalardo** (transición): disponible para consultas
  técnicas durante las primeras 4 semanas del handover. Después de eso,
  el proyecto queda 100% en tu lado.

### Soporte de proveedores

- **Render**: chat en el dashboard, response time ~horas.
- **Anthropic**: `support@anthropic.com` para temas de cuenta.
  Discord/forum para temas técnicos del SDK.
- **OpenAI**: `help.openai.com` para temas de cuenta y billing.
- **GoDaddy**: chat 24/7 desde el panel.

---

## 13. Anexos

### Glosario rápido

| Término | Significado |
|---|---|
| **RAG** | Retrieval Augmented Generation. Estrategia donde primero se busca contexto en una base de datos y después se le pasa a un LLM. |
| **Embedding** | Vector numérico (1536 dimensiones) que representa el significado de un texto. Textos parecidos = vectores cercanos. |
| **FAISS** | Librería de Facebook para búsqueda eficiente de vectores cercanos. |
| **BM25** | Algoritmo clásico de búsqueda por palabras (TF-IDF mejorado). |
| **Hybrid search** | Combinar BM25 (palabras) + vectores (semántica) para mejor recall. |
| **Tool use** | Capacidad de Claude de llamar funciones definidas en el código del backend para buscar más contexto antes de responder. |
| **System prompt** | Instrucciones iniciales que se le pasan al LLM y que aplican a toda la conversación. |
| **Hard rules** | Reglas que vos definís y se incrustan en el system prompt. |
| **Hot reload** | Recargar configuración sin reiniciar el servicio. |
| **Healthcheck** | Endpoint `/healthz` que Render usa para saber si tu servicio está vivo. |

### Links importantes

- Repo: `github.com/mariano-git88/bondi` (a transferir)
- Chat público: `https://bondi.suprabond.ai`
- Backoffice: `https://admin.suprabond.ai`
- Render: `dashboard.render.com`
- Anthropic Console: `console.anthropic.com`
- OpenAI Platform: `platform.openai.com`
- GoDaddy: `dcc.godaddy.com`

### Archivos del repo a tener a mano

- `README.md` — descripción técnica general.
- `render.yaml` — configuración de deploy.
- `.env.example` — variables de entorno que necesita.
- `backend/agent.py` — modelo Claude y lógica del agent.
- `backend/main.py` — endpoints HTTP.
- `backoffice/app.py` — las 8 tabs del backoffice.

---

**Fin del documento.** Si quedó algo confuso o creés que falta algo,
anotalo y consultalo con Mariano durante la ventana de transición.
Bienvenida al proyecto.
