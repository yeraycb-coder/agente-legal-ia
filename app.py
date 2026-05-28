import streamlit as st
import anthropic
from tavily import TavilyClient
import requests
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

def get_secret(key):
    try:
        return st.secrets[key]
    except Exception:
        return os.getenv(key, "")

# ── Configuración de página ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Asistente Jurídico IA",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ── Estilos ───────────────────────────────────────────────────────────────────
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .header-box {
        background: linear-gradient(135deg, #0A1628 0%, #1a2f52 100%);
        color: white;
        padding: 2rem 2.5rem;
        border-radius: 16px;
        margin-bottom: 1.5rem;
    }
    .header-box h1 { font-size: 1.8rem; font-weight: 700; margin: 0; }
    .header-box p  { color: #00E5D4; font-size: 0.9rem; margin: 0.3rem 0 0; }

    .source-card {
        background: #f8fafc;
        border: 1px solid #e2e8f0;
        border-left: 4px solid #00E5D4;
        border-radius: 8px;
        padding: 0.7rem 1rem;
        margin-bottom: 0.5rem;
        font-size: 0.85rem;
    }
    .source-card a { color: #0A1628; font-weight: 600; text-decoration: none; }
    .source-card a:hover { text-decoration: underline; }
    .source-domain { color: #64748b; font-size: 0.75rem; }

    .not-found-box {
        background: #fff7ed;
        border: 1px solid #fed7aa;
        border-radius: 10px;
        padding: 1rem 1.2rem;
        color: #9a3412;
        font-size: 0.9rem;
    }

    .badge {
        display: inline-block;
        padding: 0.2rem 0.7rem;
        border-radius: 999px;
        font-size: 0.75rem;
        font-weight: 600;
        margin-right: 0.3rem;
    }
    .badge-leg  { background:#dbeafe; color:#1d4ed8; }
    .badge-jur  { background:#d1fae5; color:#065f46; }
    .badge-gen  { background:#ede9fe; color:#5b21b6; }

    .disclaimer {
        background: #fef9c3;
        border: 1px solid #fde047;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-size: 0.78rem;
        color: #713f12;
        margin-top: 0.5rem;
    }

    [data-testid="stChatMessage"] { padding: 0.8rem 0; }

    .stSpinner > div { border-top-color: #00E5D4 !important; }
</style>
""", unsafe_allow_html=True)

# ── Clientes API ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_clients():
    tavily = TavilyClient(api_key=get_secret("TAVILY_API_KEY"))
    claude = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return tavily, claude

tavily_client, claude_client = get_clients()

# ── Dominios por tipo de búsqueda ─────────────────────────────────────────────
DOMINIOS = {
    "Legislación": [
        "boe.es", "sepe.es",
        "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ],
    "Jurisprudencia": [
        "poderjudicial.es", "boe.es",
        "abogacia.es", "iberley.es", "noticias.juridicas.com"
    ],
    "Consulta general": [
        "boe.es", "poderjudicial.es", "sepe.es",
        "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ]
}

SUFIJOS = {
    "Legislación":     "legislación ley España BOE",
    "Jurisprudencia":  "jurisprudencia sentencia tribunal España",
    "Consulta general": "derecho España jurídico legal"
}

# ── Prompt estricto anti-alucinación ─────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente jurídico especializado en derecho español y europeo.
Asistes a abogados profesionales con consultas de investigación legal.

REGLAS ABSOLUTAS — nunca puedes saltártelas:

1. SOLO puedes responder usando la información de los resultados de búsqueda proporcionados.
2. Si la información NO aparece en los resultados, responde EXACTAMENTE con esta frase:
   "No he encontrado información suficiente sobre este tema en las fuentes consultadas."
3. Cita SIEMPRE la fuente para cada dato relevante: nombre del documento, número de ley/sentencia y fecha si están disponibles.
4. NUNCA inventes sentencias, artículos, fechas, números de expediente, nombres de partes ni datos de ningún tipo.
5. Si una norma puede haber sido modificada o derogada posteriormente, adviértelo explícitamente.
6. Si los resultados son ambiguos o contradictorios entre fuentes, indícalo y presenta las dos versiones.
7. Usa lenguaje jurídico preciso. Estructura la respuesta con secciones claras cuando haya varios puntos.
8. Al final de cada respuesta añade siempre: "⚠️ Esta información es orientativa. Verifique la vigencia de las normas antes de aplicarlas."

Formato de respuesta:
- Respuesta directa y estructurada
- Referencias a fuentes entre corchetes: [Fuente 1], [Fuente 2]...
- Advertencia de vigencia al final"""

# ── Funciones de búsqueda ─────────────────────────────────────────────────────
def buscar_boe(query: str) -> dict | None:
    try:
        url = f"https://www.boe.es/buscar/act.php?id=BOE-A&p={requests.utils.quote(query)}&tipo=all"
        r = requests.get(
            f"https://www.boe.es/datosabiertos/api/boe/sumario/{datetime.now().strftime('%Y%m%d')}",
            timeout=8
        )
        if r.status_code == 200:
            return {"boe_hoy": r.json()}
    except Exception:
        pass
    return None

def buscar_tavily(query: str, tipo: str) -> dict:
    sufijo = SUFIJOS.get(tipo, "")
    dominios = DOMINIOS.get(tipo, DOMINIOS["Consulta general"])
    try:
        results = tavily_client.search(
            query=f"{query} {sufijo}",
            search_depth="advanced",
            max_results=6,
            include_domains=dominios
        )
        return results
    except Exception as e:
        return {"error": str(e), "results": []}

def construir_contexto(results: dict) -> str:
    items = results.get("results", [])
    if not items:
        return ""
    ctx = "RESULTADOS DE BÚSQUEDA EN FUENTES JURÍDICAS OFICIALES:\n\n"
    for i, r in enumerate(items, 1):
        ctx += f"[Fuente {i}] {r.get('title','Sin título')}\n"
        ctx += f"URL: {r.get('url','')}\n"
        ctx += f"Contenido: {r.get('content','')[:1200]}\n"
        ctx += "---\n"
    return ctx

def stream_respuesta(query: str, contexto: str):
    if not contexto.strip():
        yield "No he encontrado información suficiente sobre este tema en las fuentes consultadas."
        return

    with claude_client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{
            "role": "user",
            "content": f"Consulta del abogado: {query}\n\n{contexto}\n\nResponde ÚNICAMENTE basándote en los resultados anteriores."
        }]
    ) as stream:
        for text in stream.text_stream:
            yield text

# ── Interfaz ──────────────────────────────────────────────────────────────────
st.markdown("""
<div class="header-box">
    <h1>⚖️ Asistente Jurídico IA</h1>
    <p>Búsqueda en fuentes oficiales: BOE · Poder Judicial · EUR-Lex · Legislación española</p>
</div>
""", unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tipo = st.radio(
        "Tipo de búsqueda",
        ["Legislación", "Jurisprudencia", "Consulta general"],
        help="Legislación: BOE, Congreso, EU\nJurisprudencia: Poder Judicial, Tribunales\nGeneral: todas las fuentes"
    )

    badges = {"Legislación": "badge-leg", "Jurisprudencia": "badge-jur", "Consulta general": "badge-gen"}
    st.markdown(f'<span class="badge {badges[tipo]}">{tipo}</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Fuentes activas:**")
    for d in DOMINIOS[tipo]:
        st.markdown(f"• `{d}`")

    st.markdown("---")
    if st.button("🗑️ Limpiar conversación"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("""
<div style="font-size:0.75rem;color:#94a3b8;margin-top:1rem;">
    <b>CUVEAI</b> — Demo confidencial<br>
    Solo para uso interno
</div>
""", unsafe_allow_html=True)

# Inicializar historial
if "messages" not in st.session_state:
    st.session_state.messages = []

# Mostrar historial
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("sources"):
            with st.expander("📚 Fuentes consultadas"):
                for s in msg["sources"]:
                    st.markdown(f"""
<div class="source-card">
    <a href="{s['url']}" target="_blank">{s['title']}</a><br>
    <span class="source-domain">🔗 {s['url'][:80]}...</span>
</div>
""", unsafe_allow_html=True)

# Input
if prompt := st.chat_input("Escribe tu consulta jurídica..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # Paso 1 — Búsqueda
        status = st.status(f"Buscando en fuentes jurídicas...", expanded=True)
        with status:
            st.write(f"🔎 Consultando {tipo.lower()}: {', '.join(DOMINIOS[tipo][:3])}...")
            results = buscar_tavily(prompt, tipo)
            n = len(results.get("results", []))
            st.write(f"📄 {n} fuentes encontradas")

            # Paso 2 — Contexto
            st.write("🧠 Analizando contenido jurídico...")
            contexto = construir_contexto(results)

            # Paso 3 — Respuesta
            st.write("✍️ Redactando respuesta...")
        status.update(label=f"✅ Búsqueda completada — {n} fuentes", state="complete", expanded=False)

        # Streaming de la respuesta
        respuesta = st.write_stream(stream_respuesta(prompt, contexto))

        # Fuentes
        sources = results.get("results", [])
        if sources:
            with st.expander(f"📚 {len(sources)} fuentes consultadas"):
                for s in sources:
                    st.markdown(f"""
<div class="source-card">
    <a href="{s['url']}" target="_blank">{s['title']}</a><br>
    <span class="source-domain">🔗 {s['url'][:90]}</span>
</div>
""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="not-found-box">⚠️ No se encontraron fuentes jurídicas relevantes para esta consulta.</div>', unsafe_allow_html=True)

    st.session_state.messages.append({
        "role": "assistant",
        "content": respuesta,
        "sources": sources
    })
