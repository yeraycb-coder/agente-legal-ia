import streamlit as st
import anthropic
from tavily import TavilyClient
import requests
import re
import json
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
        margin-left: 0.4rem;
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

# ── Fuentes por tipo de búsqueda ─────────────────────────────────────────────
DOMINIOS = {
    "Legislación": [
        "boe.es", "eur-lex.europa.eu", "congreso.es", "senado.es",
        "mjusticia.gob.es", "agenciatributaria.es", "seg-social.es",
        "sepe.es", "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ],
    "Jurisprudencia": [
        "poderjudicial.es", "tribunalconstitucional.es", "hudoc.echr.coe.int",
        "boe.es", "eur-lex.europa.eu", "mjusticia.gob.es",
        "abogacia.es", "iberley.es", "noticias.juridicas.com"
    ],
    "Consulta general": [
        "boe.es", "poderjudicial.es", "tribunalconstitucional.es",
        "hudoc.echr.coe.int", "eur-lex.europa.eu", "congreso.es",
        "mjusticia.gob.es", "agenciatributaria.es", "seg-social.es",
        "sepe.es", "noticias.juridicas.com", "iberley.es", "abogacia.es"
    ]
}

# Fuentes con integración API directa
FUENTES_API_DIRECTA = {
    "boe.es", "eur-lex.europa.eu",
    "poderjudicial.es", "tribunalconstitucional.es", "hudoc.echr.coe.int"
}

SUFIJOS = {
    "Legislación":      "legislación ley España BOE normativa",
    "Jurisprudencia":   "jurisprudencia sentencia tribunal España",
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

# ── Headers comunes ───────────────────────────────────────────────────────────
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; LegalAssistant/2.0)"}

# ── 1. Tavily — búsqueda amplia sin filtro de dominio ─────────────────────────
def buscar_tavily(query: str, tipo: str) -> list:
    sufijo = SUFIJOS.get(tipo, "")
    try:
        res = tavily_client.search(
            query=f"{query} {sufijo}",
            search_depth="advanced",
            max_results=6,
        )
        return res.get("results", [])
    except Exception:
        return []

# ── 2. BOE — API datos abiertos + buscador oficial ───────────────────────────
def buscar_boe_directo(query: str) -> list:
    results = []

    # Buscador de normativa vigente
    try:
        r = requests.get(
            "https://www.boe.es/buscar/act.php",
            params={"p": query, "tipo": "all", "accion": "Buscar"},
            headers=HEADERS,
            timeout=10
        )
        if r.status_code == 200:
            for m in re.finditer(r'href="(/buscar/act/[^"]+)"', r.text):
                href = m.group(1)
                snippet = r.text[m.end():m.end() + 300]
                t = re.search(r'>\s*([^<]{15,200}?)\s*<', snippet)
                if t:
                    title = t.group(1).strip()
                    if len(title) > 15:
                        results.append({
                            'title': f"BOE: {title}",
                            'url': f"https://www.boe.es{href}",
                            'content': f"Normativa BOE: {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass

    # API datos abiertos — sumario de hoy
    try:
        today = datetime.now().strftime('%Y%m%d')
        r2 = requests.get(
            f"https://www.boe.es/datosabiertos/api/boe/sumario/{today}",
            headers={**HEADERS, "Accept": "application/json"},
            timeout=8
        )
        if r2.status_code == 200:
            data = r2.json()
            kws = [w.lower() for w in query.split() if len(w) > 3]

            def scan(obj, depth=0):
                if depth > 10 or len(results) >= 5:
                    return
                if isinstance(obj, dict):
                    titulo = obj.get('titulo', '')
                    if titulo and any(k in titulo.lower() for k in kws):
                        url_doc = obj.get('urlHtml', '') or obj.get('urlPdf', '')
                        if isinstance(url_doc, dict):
                            url_doc = url_doc.get('#text', '') or url_doc.get('@attr', '')
                        results.append({
                            'title': f"BOE {today}: {titulo}",
                            'url': f"https://www.boe.es{url_doc}" if url_doc and str(url_doc).startswith('/') else "https://www.boe.es",
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

# ── 3. EUR-Lex — buscador oficial + SPARQL ───────────────────────────────────
def buscar_eurlex_directo(query: str) -> list:
    results = []

    # Buscador web EUR-Lex
    try:
        r = requests.get(
            "https://eur-lex.europa.eu/search.html",
            params={"type": "quick", "text": query, "lang": "es"},
            headers=HEADERS,
            timeout=12
        )
        if r.status_code == 200:
            seen = set()
            for m in re.finditer(
                r'href="(https://eur-lex\.europa\.eu/legal-content/[^"]+)"',
                r.text
            ):
                url = m.group(1).split('?')[0]
                if url in seen:
                    continue
                seen.add(url)
                snippet = r.text[m.end():m.end() + 400]
                t = re.search(r'title="([^"]{10,200})"', snippet) or \
                    re.search(r'>\s*([^<]{15,200}?)\s*</', snippet)
                if t:
                    title = re.sub(r'\s+', ' ', t.group(1)).strip()
                    if title:
                        results.append({
                            'title': f"EUR-Lex: {title}",
                            'url': url,
                            'content': f"Legislación europea (EUR-Lex): {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass

    # SPARQL fallback
    if not results:
        try:
            kws = [w for w in query.split() if len(w) > 4][:2]
            if kws:
                filter_str = " && ".join(
                    [f'CONTAINS(LCASE(STR(?title)), "{k.lower()}")' for k in kws]
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
                    for b in r2.json().get('results', {}).get('bindings', []):
                        title = b.get('title', {}).get('value', '')
                        work  = b.get('work',  {}).get('value', '')
                        date  = b.get('date',  {}).get('value', '')[:10]
                        if title and work:
                            results.append({
                                'title': f"EUR-Lex: {title} ({date})",
                                'url': work,
                                'content': f"Legislación europea: {title}. Fecha: {date}."
                            })
        except Exception:
            pass

    return results[:3]

# ── 4. CENDOJ — Centro de Documentación Judicial ─────────────────────────────
def buscar_cendoj(query: str) -> list:
    results = []
    try:
        r = requests.get(
            "https://www.poderjudicial.es/search/indexAN.jsp",
            params={"texto": query, "secc": "1"},
            headers=HEADERS,
            timeout=12
        )
        if r.status_code == 200:
            for m in re.finditer(r'href="(/search/AN/openCDocument\.do\?[^"]+)"', r.text):
                href = m.group(1)
                snippet = r.text[m.end():m.end() + 400]
                t = re.search(r'>\s*([^<]{10,200}?)\s*<', snippet)
                if t:
                    title = re.sub(r'\s+', ' ', t.group(1)).strip()
                    if len(title) > 10:
                        results.append({
                            'title': f"CENDOJ: {title}",
                            'url': f"https://www.poderjudicial.es{href}",
                            'content': f"Jurisprudencia CENDOJ (Poder Judicial): {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass
    return results

# ── 5. Tribunal Constitucional ────────────────────────────────────────────────
def buscar_tc(query: str) -> list:
    results = []
    try:
        r = requests.get(
            "https://hj.tribunalconstitucional.es/es/Resolucion/Buscar",
            params={"texto": query},
            headers=HEADERS,
            timeout=12
        )
        if r.status_code == 200:
            for m in re.finditer(r'href="(/es/Resolucion/Show/(\d+))"', r.text):
                href = m.group(1)
                snippet = r.text[m.end():m.end() + 400]
                t = re.search(r'>\s*([^<]{10,200}?)\s*</[^>]+>', snippet)
                if t:
                    title = re.sub(r'\s+', ' ', t.group(1)).strip()
                    if len(title) > 5:
                        results.append({
                            'title': f"TC: {title}",
                            'url': f"https://hj.tribunalconstitucional.es{href}",
                            'content': f"Resolución del Tribunal Constitucional: {title}."
                        })
                        if len(results) >= 3:
                            break
    except Exception:
        pass
    return results

# ── 6. HUDOC — Tribunal Europeo de Derechos Humanos ──────────────────────────
def buscar_hudoc(query: str) -> list:
    results = []
    try:
        params = {
            "query": json.dumps({
                "fulltext": [query],
                "documentcollectionid2": ["GRANDCHAMBER", "CHAMBER", "JUDGMENTS"]
            }),
            "select": json.dumps({
                "itemid": 1,
                "docname": 1,
                "conclusion": 1,
                "importance": 1,
                "kpdate": 1,
                "respondent": 1
            }),
            "sort": json.dumps({"kpdate": "Descending"}),
            "start": 0,
            "length": 4
        }
        r = requests.get(
            "https://hudoc.echr.coe.int/app/query/results",
            params=params,
            headers={**HEADERS, "Accept": "application/json"},
            timeout=15
        )
        if r.status_code == 200:
            data = r.json()
            # Navegar estructura de respuesta HUDOC
            hits = data
            for key in ['results', 'hits', 'hits']:
                if isinstance(hits, dict):
                    hits = hits.get(key, hits)
            if not isinstance(hits, list):
                hits = []

            for hit in hits[:4]:
                src = hit.get('_source', hit)
                docname = src.get('docname', '')
                itemid  = src.get('itemid', '')
                conc    = src.get('conclusion', '')
                if isinstance(conc, list):
                    conc = '; '.join(str(c) for c in conc[:2])
                date = str(src.get('kpdate', ''))[:10]
                resp = src.get('respondent', '')
                if isinstance(resp, list):
                    resp = ', '.join(resp)

                if docname and itemid:
                    results.append({
                        'title': f"TEDH: {docname} ({date})",
                        'url': f"https://hudoc.echr.coe.int/eng?i={itemid}",
                        'content': f"Sentencia TEDH contra {resp} ({date}): {str(conc)[:400]}"
                    })
    except Exception:
        pass
    return results

# ── Búsqueda multi-fuente en paralelo ─────────────────────────────────────────
def buscar_todas_fuentes(query: str, tipo: str) -> dict:
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(buscar_tavily,        query, tipo): "tavily",
            ex.submit(buscar_boe_directo,   query):       "boe",
        }
        if tipo in ("Legislación", "Consulta general"):
            futures[ex.submit(buscar_eurlex_directo, query)] = "eurlex"
        if tipo in ("Jurisprudencia", "Consulta general"):
            futures[ex.submit(buscar_cendoj, query)] = "cendoj"
            futures[ex.submit(buscar_tc,     query)] = "tc"
            futures[ex.submit(buscar_hudoc,  query)] = "hudoc"

        raw = []
        for future in as_completed(futures, timeout=20):
            try:
                raw.extend(future.result())
            except Exception:
                pass

    seen, merged = set(), []
    for item in raw:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(item)

    return {"results": merged[:14]}

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

# ── Streaming ─────────────────────────────────────────────────────────────────
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
    <p>BOE · EUR-Lex · CENDOJ · Tribunal Constitucional · TEDH (HUDOC) · Legislación española</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tipo = st.radio(
        "Tipo de búsqueda",
        ["Legislación", "Jurisprudencia", "Consulta general"],
        help="Legislación: BOE, EUR-Lex, Congreso…\nJurisprudencia: CENDOJ, TC, TEDH…\nGeneral: todas las fuentes"
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

if "messages" not in st.session_state:
    st.session_state.messages = []

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

if prompt := st.chat_input("Escribe tu consulta jurídica..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status = st.status("Buscando en fuentes jurídicas...", expanded=True)
        with status:
            fuentes_activas = []
            fuentes_activas.append("BOE (API)")
            if tipo in ("Legislación", "Consulta general"):
                fuentes_activas.append("EUR-Lex (API)")
            if tipo in ("Jurisprudencia", "Consulta general"):
                fuentes_activas += ["CENDOJ (API)", "TC (API)", "HUDOC/TEDH (API)"]
            fuentes_activas.append("Tavily")
            st.write(f"🔎 Consultando: {' · '.join(fuentes_activas)}")

            results  = buscar_todas_fuentes(prompt, tipo)
            n        = len(results.get("results", []))
            boe_n    = sum(1 for r in results["results"] if "boe.es"                    in r.get("url", ""))
            el_n     = sum(1 for r in results["results"] if "eur-lex"                   in r.get("url", ""))
            cendoj_n = sum(1 for r in results["results"] if "poderjudicial.es"          in r.get("url", ""))
            tc_n     = sum(1 for r in results["results"] if "tribunalconstitucional.es" in r.get("url", ""))
            hudoc_n  = sum(1 for r in results["results"] if "hudoc.echr.coe.int"        in r.get("url", ""))

            resumen = f"📄 {n} resultados — BOE:{boe_n} · EUR-Lex:{el_n} · CENDOJ:{cendoj_n} · TC:{tc_n} · TEDH:{hudoc_n} · otras:{n-boe_n-el_n-cendoj_n-tc_n-hudoc_n}"
            st.write(resumen)
            st.write("🧠 Analizando contenido jurídico...")
            contexto = construir_contexto(results)
            st.write("✍️ Redactando respuesta...")
        status.update(
            label=f"✅ {n} fuentes — BOE · EUR-Lex · CENDOJ · TC · TEDH",
            state="complete", expanded=False
        )

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
