"""
theme.py — Tema visual del Kitchen de Bondi.

Inspiración: el logo (gota amarilla con aura multicolor) + la tienda
Suprabond (naranja CTA + blanco + sans-serif limpia). La estética
busca:

  - Calidez. Fondos warm-white (no blancos puros), grises oscuros
    cálidos en vez de negro puro, amarillo del logo como hint
    secundario.
  - Profesionalismo. Tipografía dominante, jerarquía clara, métricas
    grandes pero no estridentes.
  - Identidad. Acentos del aura del logo (amarillo, naranja, rojo,
    azul) usados con disciplina — solo en lo que el ojo necesita
    seguir (CTA, tab activa, hover).

Coexistencia con el frontend chat (`frontend/index.html`): paleta
compartida — los operadores ven el mismo lenguaje visual que los
visitantes.

Llamar `apply_theme()` UNA vez al inicio, después de
`st.set_page_config()`.
"""

from pathlib import Path

import streamlit as st

LOGO_PATH = Path(__file__).parent.parent / "assets" / "logo.png"

# ----- Paleta brand -----
YELLOW = "#FACA28"         # gota del logo
YELLOW_SOFT = "#FFF4C9"    # fondo cálido sutil
YELLOW_GLOW = "#FDE36B"
ORANGE = "#C8552F"         # naranja Suprabond, CTA principal
ORANGE_DARK = "#A8451F"
ORANGE_SOFT = "#FFE5D5"
CORAL = "#F87171"

# Acentos del aura (uso muy puntual)
AURA_RED = "#E63946"
AURA_BLUE = "#2563EB"
AURA_GREEN = "#16A34A"

# Neutros cálidos
INK = "#2A2422"            # casi negro pero cálido
INK_SOFT = "#4D4540"
TEXT_SOFT = "#8B7E73"
LINE = "#EFE6D8"
LINE_STRONG = "#D9CDB8"
LINE_SOFTBG = "#FFFAF0"    # warm white
WHITE = "#FFFFFF"


CUSTOM_CSS = f"""
<style>
/* ==============================================================
   Bondi — Kitchen theme (warm + brand-aligned)
   ============================================================== */

html, body, [data-testid="stAppViewContainer"], [class*="css"] {{
    font-family: -apple-system, BlinkMacSystemFont, "Inter", "Helvetica Neue",
                 Helvetica, Arial, sans-serif;
    color: {INK};
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}}

[data-testid="stAppViewContainer"] {{
    background-color: {LINE_SOFTBG};
}}

/* ----- Headings ----- */
h1 {{
    color: {INK} !important;
    font-weight: 700 !important;
    font-size: 2.2rem !important;
    letter-spacing: -0.025em !important;
    line-height: 1.15 !important;
    margin: 0 0 0.5rem 0 !important;
}}
h2 {{
    color: {INK} !important;
    font-weight: 600 !important;
    font-size: 1.45rem !important;
    letter-spacing: -0.015em !important;
    line-height: 1.25 !important;
    margin: 2.25rem 0 1rem 0 !important;
    padding-bottom: 0.5rem;
    border-bottom: 1px solid {LINE};
}}
h3 {{
    color: {INK} !important;
    font-weight: 600 !important;
    font-size: 1.05rem !important;
    letter-spacing: -0.005em !important;
    margin: 1.75rem 0 0.85rem 0 !important;
}}
p, div, span, li {{
    line-height: 1.6;
}}

/* ----- Logo en sidebar ----- */
[data-testid="stLogo"] img,
[data-testid="stSidebarHeader"] img {{
    max-height: 220px !important;
    max-width: 100% !important;
    width: auto !important;
    height: auto !important;
    margin: 0.75rem auto 1rem auto !important;
    display: block !important;
}}
[data-testid="stSidebarHeader"],
[data-testid="stLogo"],
[data-testid="stSidebarHeader"] > div,
[data-testid="stLogoSpacer"] {{
    height: auto !important;
    min-height: 0 !important;
    max-height: none !important;
    overflow: visible !important;
    padding-top: 0.5rem !important;
    padding-bottom: 0.5rem !important;
}}

/* ----- Sidebar cremita (yellow-soft del logo) -----
   Streamlit cambia el selector entre versiones; usamos varios + !important
   en cada uno para asegurar el fondo en todas. ----- */
[data-testid="stSidebar"],
section[data-testid="stSidebar"],
[data-testid="stSidebar"] > div,
[data-testid="stSidebar"] > div:first-child,
[data-testid="stSidebarContent"],
[data-testid="stSidebarUserContent"] {{
    background-color: {YELLOW_SOFT} !important;
    border-right: 1px solid {LINE_STRONG} !important;
}}
/* Inputs dentro del sidebar mantienen fondo blanco para contraste */
[data-testid="stSidebar"] .stTextInput input,
[data-testid="stSidebar"] .stNumberInput input,
[data-testid="stSidebar"] .stTextArea textarea,
[data-testid="stSidebar"] div[data-baseweb="select"] > div {{
    background-color: {WHITE} !important;
}}
[data-testid="stSidebar"] h2 {{
    border: none !important;
    padding: 0 !important;
    font-size: 0.78rem !important;
    text-transform: uppercase;
    letter-spacing: 0.12em !important;
    color: {TEXT_SOFT} !important;
    margin-top: 1.75rem !important;
    margin-bottom: 0.75rem !important;
    font-weight: 600 !important;
}}
[data-testid="stSidebar"] h1 {{
    font-size: 1.4rem !important;
    margin-bottom: 0.25rem !important;
    color: {INK} !important;
}}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] {{
    color: {TEXT_SOFT};
    font-size: 0.82rem;
}}

/* ----- Botones: naranja Suprabond CTA con redondeo cálido ----- */
.stButton > button,
.stDownloadButton > button,
[data-testid="stFormSubmitButton"] > button {{
    background-color: {ORANGE};
    color: {WHITE};
    border: none;
    border-radius: 10px;
    padding: 0.65rem 1.4rem;
    font-weight: 600;
    font-size: 0.92rem;
    letter-spacing: 0.01em;
    transition: background-color 0.18s ease, transform 0.1s ease, box-shadow 0.18s ease;
    box-shadow: 0 1px 3px rgba(200, 85, 47, 0.25);
}}
.stButton > button:hover,
.stDownloadButton > button:hover,
[data-testid="stFormSubmitButton"] > button:hover {{
    background-color: {ORANGE_DARK};
    color: {WHITE};
    transform: translateY(-1px);
    box-shadow: 0 4px 10px rgba(200, 85, 47, 0.32);
}}
.stButton > button:active,
.stDownloadButton > button:active,
[data-testid="stFormSubmitButton"] > button:active {{
    transform: translateY(0);
}}
/* Botón secondary (cuando no es primary) — usar bordes warm */
.stButton > button[kind="secondary"] {{
    background-color: {WHITE};
    color: {INK};
    border: 1.5px solid {LINE_STRONG};
    box-shadow: none;
}}
.stButton > button[kind="secondary"]:hover {{
    background-color: {YELLOW_SOFT};
    border-color: {YELLOW};
    color: {INK};
    box-shadow: 0 2px 6px rgba(250, 202, 40, 0.18);
}}

/* ----- File uploader: borde redondeado warm ----- */
[data-testid="stFileUploader"] section {{
    border: 1.5px dashed {LINE_STRONG} !important;
    border-radius: 12px !important;
    background-color: {WHITE} !important;
    padding: 1.2rem !important;
    transition: border-color 0.18s ease, background-color 0.18s ease;
}}
[data-testid="stFileUploader"] section:hover {{
    border-color: {ORANGE} !important;
    background-color: {ORANGE_SOFT} !important;
}}
[data-testid="stFileUploader"] small {{
    color: {TEXT_SOFT};
    font-size: 0.8rem;
}}
[data-testid="stFileUploader"] label {{
    font-size: 0.85rem !important;
    font-weight: 600 !important;
    color: {INK} !important;
}}

/* ----- Inputs: bordes redondeados con focus naranja ----- */
.stTextInput input,
.stNumberInput input,
.stTextArea textarea {{
    border-radius: 10px !important;
    border: 1.5px solid {LINE} !important;
    padding: 0.65rem 0.9rem !important;
    font-size: 0.95rem !important;
    background-color: {WHITE} !important;
    color: {INK} !important;
    transition: border-color 0.15s ease, box-shadow 0.15s ease;
}}
.stTextInput input:focus,
.stNumberInput input:focus,
.stTextArea textarea:focus {{
    border-color: {ORANGE} !important;
    box-shadow: 0 0 0 3px rgba(200, 85, 47, 0.12) !important;
    outline: none !important;
}}

/* ----- Metrics: tipografía dominante + delta cálido ----- */
[data-testid="stMetric"] {{
    background-color: {WHITE};
    border: 1px solid {LINE};
    border-radius: 12px;
    padding: 1rem 1.2rem;
    box-shadow: 0 1px 2px rgba(42, 36, 34, 0.04);
}}
[data-testid="stMetricValue"] {{
    color: {INK} !important;
    font-weight: 700 !important;
    font-size: 2.1rem !important;
    letter-spacing: -0.02em !important;
    line-height: 1.1 !important;
}}
[data-testid="stMetricLabel"] {{
    color: {TEXT_SOFT} !important;
    font-weight: 600 !important;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    font-size: 0.72rem !important;
}}
[data-testid="stMetricDelta"] {{
    color: {ORANGE} !important;
    font-weight: 600 !important;
}}

/* ----- Dataframes ----- */
[data-testid="stDataFrame"] {{
    border-radius: 12px !important;
    border: 1px solid {LINE} !important;
    box-shadow: 0 1px 2px rgba(42, 36, 34, 0.04) !important;
    overflow: hidden;
}}

/* ----- Tabs: pill activa amarilla + borde inferior naranja ----- */
[data-testid="stTabs"] {{
    border-bottom: 1px solid {LINE};
    margin-bottom: 1.5rem;
}}
[data-testid="stTabs"] [role="tablist"] {{
    display: flex !important;
    width: 100% !important;
    gap: 4px;
}}
[data-testid="stTabs"] button[role="tab"] {{
    flex: 1 1 0 !important;
    min-width: 0 !important;
    padding: 0.6rem 0.7rem !important;
    background-color: {WHITE} !important;
    border-radius: 10px 10px 0 0 !important;
    color: {TEXT_SOFT} !important;
    font-weight: 500 !important;
    font-size: 0.92rem !important;
    letter-spacing: 0.01em;
    border: none !important;
    border-bottom: 3px solid transparent !important;
    margin-bottom: -1px;
    text-align: center;
    justify-content: center;
    transition: background-color 0.15s ease, color 0.15s ease;
}}
[data-testid="stTabs"] button[role="tab"]:hover {{
    color: {INK} !important;
    background-color: {YELLOW_SOFT} !important;
}}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"] {{
    color: {INK} !important;
    background-color: {YELLOW_SOFT} !important;
    border-bottom: 3px solid {ORANGE} !important;
    font-weight: 700 !important;
}}

/* ----- Forms (login card) ----- */
[data-testid="stForm"] {{
    background-color: {WHITE};
    border: 1px solid {LINE};
    border-radius: 14px;
    padding: 2rem;
    box-shadow: 0 2px 6px rgba(42, 36, 34, 0.04);
}}

/* ----- Alertas: bordes finos con redondeo warm ----- */
[data-testid="stAlert"] {{
    border-radius: 10px !important;
    border: 1px solid {LINE} !important;
    border-left-width: 4px !important;
    box-shadow: none !important;
    padding: 0.85rem 1.1rem !important;
    background-color: {WHITE} !important;
}}
[data-testid="stAlert"][data-baseweb="notification"] {{
    background-color: {WHITE} !important;
}}

/* ----- Captions ----- */
[data-testid="stCaptionContainer"], .stCaption {{
    color: {TEXT_SOFT};
    font-size: 0.85rem;
    line-height: 1.55;
}}

/* ----- Expanders: bordes warm con redondeo ----- */
[data-testid="stExpander"] {{
    border: 1px solid {LINE} !important;
    border-radius: 12px !important;
    background-color: {WHITE} !important;
    box-shadow: none !important;
    overflow: hidden;
}}
[data-testid="stExpander"] summary {{
    padding: 0.9rem 1.1rem !important;
    font-weight: 600 !important;
    font-size: 0.92rem !important;
    background-color: transparent !important;
}}
[data-testid="stExpander"] summary:hover {{
    background-color: {YELLOW_SOFT} !important;
}}

/* ----- Radio / Checkbox ----- */
.stRadio > div {{ gap: 1rem !important; }}
.stRadio label {{ font-size: 0.9rem !important; color: {INK} !important; }}

/* ----- Selectbox ----- */
.stSelectbox div[data-baseweb="select"] > div {{
    border-radius: 10px !important;
    border: 1.5px solid {LINE} !important;
    background-color: {WHITE} !important;
}}
.stSelectbox div[data-baseweb="select"]:hover > div {{
    border-color: {ORANGE} !important;
}}

/* ----- Slider: track naranja ----- */
.stSlider [data-baseweb="slider"] [role="slider"] {{
    background-color: {ORANGE} !important;
    border: 2px solid {WHITE} !important;
    box-shadow: 0 1px 3px rgba(200, 85, 47, 0.3) !important;
}}

/* ----- Divider ----- */
hr {{
    border-color: {LINE} !important;
    margin: 2rem 0 !important;
}}

/* ----- Code blocks: fondo warm sutil ----- */
.stCode, pre {{
    background-color: {LINE_SOFTBG} !important;
    border: 1px solid {LINE} !important;
    border-radius: 10px !important;
}}

/* ----- Hide Streamlit chrome -----
   Ocultamos solo decoraciones cosméticas. NO ocultar el header ni el
   toolbar entero: el botón para reabrir el sidebar colapsado vive ahí
   y necesita seguir visible. ----- */
#MainMenu {{ visibility: hidden; }}
footer {{ visibility: hidden; }}
header [data-testid="stDecoration"] {{ display: none; }}
/* Ocultar el botón "Deploy" arriba-derecha (sólo ese, no todo el toolbar). */
[data-testid="stToolbarActions"] {{ visibility: hidden; }}

/* Asegurar que el control para re-expandir el sidebar SIEMPRE sea
   visible cuando el sidebar está colapsado. Streamlit usa varios
   nombres distintos según versión, los apuntamos todos. */
[data-testid="stSidebarCollapsedControl"],
[data-testid="collapsedControl"],
[data-testid="stSidebarCollapseButton"] {{
    visibility: visible !important;
    display: flex !important;
    opacity: 1 !important;
    background-color: {WHITE} !important;
    border: 1px solid {LINE_STRONG} !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 3px rgba(42, 36, 34, 0.08) !important;
    z-index: 999 !important;
}}
[data-testid="stSidebarCollapsedControl"] button,
[data-testid="collapsedControl"] button {{
    color: {INK} !important;
}}
[data-testid="stSidebarCollapsedControl"]:hover,
[data-testid="collapsedControl"]:hover {{
    background-color: {YELLOW_SOFT} !important;
    border-color: {YELLOW} !important;
}}

/* ----- Container principal ----- */
[data-testid="stAppViewContainer"] > .main > .block-container {{
    padding-top: 2.5rem !important;
    padding-bottom: 5rem !important;
    padding-left: 3rem !important;
    padding-right: 3rem !important;
    max-width: 1240px;
    background-color: {LINE_SOFTBG};
}}

/* Texto fuerte un pelín más oscuro */
strong, b {{ font-weight: 600; color: {INK}; }}

/* Spinner: usar naranja en vez del rosa default */
.stSpinner > div > div {{
    border-top-color: {ORANGE} !important;
}}
</style>
"""


def apply_theme() -> None:
    """Aplicar el theme al app Streamlit. Llamar UNA vez al inicio."""
    if LOGO_PATH.exists():
        st.logo(str(LOGO_PATH))
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)
