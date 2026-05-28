import streamlit as st
import anthropic
from tavily import TavilyClient
import requests
import re
import os
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
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

    .api-badge {
        background: #dcfce7;
        color: #166534;
        font-size: 0.65rem;
        font-weight: 700;
        padding: 0.1rem 0.4rem;
        border-radius: 4px;
        margin-left: 0.3rem;
        vertical-align: middle;
    }
</style>
""", unsafe_allow_html=True)

# ── Clientes API ──────────────────────────────────────────────────────────────
@st.cache_resource
def get_clients():
    tavily = TavilyClient(api_key=get_secret("TAVILY_API_KEY"))
    claude = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return tavily, claude

tavily_client, claude_client = get_clients()

# ── Fuentes por tipo ──────────────────────────────────────────────────────────
DOMINIOS = {
    "Legislación": [
        "boe.es", "congreso.es", "senado.es", "mjusticia.gob.es",
        "eur-lex.europa.eu", "agenciatributaria.es", "seg-social.es",
        "sepe.es", "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ],
    "Jurisprudencia": [
        "poderjudicial.es", "mjusticia.gob.es", "boe.es",
        "abogacia.es", "iberley.es", "noticias.juridicas.com"
    ],
    "Consulta general": [
        "boe.es", "poderjudicial.es", "congreso.es", "eur-lex.europa.eu",
        "mjusticia.gob.es", "agenciatributaria.es", "seg-social.es",
        "sepe.es", "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ]
}

# Fuentes con integración API directa
FUENTES_API_DIRECTA = {"boe.es", "eur-lex.europa.eu"}

SUFIJOS = {
    "Legislación":     "legislación ley España BOE normativa",
    "Jurisprudencia":  "jurisprudencia sentencia tribunal España CENDOJ",
    "Consulta general": "derecho España jurídico legal normativa"
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

# ── Búsqueda Tavily (sin filtro de dominio para máxima cobertura) ─────────────
def buscar_tavily(query: str, tipo: str) -> list:
    sufijo = SUFIJOS.get(tipo, "")
    try:
        results = tavily_client.search(
            query=f"{query} {sufijo}",
            search_depth="advanced",
            max_results=7,
        )
        return results.get("results", [])
    except Exception:
        return []

# ── BOE — API datos abiertos + buscador oficial ───────────────────────────────
def buscar_boe_directo(query: str) -> list:
    results = []

    # 1. Buscador BOE (normativa vigente)
    try:
        r = requests.get(
            "https://www.boe.es/buscar/act.php",
            params={"p": query, "tipo": "all", "accion": "Buscar"},
            headers={"User-Agent": "Mozilla/5.0 (compatible; LegalAssistant/1.0)"},
            timeout=10
        )
        if r.status_code == 200:
            # Extraer enlaces de resultados de normativa
            for m in re.finditer(r'href="(/buscar/act/[^"]+)"', r.text):
                href = m.group(1)
                # Obtener texto circundante para extraer título
                start = max(0, m.end())
                snippet = r.text[start:start + 300]
                title_m = re.search(r'>\s*([^<]{15,200}?)\s*<', snippet)
                if title_m:
                    title = title_m.group(1).strip()
                    if len(title) > 15 and not title.startswith('http'):
                        results.append({
                            'title': f"BOE (normativa): {title}",
                            'url': f"https://www.boe.es{href}",
                            'content': f"Normativa en vigor publicada en el BOE: {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass

    # 2. API datos abiertos — sumario de hoy
    try:
        today = datetime.now().strftime('%Y%m%d')
        r2 = requests.get(
            f"https://www.boe.es/datosabiertos/api/boe/sumario/{today}",
            headers={"Accept": "application/json", "User-Agent": "Mozilla/5.0"},
            timeout=8
        )
        if r2.status_code == 200:
            data = r2.json()
            keywords = [w.lower() for w in query.split() if len(w) > 3]

            def scan(obj, depth=0):
                if depth > 10 or len(results) >= 5:
                    return
                if isinstance(obj, dict):
                    titulo = obj.get('titulo', '')
                    if titulo and any(kw in titulo.lower() for kw in keywords):
                        url_doc = obj.get('urlHtml', '') or obj.get('urlPdf', '')
                        if isinstance(url_doc, dict):
                            url_doc = url_doc.get('#text', '') or url_doc.get('@attr', '')
                        results.append({
                            'title': f"BOE {today}: {titulo}",
                            'url': f"https://www.boe.es{url_doc}" if url_doc and url_doc.startswith('/') else "https://www.boe.es",
                            'content': f"Publicado en BOE el {today}: {titulo}."
                        })
                    for v in obj.values():
                        scan(v, depth + 1)
                elif isinstance(obj, list):
                    for item in obj:
                        scan(item, depth + 1)

            scan(data)
    except Exception:
        pass

    return results[:4]

# ── EUR-Lex — buscador oficial + SPARQL ──────────────────────────────────────
def buscar_eurlex_directo(query: str) -> list:
    results = []

    # 1. Buscador web EUR-Lex
    try:
        r = requests.get(
            "https://eur-lex.europa.eu/search.html",
            params={"type": "quick", "text": query, "lang": "es"},
            headers={"User-Agent": "Mozilla/5.0 (compatible)"},
            timeout=12
        )
        if r.status_code == 200:
            # Extraer enlaces a documentos de contenido legal
            seen = set()
            for m in re.finditer(
                r'href="(https://eur-lex\.europa\.eu/legal-content/[^"]+)"',
                r.text
            ):
                url = m.group(1).split('?')[0]  # quitar parámetros
                if url in seen:
                    continue
                seen.add(url)
                # Extraer título del contexto
                start = max(0, m.end())
                snippet = r.text[start:start + 400]
                title_m = re.search(r'title="([^"]{10,200})"', snippet) or \
                          re.search(r'>\s*([^<]{15,200}?)\s*</', snippet)
                if title_m:
                    title = re.sub(r'\s+', ' ', title_m.group(1)).strip()
                    if title and 'EUR-Lex' not in title:
                        results.append({
                            'title': f"EUR-Lex: {title}",
                            'url': url,
                            'content': f"Legislación europea (EUR-Lex): {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass

    # 2. SPARQL Publications Office (fallback si no hay resultados HTML)
    if not results:
        try:
            keywords = [w for w in query.split() if len(w) > 4][:2]
            if keywords:
                filter_str = " && ".join(
                    [f'CONTAINS(LCASE(STR(?title)), "{kw.lower()}")' for kw in keywords]
                )
                sparql = f"""
PREFIX cdm: <http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?work ?title ?date WHERE {{
  ?work cdm:work_title ?title ;
        cdm:work_date_document ?date .
  FILTER (LANG(?title) = 'es')
  FILTER ({filter_str})
  FILTER (xsd:integer(SUBSTR(STR(?date),1,4)) >= 2010)
}} ORDER BY DESC(?date) LIMIT 3
"""
                r2 = requests.post(
                    "https://publications.europa.eu/webapi/rdf/sparql",
                    data={"query": sparql, "format": "application/sparql-results+json"},
                    timeout=15
                )
                if r2.status_code == 200:
                    data = r2.json()
                    for b in data.get('results', {}).get('bindings', []):
                        title = b.get('title', {}).get('value', '')
                        work  = b.get('work',  {}).get('value', '')
                        date  = b.get('date',  {}).get('value', '')[:10]
                        if title and work:
                            results.append({
                                'title': f"EUR-Lex: {title} ({date})",
                                'url': work,
                                'content': f"Legislación europea: {title}. Fecha: {date}. Fuente: Publications Office / EUR-Lex."
                            })
        except Exception:
            pass

    return results[:3]

# ── Búsqueda multi-fuente en paralelo ─────────────────────────────────────────
def buscar_todas_fuentes(query: str, tipo: str) -> dict:
    futures_map = {}

    with ThreadPoolExecutor(max_workers=3) as ex:
        futures_map[ex.submit(buscar_tavily, query, tipo)] = "tavily"
        futures_map[ex.submit(buscar_boe_directo, query)] = "boe"
        if tipo in ("Legislación", "Consulta general"):
            futures_map[ex.submit(buscar_eurlex_directo, query)] = "eurlex"

        raw = []
        for future in as_completed(futures_map, timeout=18):
            try:
                raw.extend(future.result())
            except Exception:
                pass

    # Deduplicar por URL
    seen, merged = set(), []
    for item in raw:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(item)

    return {"results": merged[:12]}

# ── Contexto para Claude ──────────────────────────────────────────────────────
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

# ── Respuesta en streaming ────────────────────────────────────────────────────
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
    <p>Búsqueda en fuentes oficiales: BOE · EUR-Lex · Poder Judicial · Congreso · Legislación española</p>
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
        if d in FUENTES_API_DIRECTA:
            st.markdown(f'• `{d}` <span class="api-badge">API</span>', unsafe_allow_html=True)
        else:
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
        status = st.status("Buscando en fuentes jurídicas...", expanded=True)
        with status:
            st.write("🔎 Consultando BOE (API) · EUR-Lex (API) · Tavily · Poder Judicial...")
            results = buscar_todas_fuentes(prompt, tipo)
            n = len(results.get("results", []))

            # Contar por fuente
            boe_n = sum(1 for r in results["results"] if "boe.es" in r.get("url", ""))
            el_n  = sum(1 for r in results["results"] if "eur-lex" in r.get("url", ""))
            st.write(f"📄 {n} resultados — {boe_n} BOE · {el_n} EUR-Lex · {n-boe_n-el_n} otras fuentes")

            st.write("🧠 Analizando contenido jurídico...")
            contexto = construir_contexto(results)
            st.write("✍️ Redactando respuesta...")
        status.update(label=f"✅ {n} fuentes consultadas (BOE + EUR-Lex + web)", state="complete", expanded=False)

        respuesta = st.write_stream(stream_respuesta(prompt, contexto))

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
