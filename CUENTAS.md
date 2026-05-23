# Cuentas a crear — Bondi

Servicios externos donde necesitás abrir una cuenta para operar Bondi.
Usá tu email corporativo en todos. Cuando termines, tildá cada uno.

> **Tip**: creá todas las cuentas el mismo día, antes de empezar el
> handover técnico. Algunas piden verificación por mail que puede
> tardar minutos.

---

- [ ] **GitHub** — `https://github.com/signup`
  Código fuente del proyecto. Vas a recibir el repo `bondi` por
  transferencia.

- [ ] **Render** — `https://render.com/register`
  Hosting de los dos servicios deployados (chat público + backoffice).
  Te conviene vincularla con tu cuenta de GitHub recién creada
  (la usa al conectar el repo).

- [ ] **Anthropic (Claude)** — `https://console.anthropic.com/login`
  Modelo de lenguaje del chat (cerebro de Bondi). Genera una API key
  desde Console → API Keys.
  **Pone un spending limit** en Billing → Limits (sugerido: USD 100/mes).

- [ ] **OpenAI** — `https://platform.openai.com/signup`
  Embeddings (búsqueda por similitud semántica). Solo se usa al
  reconstruir el índice, así que el gasto es bajo.
  **Spending limit sugerido**: USD 10/mes.

- [ ] **GoDaddy** — `https://account.godaddy.com/products`
  DNS del dominio `suprabond.ai` (apunta los subdominios `bondi.` y
  `admin.` al hosting de Render). Solo necesitás acceso si en algún
  momento cambian los CNAMEs.

---

## Servicios que NO requieren cuenta nueva

Bondi también consume **Shopify** (catálogo `tienda.suprabond.com`) y
el **sitio corporativo** (`www.suprabond.com`), pero los lee como
páginas públicas — no hace falta cuenta ni API key.

---

**Próximo paso después de crear las cuentas**: avisarle a Mariano para
que arranque la transferencia de ownership (GitHub → tu cuenta, Render
→ tu workspace, y reemplazo de la API key de Anthropic por la tuya).
