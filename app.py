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

st.set_page_config(
    page_title="Asistente Jurídico IA",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded"
)

st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');
    html, body, [class*="css"] { font-family: 'Inter', sans-serif; }

    .header-box {
        background: linear-gradient(135deg, #0A1628 0%, #1a2f52 100%);
        color: white; padding: 2rem 2.5rem; border-radius: 16px; margin-bottom: 1.5rem;
    }
    .header-box h1 { font-size: 1.8rem; font-weight: 700; margin: 0; }
    .header-box p  { color: #00E5D4; font-size: 0.9rem; margin: 0.3rem 0 0; }

    .source-card {
        background: #f8fafc; border: 1px solid #e2e8f0;
        border-left: 4px solid #00E5D4; border-radius: 8px;
        padding: 0.7rem 1rem; margin-bottom: 0.5rem; font-size: 0.85rem;
    }
    .source-card a { color: #0A1628; font-weight: 600; text-decoration: none; }
    .source-card a:hover { text-decoration: underline; }
    .source-domain { color: #64748b; font-size: 0.75rem; }

    .not-found-box {
        background: #fff7ed; border: 1px solid #fed7aa;
        border-radius: 10px; padding: 1rem 1.2rem; color: #9a3412; font-size: 0.9rem;
    }

    .badge { display:inline-block; padding:0.2rem 0.7rem; border-radius:999px; font-size:0.75rem; font-weight:600; margin-right:0.3rem; }
    .badge-leg { background:#dbeafe; color:#1d4ed8; }
    .badge-jur { background:#d1fae5; color:#065f46; }
    .badge-gen { background:#ede9fe; color:#5b21b6; }

    .api-badge {
        background:#dcfce7; color:#166534; font-size:0.6rem; font-weight:700;
        padding:0.1rem 0.35rem; border-radius:4px; margin-left:0.3rem; vertical-align:middle;
    }
    .src-cat { font-size:0.7rem; font-weight:700; color:#94a3b8; text-transform:uppercase; letter-spacing:0.05em; margin:0.6rem 0 0.2rem; }

    [data-testid="stChatMessage"] { padding: 0.8rem 0; }
    .stSpinner > div { border-top-color: #00E5D4 !important; }
</style>
""", unsafe_allow_html=True)

@st.cache_resource
def get_clients():
    tavily = TavilyClient(api_key=get_secret("TAVILY_API_KEY"))
    claude = anthropic.Anthropic(api_key=get_secret("ANTHROPIC_API_KEY"))
    return tavily, claude

tavily_client, claude_client = get_clients()

# ── Fuentes organizadas por categoría ────────────────────────────────────────
FUENTES_CATS = {
    "Legislación española": [
        ("boe.es",               True),
        ("congreso.es",          True),
        ("senado.es",            False),
        ("mjusticia.gob.es",     False),
        ("noticias.juridicas.com", False),
        ("iberley.es",           False),
    ],
    "Fiscalidad y laboral": [
        ("agenciatributaria.es", True),
        ("seg-social.es",        False),
        ("sepe.es",              False),
        ("fiscal.es",            False),
    ],
    "Jurisprudencia española": [
        ("poderjudicial.es",              True),
        ("tribunalconstitucional.es",     True),
        ("abogacia.es",                   False),
    ],
    "Organismos y supervisores": [
        ("aepd.es",              True),
        ("cnmc.es",              True),
        ("consejo-estado.es",    True),
        ("tcu.es",               True),
        ("cnmv.es",              False),
        ("bde.es",               False),
    ],
    "Derecho europeo e internacional": [
        ("eur-lex.europa.eu",    True),
        ("curia.europa.eu",      True),
        ("hudoc.echr.coe.int",   True),
        ("edpb.europa.eu",       False),
    ],
}

# Fuentes que activamos por tipo de búsqueda (para el sidebar)
DOMINIOS_TIPO = {
    "Legislación": [
        "boe.es", "congreso.es", "senado.es", "mjusticia.gob.es",
        "noticias.juridicas.com", "iberley.es", "agenciatributaria.es",
        "seg-social.es", "sepe.es", "consejo-estado.es",
        "eur-lex.europa.eu", "curia.europa.eu",
    ],
    "Jurisprudencia": [
        "poderjudicial.es", "tribunalconstitucional.es", "hudoc.echr.coe.int",
        "curia.europa.eu", "eur-lex.europa.eu", "boe.es",
        "aepd.es", "cnmc.es", "tcu.es",
        "abogacia.es", "iberley.es", "noticias.juridicas.com",
    ],
    "Consulta general": [
        "boe.es", "poderjudicial.es", "tribunalconstitucional.es",
        "hudoc.echr.coe.int", "eur-lex.europa.eu", "curia.europa.eu",
        "congreso.es", "senado.es", "mjusticia.gob.es",
        "agenciatributaria.es", "seg-social.es", "sepe.es", "fiscal.es",
        "aepd.es", "cnmc.es", "consejo-estado.es", "tcu.es",
        "noticias.juridicas.com", "iberley.es", "abogacia.es",
    ],
}

# Set de fuentes con integración directa (API o scraping dedicado)
FUENTES_DIRECTAS = {
    "boe.es", "eur-lex.europa.eu", "poderjudicial.es",
    "tribunalconstitucional.es", "hudoc.echr.coe.int",
    "curia.europa.eu", "aepd.es", "cnmc.es",
    "consejo-estado.es", "tcu.es", "congreso.es",
    "agenciatributaria.es",
}

SUFIJOS = {
    "Legislación":      "legislación ley España BOE normativa",
    "Jurisprudencia":   "jurisprudencia sentencia tribunal España",
    "Consulta general": "derecho España jurídico legal",
}

SYSTEM_PROMPT = """Eres un asistente jurídico especializado en derecho español y europeo.
Asistes a abogados profesionales con consultas de investigación legal.

REGLAS ABSOLUTAS:
1. SOLO puedes responder usando la información de los resultados de búsqueda proporcionados.
2. Si la información NO aparece en los resultados, responde EXACTAMENTE:
   "No he encontrado información suficiente sobre este tema en las fuentes consultadas."
3. Cita SIEMPRE la fuente: nombre del documento, número de ley/sentencia y fecha si disponibles.
4. NUNCA inventes sentencias, artículos, fechas, números de expediente ni datos de ningún tipo.
5. Si una norma puede haber sido modificada o derogada, adviértelo explícitamente.
6. Si los resultados son contradictorios entre fuentes, indícalo y presenta ambas versiones.
7. Usa lenguaje jurídico preciso. Estructura con secciones claras cuando hay varios puntos.
8. Al final añade siempre: "⚠️ Esta información es orientativa. Verifique la vigencia antes de aplicarlas."

Formato: respuesta directa → [Fuente N] para citas → advertencia de vigencia al final."""

H = {"User-Agent": "Mozilla/5.0 (compatible; LegalAssistant/3.0)"}

# ═══════════════════════════════════════════════════════════════════════════════
# FUNCIONES DE BÚSQUEDA
# ═══════════════════════════════════════════════════════════════════════════════

def _extract(text, pattern, base_url="", prefix="", content_tmpl=""):
    """Helper: extrae (url, title) de HTML con regex y construye resultado."""
    results = []
    seen = set()
    for m in re.finditer(pattern, text, re.DOTALL):
        href = m.group(1)
        url = href if href.startswith("http") else f"{base_url}{href}"
        if url in seen:
            continue
        seen.add(url)
        snippet = text[m.end():m.end() + 400]
        t = re.search(r'(?:title|alt)="([^"]{10,200})"', snippet) or \
            re.search(r'>\s*([^<]{10,200}?)\s*<', snippet)
        if t:
            title = re.sub(r'\s+', ' ', t.group(1)).strip()
            if len(title) >= 10:
                results.append({
                    'title': f"{prefix}{title}",
                    'url': url,
                    'content': content_tmpl.format(title=title)
                })
                if len(results) >= 3:
                    break
    return results


# ── 1. Tavily — búsqueda amplia ───────────────────────────────────────────────
def buscar_tavily(query: str, tipo: str) -> list:
    try:
        res = tavily_client.search(
            query=f"{query} {SUFIJOS.get(tipo,'')}",
            search_depth="advanced",
            max_results=7,
        )
        return res.get("results", [])
    except Exception:
        return []


# ── 2. BOE ────────────────────────────────────────────────────────────────────
def buscar_boe(query: str) -> list:
    results = []
    # Buscador normativa vigente
    try:
        r = requests.get("https://www.boe.es/buscar/act.php",
                         params={"p": query, "tipo": "all"}, headers=H, timeout=10)
        if r.status_code == 200:
            results += _extract(r.text,
                r'href="(/buscar/act/[^"]+)"',
                "https://www.boe.es", "BOE: ",
                "Normativa BOE: {title}.")
    except Exception:
        pass
    # Sumario de hoy
    try:
        today = datetime.now().strftime('%Y%m%d')
        r2 = requests.get(f"https://www.boe.es/datosabiertos/api/boe/sumario/{today}",
                          headers={**H, "Accept": "application/json"}, timeout=8)
        if r2.status_code == 200:
            kws = [w.lower() for w in query.split() if len(w) > 3]
            def scan(obj, d=0):
                if d > 10 or len(results) >= 5: return
                if isinstance(obj, dict):
                    tit = obj.get('titulo', '')
                    if tit and any(k in tit.lower() for k in kws):
                        ud = obj.get('urlHtml', '') or obj.get('urlPdf', '')
                        if isinstance(ud, dict): ud = ud.get('#text', '') or ud.get('@attr', '')
                        results.append({'title': f"BOE {today}: {tit}",
                            'url': f"https://www.boe.es{ud}" if str(ud).startswith('/') else "https://www.boe.es",
                            'content': f"Publicado en BOE el {today}: {tit}."})
                    for v in obj.values(): scan(v, d+1)
                elif isinstance(obj, list):
                    for i in obj: scan(i, d+1)
            scan(r2.json())
    except Exception:
        pass
    return results[:4]


# ── 3. Congreso de los Diputados ──────────────────────────────────────────────
def buscar_congreso(query: str) -> list:
    try:
        r = requests.get("https://www.congreso.es/busqueda-de-leyes",
                         params={"_leyes_WAR_leyesportlet_texto": query},
                         headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(https?://www\.congreso\.es[^"]*ley[^"]*)"',
            "", "Congreso: ", "Ley aprobada en Congreso: {title}.")
    except Exception:
        return []


# ── 4. EUR-Lex ────────────────────────────────────────────────────────────────
def buscar_eurlex(query: str) -> list:
    results = []
    try:
        r = requests.get("https://eur-lex.europa.eu/search.html",
                         params={"type": "quick", "text": query, "lang": "es"},
                         headers=H, timeout=12)
        if r.status_code == 200:
            results += _extract(r.text,
                r'href="(https://eur-lex\.europa\.eu/legal-content/[^"]+)"',
                "", "EUR-Lex: ", "Legislación europea: {title}.")
    except Exception:
        pass
    # SPARQL fallback
    if not results:
        try:
            kws = [w for w in query.split() if len(w) > 4][:2]
            if kws:
                f = " && ".join([f'CONTAINS(LCASE(STR(?t)),"{k.lower()}")' for k in kws])
                sparql = f"""PREFIX cdm:<http://publications.europa.eu/ontology/cdm#>
SELECT DISTINCT ?w ?t ?d WHERE{{?w cdm:work_title ?t;cdm:work_date_document ?d.
FILTER(LANG(?t)='es')FILTER({f})FILTER(xsd:integer(SUBSTR(STR(?d),1,4))>=2010)
}}ORDER BY DESC(?d) LIMIT 3"""
                r2 = requests.post("https://publications.europa.eu/webapi/rdf/sparql",
                    data={"query": sparql, "format": "application/sparql-results+json"}, timeout=15)
                if r2.status_code == 200:
                    for b in r2.json().get('results',{}).get('bindings',[]):
                        t = b.get('t',{}).get('value','')
                        w = b.get('w',{}).get('value','')
                        d = b.get('d',{}).get('value','')[:10]
                        if t and w:
                            results.append({'title': f"EUR-Lex: {t} ({d})", 'url': w,
                                            'content': f"Legislación europea: {t}. Fecha: {d}."})
        except Exception:
            pass
    return results[:3]


# ── 5. CURIA — Tribunal de Justicia UE ───────────────────────────────────────
def buscar_curia(query: str) -> list:
    try:
        r = requests.get("https://curia.europa.eu/juris/documents.jsf",
                         params={"critere": query, "occ": "first", "part": "1",
                                 "mode": "liste", "language": "es"},
                         headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(https://curia\.europa\.eu/juris/document/document\.jsf\?[^"]+)"',
            "", "CURIA: ", "Sentencia TJUE: {title}.")
    except Exception:
        return []


# ── 6. CENDOJ — Poder Judicial ────────────────────────────────────────────────
def buscar_cendoj(query: str) -> list:
    try:
        r = requests.get("https://www.poderjudicial.es/search/indexAN.jsp",
                         params={"texto": query, "secc": "1"},
                         headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(/search/AN/openCDocument\.do\?[^"]+)"',
            "https://www.poderjudicial.es", "CENDOJ: ",
            "Jurisprudencia CENDOJ: {title}.")
    except Exception:
        return []


# ── 7. Tribunal Constitucional ────────────────────────────────────────────────
def buscar_tc(query: str) -> list:
    try:
        r = requests.get("https://hj.tribunalconstitucional.es/es/Resolucion/Buscar",
                         params={"texto": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(/es/Resolucion/Show/\d+)"',
            "https://hj.tribunalconstitucional.es", "TC: ",
            "Resolución Tribunal Constitucional: {title}.")
    except Exception:
        return []


# ── 8. HUDOC — TEDH ───────────────────────────────────────────────────────────
def buscar_hudoc(query: str) -> list:
    try:
        params = {
            "query": json.dumps({"fulltext": [query],
                "documentcollectionid2": ["GRANDCHAMBER","CHAMBER","JUDGMENTS"]}),
            "select": json.dumps({"itemid":1,"docname":1,"conclusion":1,
                                  "kpdate":1,"respondent":1}),
            "sort": json.dumps({"kpdate":"Descending"}),
            "start": 0, "length": 4
        }
        r = requests.get("https://hudoc.echr.coe.int/app/query/results",
                         params=params, headers={**H, "Accept":"application/json"}, timeout=15)
        if r.status_code != 200: return []
        data = r.json()
        hits = data
        for k in ['results','hits','hits']:
            if isinstance(hits, dict): hits = hits.get(k, hits)
        if not isinstance(hits, list): return []
        results = []
        for hit in hits[:4]:
            src = hit.get('_source', hit)
            name = src.get('docname','')
            iid  = src.get('itemid','')
            conc = src.get('conclusion','')
            if isinstance(conc, list): conc = '; '.join(str(c) for c in conc[:2])
            date = str(src.get('kpdate',''))[:10]
            resp = src.get('respondent','')
            if isinstance(resp, list): resp = ', '.join(resp)
            if name and iid:
                results.append({'title': f"TEDH: {name} ({date})",
                    'url': f"https://hudoc.echr.coe.int/eng?i={iid}",
                    'content': f"TEDH contra {resp} ({date}): {str(conc)[:400]}"})
        return results
    except Exception:
        return []


# ── 9. AEPD — Agencia Española de Protección de Datos ────────────────────────
def buscar_aepd(query: str) -> list:
    try:
        r = requests.get("https://www.aepd.es/es/buscador",
                         params={"palabras-clave": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(/es/(?:resoluciones|guias-y-herramientas|informes|documento)[^"]+)"',
            "https://www.aepd.es", "AEPD: ",
            "Resolución/Guía AEPD (protección de datos): {title}.")
    except Exception:
        return []


# ── 10. CNMC — Comisión Nacional de Mercados y Competencia ───────────────────
def buscar_cnmc(query: str) -> list:
    try:
        r = requests.get("https://www.cnmc.es/buscar",
                         params={"busqueda": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(https://www\.cnmc\.es/[^"]+(?:expediente|resolucion|acuerdo|nota)[^"]*)"',
            "", "CNMC: ", "Resolución CNMC (competencia/mercados): {title}.")
    except Exception:
        return []


# ── 11. Consejo de Estado ─────────────────────────────────────────────────────
def buscar_consejo_estado(query: str) -> list:
    try:
        r = requests.get(
            "https://www.consejo-estado.es/es/doctrina-legal/buscador-de-dictamenes",
            params={"busqueda": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="([^"]*(?:dictamen|consulta)[^"]*)"',
            "https://www.consejo-estado.es", "Consejo de Estado: ",
            "Dictamen del Consejo de Estado: {title}.")
    except Exception:
        return []


# ── 12. Tribunal de Cuentas ───────────────────────────────────────────────────
def buscar_tribunal_cuentas(query: str) -> list:
    try:
        r = requests.get("https://www.tcu.es/tribunal-de-cuentas/es/buscador/",
                         params={"q": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(https://www\.tcu\.es[^"]+(?:informe|resolucion|auto|sentencia)[^"]*)"',
            "", "TCu: ", "Resolución Tribunal de Cuentas: {title}.")
    except Exception:
        return []


# ── 13. Agencia Tributaria ────────────────────────────────────────────────────
def buscar_aeat(query: str) -> list:
    try:
        r = requests.get(
            "https://www.agenciatributaria.es/AEAT.internet/Inicio/search/Buscador_de_publicaciones.shtml",
            params={"q": query}, headers=H, timeout=12)
        if r.status_code != 200: return []
        return _extract(r.text,
            r'href="(https?://[^"]*agenciatributaria[^"]+)"',
            "", "AEAT: ", "Publicación Agencia Tributaria: {title}.")
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════════════════════════
# BÚSQUEDA MULTI-FUENTE EN PARALELO
# ═══════════════════════════════════════════════════════════════════════════════

FUENTES_LABEL = {
    "tavily":          ("Tavily",          ""),
    "boe":             ("BOE",             "boe.es"),
    "congreso":        ("Congreso",        "congreso.es"),
    "eurlex":          ("EUR-Lex",         "eur-lex.europa.eu"),
    "curia":           ("CURIA",           "curia.europa.eu"),
    "cendoj":          ("CENDOJ",          "poderjudicial.es"),
    "tc":              ("TC",              "tribunalconstitucional.es"),
    "hudoc":           ("TEDH",            "hudoc.echr.coe.int"),
    "aepd":            ("AEPD",            "aepd.es"),
    "cnmc":            ("CNMC",            "cnmc.es"),
    "consejo_estado":  ("Consejo Estado",  "consejo-estado.es"),
    "tcu":             ("Trib. Cuentas",   "tcu.es"),
    "aeat":            ("AEAT",            "agenciatributaria.es"),
}

def buscar_todas_fuentes(query: str, tipo: str) -> dict:
    jobs = {
        "tavily": (buscar_tavily, [query, tipo]),
        "boe":    (buscar_boe,    [query]),
        "aepd":   (buscar_aepd,   [query]),
    }
    if tipo in ("Legislación", "Consulta general"):
        jobs.update({
            "eurlex":         (buscar_eurlex,          [query]),
            "curia":          (buscar_curia,           [query]),
            "congreso":       (buscar_congreso,        [query]),
            "consejo_estado": (buscar_consejo_estado,  [query]),
            "aeat":           (buscar_aeat,            [query]),
        })
    if tipo in ("Jurisprudencia", "Consulta general"):
        jobs.update({
            "cendoj": (buscar_cendoj,           [query]),
            "tc":     (buscar_tc,               [query]),
            "hudoc":  (buscar_hudoc,            [query]),
            "cnmc":   (buscar_cnmc,             [query]),
            "tcu":    (buscar_tribunal_cuentas, [query]),
        })

    with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
        futures = {ex.submit(fn, *args): key for key, (fn, args) in jobs.items()}
        raw, hit_sources = [], {}
        for future in as_completed(futures, timeout=22):
            key = futures[future]
            try:
                items = future.result()
                raw.extend(items)
                if items:
                    hit_sources[key] = len(items)
            except Exception:
                pass

    seen, merged = set(), []
    for item in raw:
        url = item.get("url", "")
        if url and url not in seen:
            seen.add(url)
            merged.append(item)

    return {"results": merged[:16], "hit_sources": hit_sources}


# ── Contexto para Claude ──────────────────────────────────────────────────────
def construir_contexto(results: dict) -> str:
    items = results.get("results", [])
    if not items:
        return ""
    ctx = "RESULTADOS DE BÚSQUEDA EN FUENTES JURÍDICAS OFICIALES:\n\n"
    for i, r in enumerate(items, 1):
        ctx += f"[Fuente {i}] {r.get('title','Sin título')}\n"
        ctx += f"URL: {r.get('url','')}\n"
        ctx += f"Contenido: {r.get('content','')[:1200]}\n---\n"
    return ctx


def stream_respuesta(query: str, contexto: str):
    if not contexto.strip():
        yield "No he encontrado información suficiente sobre este tema en las fuentes consultadas."
        return
    with claude_client.messages.stream(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        system=SYSTEM_PROMPT,
        messages=[{"role":"user","content":
            f"Consulta del abogado: {query}\n\n{contexto}\n\nResponde ÚNICAMENTE basándote en los resultados anteriores."}]
    ) as stream:
        for text in stream.text_stream:
            yield text


# ═══════════════════════════════════════════════════════════════════════════════
# INTERFAZ
# ═══════════════════════════════════════════════════════════════════════════════

st.markdown("""
<div class="header-box">
    <h1>⚖️ Asistente Jurídico IA</h1>
    <p>BOE · EUR-Lex · CURIA · CENDOJ · TC · TEDH · AEPD · CNMC · Congreso · y más</p>
</div>
""", unsafe_allow_html=True)

with st.sidebar:
    st.markdown("### ⚙️ Configuración")
    tipo = st.radio("Tipo de búsqueda",
                    ["Legislación", "Jurisprudencia", "Consulta general"],
                    help="Legislación: leyes, BOE, EUR-Lex\nJurisprudencia: CENDOJ, TC, TEDH, CNMC\nGeneral: todas las fuentes")

    badges = {"Legislación":"badge-leg","Jurisprudencia":"badge-jur","Consulta general":"badge-gen"}
    st.markdown(f'<span class="badge {badges[tipo]}">{tipo}</span>', unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("**Fuentes activas:**")

    dominios_activos = set(DOMINIOS_TIPO[tipo])
    for cat, fuentes in FUENTES_CATS.items():
        activas = [(d, api) for d, api in fuentes if d in dominios_activos]
        if not activas:
            continue
        st.markdown(f'<div class="src-cat">{cat}</div>', unsafe_allow_html=True)
        for d, api in activas:
            if api:
                st.markdown(f'• `{d}` <span class="api-badge">API</span>', unsafe_allow_html=True)
            else:
                st.markdown(f"• `{d}`")

    st.markdown("---")
    if st.button("🗑️ Limpiar conversación"):
        st.session_state.messages = []
        st.rerun()

    st.markdown("""
<div style="font-size:0.75rem;color:#94a3b8;margin-top:1rem;">
    <b>CUVEAI</b> — Demo confidencial<br>Solo para uso interno
</div>""", unsafe_allow_html=True)

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
  <span class="source-domain">🔗 {s['url'][:80]}</span>
</div>""", unsafe_allow_html=True)

if prompt := st.chat_input("Escribe tu consulta jurídica..."):
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        status = st.status("Buscando en fuentes jurídicas...", expanded=True)
        with status:
            n_fuentes = len([d for d in DOMINIOS_TIPO[tipo]])
            st.write(f"🔎 Consultando {n_fuentes} fuentes en paralelo...")
            results  = buscar_todas_fuentes(prompt, tipo)
            n        = len(results.get("results", []))
            hit_src  = results.get("hit_sources", {})

            # Resumen de hits por fuente
            partes = [f"{FUENTES_LABEL[k][0]}:{v}" for k, v in sorted(hit_src.items(), key=lambda x:-x[1])]
            st.write(f"📄 {n} resultados — " + " · ".join(partes) if partes else f"📄 {n} resultados")
            st.write("🧠 Analizando contenido jurídico...")
            contexto = construir_contexto(results)
            st.write("✍️ Redactando respuesta...")
        fuentes_con_hits = " · ".join(FUENTES_LABEL[k][0] for k in hit_src)
        status.update(label=f"✅ {n} resultados — {fuentes_con_hits}", state="complete", expanded=False)

        respuesta = st.write_stream(stream_respuesta(prompt, contexto))

        sources = results.get("results", [])
        if sources:
            with st.expander(f"📚 {len(sources)} fuentes consultadas"):
                for s in sources:
                    st.markdown(f"""
<div class="source-card">
  <a href="{s['url']}" target="_blank">{s['title']}</a><br>
  <span class="source-domain">🔗 {s['url'][:90]}</span>
</div>""", unsafe_allow_html=True)
        else:
            st.markdown('<div class="not-found-box">⚠️ No se encontraron fuentes jurídicas relevantes.</div>',
                        unsafe_allow_html=True)

    st.session_state.messages.append({
        "role": "assistant",
        "content": respuesta,
        "sources": sources
    })
