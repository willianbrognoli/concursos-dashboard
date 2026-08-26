"""Coletor de concursos a partir dos blogs Gran Cursos e Estratégia Concursos.

Fluxo (v2.0 — sem PCI):
1. Lê os feeds RSS dos dois blogs.
2. Para cada notícia nova sobre edital/concurso, baixa o ARTIGO COMPLETO.
3. Extrai do artigo: órgão, UF, vagas, salário, cargos, período de inscrição,
   data da prova, banca, taxa, link de inscrição, MATÉRIAS e as FASES do
   certame (objetiva, discursiva, TAF, psicológica, heteroidentificação etc.).
4. Faz upsert por órgão+UF — notícias dos dois blogs sobre o mesmo concurso
   alimentam o MESMO card (fases e matérias vão sendo mescladas).

O parser trabalha sobre o texto do artigo, tolerante a mudanças de layout.
"""
import logging
import re
import time
import unicodedata
from datetime import datetime, date

import feedparser
import requests
from bs4 import BeautifulSoup

from . import db as dbm
from .materias import (NOMES_UF, UFS, detectar_etapas, detectar_materias,
                       detectar_status_edital, regiao_da_uf)

log = logging.getLogger("scraper")

RSS_FEEDS = [
    ("Gran Cursos", "https://blog.grancursosonline.com.br/feed/"),
    ("Estratégia", "https://www.estrategiaconcursos.com.br/blog/feed/"),
]

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "março": 3, "abril": 4, "maio": 5,
    "junho": 6, "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10,
    "novembro": 11, "dezembro": 12,
}

BANCAS = [
    "Cebraspe", "Cespe", "FGV", "FCC", "Fundação Carlos Chagas", "Vunesp",
    "Cesgranrio", "IBFC", "Instituto AOCP", "AOCP", "Quadrix", "Idecan",
    "Fundatec", "FEPESE", "IADES", "Consulplan", "IBADE", "Objetiva",
    "FAUEL", "Fundep", "NC/UFPR", "UFPR", "Avança SP", "Instituto Access",
    "Legalle", "OMNI", "Instituto Verbena", "IGEDUC", "Itame", "Máxima",
    "Fafipa", "FAU", "Klc", "MS Concursos", "Gualimp", "Método", "Reis & Reis",
    "Cetro", "Instituto Mais", "IBAM", "Selecon", "FUNDEPE", "COSEAC",
]

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
DATE_RANGE_RE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*(?:a|à|ate|até)\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
EXTENSO_RE = re.compile(r"(\d{1,2})º?\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4}))?", re.I)

# título precisa parecer notícia de concurso/edital…
TITULO_CONCURSO_RE = re.compile(r"concurso|edital|processo seletivo|inscri|vagas", re.I)
# …e não ser conteúdo de estudo/marketing
TITULO_RUIDO_RE = re.compile(
    r"como estudar|dicas? de|simulado|apostila|mapa mental|questoes comentadas|"
    r"cronograma de estudos|resumo (?:de|sobre)|aula gratis|curso gratuito|"
    r"gabarito extraoficial|correcao (?:de|da) prova|raio[- ]?x|plano de estudos|"
    r"o que (?:e|sao)|quanto ganha|saiba como|entenda", re.I)

VERBOS_TITULO = (
    "tem|teve|abre|abriu|abrem|publica|publicou|publicado|oferece|oferta|esta|está|"
    "saiu|sai|divulga|divulgou|divulgado|prorroga|prorrogou|prorrogado|retifica|"
    "retificou|retificado|recebe|encerra|anuncia|anunciou|lanca|lança|lancou|lançou|"
    "convoca|forma|contara|contará|define|confirma|confirmado|autorizado|autoriza|"
    "iminente|previsto|prevista|aguarda|libera|liberado|homologa|homologado|reabre|"
    "cancela|cancelado|suspende|suspenso|sera|será|ainda|pode|deve|segue|preve|prevê"
)
ORGAO_CUT_RE = re.compile(r"\s+(?:" + VERBOS_TITULO + r")\b.*$", re.I)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").lower()
    return re.sub(r"[ \t]+", " ", s)


def _iso(d: int, m: int, y: int):
    try:
        if y < 100:
            y += 2000
        return date(y, m, d).isoformat()
    except ValueError:
        return None


def parse_date_extenso(text: str, default_year: int = None):
    m = EXTENSO_RE.search(_norm(text))
    if not m:
        return None
    dia, mes_nome, ano = int(m.group(1)), m.group(2), m.group(3)
    mes = MESES.get(mes_nome)
    if not mes:
        return None
    ano = int(ano) if ano else (default_year or datetime.now().year)
    return _iso(dia, mes, ano)


def fetch(url: str, session: requests.Session) -> str:
    r = session.get(url, headers=HEADERS, timeout=30)
    r.raise_for_status()
    return r.text


# ---------------------------------------------------------------- título
def extrair_orgao(titulo: str) -> str:
    """Extrai o nome do órgão/concurso do título da notícia."""
    t = titulo.strip()
    # corta a partir de dois-pontos / travessão / exclamação
    t = re.split(r"[:!|—–]", t)[0].strip()
    # remove prefixos comuns
    t = re.sub(r"^(?:concurso p[úu]blico|concursos?|edital|processo seletivo|sele[çc][ãa]o)\s+(?:d[oae]s?\s+)?",
               "", t, flags=re.I).strip()
    # corta no primeiro verbo de manchete
    t = ORGAO_CUT_RE.sub("", t).strip()
    # remove ano solto no final
    t = re.sub(r"\s+20\d{2}$", "", t).strip(" -–—,;")
    return t[:200] or titulo[:200]


# nomes de estado COM acento (contra o texto original, para "Pará" não casar com "para")
NOMES_UF_ACENTO = {
    "acre": "AC", "alagoas": "AL", "amapá": "AP", "amazonas": "AM", "bahia": "BA",
    "ceará": "CE", "distrito federal": "DF", "espírito santo": "ES", "goiás": "GO",
    "maranhão": "MA", "mato grosso do sul": "MS", "mato grosso": "MT",
    "minas gerais": "MG", "pará": "PA", "paraíba": "PB", "paraná": "PR",
    "pernambuco": "PE", "piauí": "PI", "rio de janeiro": "RJ",
    "rio grande do norte": "RN", "rio grande do sul": "RS", "rondônia": "RO",
    "roraima": "RR", "santa catarina": "SC", "são paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
}


def _uf_por_nome(fonte: str):
    low = fonte.lower()
    for nome in sorted(NOMES_UF_ACENTO, key=len, reverse=True):
        if re.search(r"\b" + re.escape(nome) + r"\b", low):
            return NOMES_UF_ACENTO[nome]
    return None


def extrair_uf(titulo: str, texto: str):
    """Tenta achar a UF no título e depois no texto."""
    # 1) sigla maiúscula no título ("PM PR", "Sefaz-BA", "(SP)")
    if titulo:
        for m in re.finditer(r"(?<![A-Za-z])([A-Z]{2})(?![A-Za-z])", titulo):
            sig = m.group(1)
            if sig in UFS and sig != "BR":
                return sig
        uf = _uf_por_nome(titulo)
        if uf:
            return uf
    # 2) nome do estado (com acento) no começo do texto
    if texto:
        uf = _uf_por_nome(texto[:1500])
        if uf:
            return uf
        m = re.search(r"[\(/\-–]\s*([A-Z]{2})\s*[\)]?(?=[\s,.;:!?]|$)", texto[:1500])
        if m and m.group(1) in UFS and m.group(1) != "BR":
            return m.group(1)
    ntudo = _norm((titulo or "") + " " + (texto or "")[:2000])
    if re.search(r"ambito nacional|todo o (?:brasil|pais)|carater nacional|nivel nacional", ntudo):
        return "BR"
    # órgãos federais típicos
    if re.search(r"\b(inss|ibge|receita federal|policia federal|prf|banco central|bacen|"
                 r"caixa|banco do brasil|correios|anvisa|ancine|antt|anatel|aneel|"
                 r"tribunal superior|stf|stj|tst|tse|stm|camara dos deputados|senado|"
                 r"ministerio d|advocacia[- ]geral da uniao|agu|dpu|mpu|trf|funai|ibama|"
                 r"icmbio|incra|dataprev|serpro|ebserh|embrapa)\b", ntudo):
        return "BR"
    return None


# ---------------------------------------------------------------- artigo
def parse_artigo(html: str, titulo: str):
    """Extrai os dados do concurso do artigo completo do blog."""
    soup = BeautifulSoup(html, "lxml")
    article = (soup.find("article") or soup.find("div", class_=re.compile(r"post-content|entry-content|single-content|article"))
               or soup.find("main") or soup)
    text = article.get_text(" ", strip=True)
    out = {}

    sentences = re.split(r"(?<=[\.\!\?;])\s+", text)

    # vagas
    mv = re.search(r"([\d\.]{1,7})\s+vagas", text)
    if mv:
        try:
            v = int(mv.group(1).replace(".", ""))
            if 0 < v < 200000:
                out["vagas"] = v
        except ValueError:
            pass

    # salário (maior valor R$ citado)
    valores = []
    for ms in re.finditer(r"R\$\s*([\d\.]+,\d{2})", text):
        try:
            valores.append(float(ms.group(1).replace(".", "").replace(",", ".")))
        except ValueError:
            pass
    if valores:
        maior = max(valores)
        if maior >= 500:  # ignora taxas
            out["salario_num"] = maior
            out["salario"] = "R$ " + f"{maior:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

    # data da prova — nunca em frase que fala de inscrição (evita capturar o
    # prazo de inscrição como data de prova)
    for s in sentences:
        ns = _norm(s)
        if "inscri" in ns:
            continue
        if re.search(r"\bprovas?\b|\bavaliacao objetiva\b|\bexame\b", ns) and \
           re.search(r"prevista|aplicad|realizad|marcad|agendad|ocorrer|acontec|data d", ns):
            d = None
            md = DATE_RE.search(s)
            if md:
                d = _iso(int(md.group(1)), int(md.group(2)), int(md.group(3)))
            if not d:
                d = parse_date_extenso(s, default_year=datetime.now().year)
            if d:
                out["prova_data"] = d
                out["prova_texto"] = s.strip()[:300]
                break

    # período de inscrição
    for s in sentences:
        ns = _norm(s)
        if "inscri" not in ns:
            continue
        mr = DATE_RANGE_RE.search(s)
        if mr:
            d1, m1, y1, d2, m2, y2 = mr.groups()
            out["inscricao_inicio"] = _iso(int(d1), int(m1), int(y1) if y1 else int(y2))
            out["inscricao_fim"] = _iso(int(d2), int(m2), int(y2))
            break
        extensos = []
        for m in EXTENSO_RE.finditer(_norm(s)):
            mes = MESES.get(m.group(2))
            if mes:
                ano = int(m.group(3)) if m.group(3) else datetime.now().year
                d = _iso(int(m.group(1)), mes, ano)
                if d:
                    extensos.append(d)
        numericas = [_iso(int(a), int(b), int(c)) for a, b, c in DATE_RE.findall(s)]
        numericas = [d for d in numericas if d]
        datas = extensos or numericas
        if len(datas) >= 2:
            out["inscricao_inicio"], out["inscricao_fim"] = min(datas), max(datas)
            break
        if len(datas) == 1 and re.search(r"\bate\b|\bencerr|prorrog", ns):
            out["inscricao_fim"] = datas[0]
            break

    # banca
    ntext = _norm(text)
    for banca in BANCAS:
        if re.search(r"\b" + re.escape(_norm(banca)) + r"\b", ntext):
            out["banca"] = banca
            break

    # taxa de inscrição
    mt = re.search(r"taxa[^.]{0,80}?R\$\s*([\d\.]+,\d{2})", text, re.I) or \
         re.search(r"R\$\s*([\d\.]+,\d{2})[^.]{0,60}?taxa", text, re.I)
    if mt:
        out["taxa"] = "R$ " + mt.group(1)

    # cargos ("para o cargo de X", "cargos de X e Y") — dentro de UMA frase,
    # cortando onde o assunto muda (vagas, inscrições, salário...)
    CARGO_CUT = re.compile(
        r"\s+(?:est[aã]o|estar[aã]o|ser[aã]o|ser[aá]\b|v[aã]o\b|t[eê]m\b|distribu\w*|"
        r"as inscri\w*|o vencimento|a remunera\w*|com sal[aá]rio|com remunera\w*|"
        r"abert[oa]s\b|em breve|no dia\b|at[eé]\b|que\b|para concorrer|oferecid\w*|"
        r"exig\w*|com carga|cuja\w*).*$", re.I)
    for s in sentences:
        mc = re.search(r"cargos? d[eo]s?\s+([^.;:!?\n]{4,120})", s, re.I)
        if not mc:
            continue
        cand = CARGO_CUT.sub("", mc.group(1)).strip().rstrip(",;-–— ")
        ncand = _norm(cand)
        if len(cand) >= 4 and not re.search(r"inscri|r\$|vencimento|remunera|\bvagas\b", ncand):
            out["cargos"] = cand[:300]
            break

    # sanidade: prova nunca acontece antes de encerrarem as inscrições
    if out.get("prova_data") and out.get("inscricao_fim") and \
       out["prova_data"] <= out["inscricao_fim"]:
        out.pop("prova_data", None)
        out.pop("prova_texto", None)

    # escolaridade
    niveis = []
    for nivel, pat in [("Fundamental", r"nivel fundamental"), ("Médio", r"nivel medio"),
                       ("Técnico", r"nivel tecnico"), ("Superior", r"nivel superior")]:
        if re.search(pat, ntext):
            niveis.append(nivel)
    if niveis:
        out["escolaridade"] = " / ".join(niveis)

    # link de inscrição (primeiro link externo que não é blog/rede social)
    for a in article.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and not re.search(
                r"grancursosonline|estrategia|facebook|twitter|whatsapp|instagram|"
                r"telegram|t\.me|youtube|linkedin|tiktok|google\.com|bit\.ly", href):
            texto_link = _norm(a.get_text(" ", strip=True))
            if re.search(r"inscri|edital|site|oficial|banca", texto_link) or \
               re.search(r"gov\.br|org\.br|\.br/concurso", href):
                out["url_inscricao"] = href
                break

    # resumo = primeiras ~2 frases
    if sentences:
        out["resumo"] = " ".join(sentences[:2])[:500]

    out["_texto"] = text
    return out


def montar_concurso(fonte: str, titulo: str, link: str, art: dict) -> dict:
    """Monta o dict de concurso a partir do artigo parseado."""
    texto = art.get("_texto", "")
    orgao = extrair_orgao(titulo)
    uf = extrair_uf(titulo, texto)
    data = {k: v for k, v in art.items() if not k.startswith("_")}
    data.update({
        "url_fonte": link,
        "orgao": orgao,
        "uf": uf,
        "regiao": regiao_da_uf(uf),
        "materias": detectar_materias(texto, titulo, art.get("cargos")),
        "etapas": detectar_etapas(texto, titulo),
        "edital_status": detectar_status_edital(titulo, texto),
        "texto_base": (titulo + "\n" + texto)[:6000],
        "origem": "scraper",
        "detalhado": 1,
    })
    return data


def eh_noticia_de_concurso(titulo: str) -> bool:
    nt = _norm(titulo)
    return bool(TITULO_CONCURSO_RE.search(nt)) and not TITULO_RUIDO_RE.search(nt)


def vale_criar_concurso(art: dict, titulo: str) -> bool:
    """Cria o card se o artigo tem dados concretos OU um status de pipeline
    (previsto/autorizado/banca definida...), para acompanhar o edital desde cedo."""
    nt = _norm(titulo)
    tem_gatilho = bool(re.search(r"edital|inscric|concurso|processo seletivo", nt))
    if not tem_gatilho:
        return False
    tem_dado = any(art.get(k) for k in ("vagas", "inscricao_fim", "prova_data", "banca"))
    tem_status = detectar_status_edital(titulo, art.get("_texto", "")) is not None
    return tem_dado or tem_status


# ----------------------------------------------------------------- run
def run_scrape(max_articles: int = 60, delay: float = 1.0) -> dict:
    """Executa a coleta completa. Retorna resumo p/ log."""
    started = dbm.now_iso()
    found = created = updated = errors = enriched = 0
    detail_msgs = []
    session = requests.Session()

    with dbm.get_db() as db:
        db.execute("INSERT INTO scrape_logs (started_at, detail) VALUES (?, ?)",
                   (started, "em andamento"))
        log_id = db.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]

    novos = []  # (fonte, titulo, link)
    for fonte, url in RSS_FEEDS:
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            qtd = 0
            with dbm.get_db() as db:
                for entry in feed.entries[:60]:
                    titulo = (entry.get("title") or "").strip()
                    link = (entry.get("link") or "").strip()
                    if not titulo or not link or not eh_noticia_de_concurso(titulo):
                        continue
                    pub = None
                    if entry.get("published_parsed"):
                        pub = time.strftime("%Y-%m-%dT%H:%M:%S", entry.published_parsed)
                    resumo = BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True)[:400]
                    if dbm.upsert_noticia(db, url=link, titulo=titulo, fonte=fonte,
                                          publicado_em=pub, resumo=resumo):
                        novos.append((fonte, titulo, link))
                        qtd += 1
            detail_msgs.append(f"{fonte}: {qtd} notícias novas")
        except Exception as e:
            errors += 1
            detail_msgs.append(f"{fonte}: ERRO RSS {e}")
            log.warning("RSS %s falhou: %s", fonte, e)

    found = len(novos)

    # baixa o artigo completo de cada notícia nova e tenta montar o concurso
    for fonte, titulo, link in novos[:max_articles]:
        try:
            html = fetch(link, session)
            art = parse_artigo(html, titulo)
            if vale_criar_concurso(art, titulo):
                data = montar_concurso(fonte, titulo, link, art)
                with dbm.get_db() as db:
                    res = dbm.upsert_concurso(db, data)
                created += res == "created"
                updated += res == "updated"
                enriched += 1
        except Exception as e:
            errors += 1
            log.warning("Artigo falhou p/ %s: %s", link, e)
        time.sleep(delay)
    if found > max_articles:
        detail_msgs.append(f"limite de artigos por coleta: {max_articles} (ficaram {found - max_articles})")

    # re-detecção nos abertos vindos do scraper: recalcula matérias/fases/status
    # a partir do texto guardado (aplica padrões novos E remove falsos positivos)
    import json as _json
    from .materias import STATUS_EDITAL
    with dbm.get_db() as db:
        for r in db.execute(
            "SELECT id, orgao, cargos, resumo, texto_base, materias, etapas, edital_status, "
            "prova_data, inscricao_fim FROM concursos WHERE status='aberto' AND origem='scraper'"
        ).fetchall():
            base = r["texto_base"] or ""
            if base:
                novas_m = set(detectar_materias(base, r["orgao"], r["cargos"]))
                novas_e = set(detectar_etapas(base, r["orgao"], r["cargos"]))
                novo_s = detectar_status_edital(base)
            else:  # linhas antigas sem texto guardado
                novas_m = set(detectar_materias(r["orgao"], r["cargos"], r["resumo"]))
                novas_e = set(detectar_etapas(r["orgao"], r["cargos"], r["resumo"])) | \
                          set(_json.loads(r["etapas"] or "[]"))
                novo_s = detectar_status_edital(r["orgao"], r["cargos"], r["resumo"])
            # status nunca regride
            atual_s = r["edital_status"]
            if atual_s and novo_s:
                try:
                    if STATUS_EDITAL.index(novo_s) < STATUS_EDITAL.index(atual_s):
                        novo_s = atual_s
                except ValueError:
                    pass
            novo_s = novo_s or atual_s
            # sanidade retroativa: prova antes do fim das inscrições = dado errado
            prova = r["prova_data"]
            if prova and r["inscricao_fim"] and prova <= r["inscricao_fim"]:
                prova = None
            mudou = (sorted(novas_m) != sorted(_json.loads(r["materias"] or "[]")) or
                     sorted(novas_e) != sorted(_json.loads(r["etapas"] or "[]")) or
                     novo_s != atual_s or prova != r["prova_data"])
            if mudou:
                db.execute(
                    "UPDATE concursos SET materias=?, etapas=?, edital_status=?, "
                    "prova_data=?, prova_texto=CASE WHEN ? IS NULL THEN NULL ELSE prova_texto END, "
                    "updated_at=? WHERE id=?",
                    (_json.dumps(sorted(novas_m), ensure_ascii=False),
                     _json.dumps(sorted(novas_e), ensure_ascii=False),
                     novo_s, prova, prova, dbm.now_iso(), r["id"]))

    with dbm.get_db() as db:
        dedup = dbm.dedupe_open(db)
        if dedup:
            detail_msgs.append(f"duplicatas removidas: {dedup}")
        closed = dbm.close_expired(db)
        purged = dbm.purge_old(db)
        if purged:
            detail_msgs.append(f"antigos removidos (>90d): {purged}")
        db.execute(
            "UPDATE scrape_logs SET finished_at=?, found=?, created=?, updated=?, closed=?, errors=?, detail=? WHERE id=?",
            (dbm.now_iso(), found, created, updated, closed, errors,
             "; ".join(detail_msgs) + f"; artigos processados: {enriched}", log_id),
        )

    summary = {"found": found, "created": created, "updated": updated,
               "closed": closed, "errors": errors, "enriched": enriched}
    log.info("Coleta concluída: %s", summary)
    return summary
