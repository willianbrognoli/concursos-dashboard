"""Coletor de concursos abertos a partir do PCI Concursos.

Estratégia em duas etapas:
1. Páginas de listagem por região (/concursos/<regiao>/): órgão, UF, vagas,
   salário, cargos, escolaridade e prazo de inscrição.
2. Página de detalhe (notícia) de cada concurso novo: período de inscrição,
   data da prova, banca, taxa, link de inscrição e detecção de matérias.

O parser é deliberadamente tolerante a mudanças de markup: trabalha sobre o
texto dos blocos, não sobre classes CSS específicas.
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
from .materias import UFS, detectar_materias, regiao_da_uf

log = logging.getLogger("scraper")

BASE = "https://www.pciconcursos.com.br"
REGIOES_SLUGS = {
    "Norte": ["norte"],
    "Nordeste": ["nordeste"],
    "Centro-Oeste": ["centrooeste", "centro-oeste", "centro_oeste"],
    "Sudeste": ["sudeste"],
    "Sul": ["sul"],
    "Nacional": ["nacional"],
}

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
]

DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{2,4})")
DATE_RANGE_RE = re.compile(r"(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\s*(?:a|à|ate|até)\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
EXTENSO_RE = re.compile(r"(\d{1,2})º?\s+de\s+([a-zç]+)(?:\s+de\s+(\d{4}))?", re.I)


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


# ------------------------------------------------------------- listagem
ESCOLARIDADE_WORDS = {"fundamental", "medio", "tecnico", "superior", "mestrado", "doutorado", "alfabetizado"}


def _classify_lines(lines):
    """Recebe as linhas de texto de um bloco de concurso e devolve um dict."""
    out = {"orgao": None, "uf": None, "vagas": None, "vagas_texto": None,
           "salario": None, "salario_num": None, "cargos": None,
           "escolaridade": None, "inscricao_fim": None, "inscricao_inicio": None,
           "inscricao_texto": None}
    resto = []
    for raw in lines:
        line = " ".join(raw.split())
        if not line:
            continue
        nline = _norm(line)
        # UF isolada
        if line.upper() in UFS and len(line) == 2:
            out["uf"] = line.upper()
            continue
        # linha de vagas / salário
        if re.search(r"\bvagas?\b", nline) or "r$" in nline:
            mv = re.search(r"([\d\.]+)\s+vagas?", nline)
            if mv:
                try:
                    out["vagas"] = int(mv.group(1).replace(".", ""))
                except ValueError:
                    pass
            ms = re.search(r"r\$\s*([\d\.]+,\d{2})", nline)
            if ms:
                out["salario"] = "R$ " + ms.group(1)
                try:
                    out["salario_num"] = float(ms.group(1).replace(".", "").replace(",", "."))
                except ValueError:
                    pass
            out["vagas_texto"] = line
            continue
        # escolaridade (linha composta apenas por níveis separados por /)
        parts = [p.strip() for p in nline.split("/") if p.strip()]
        if parts and all(p in ESCOLARIDADE_WORDS for p in parts):
            out["escolaridade"] = line
            continue
        # datas de inscrição
        mr = DATE_RANGE_RE.search(line)
        if mr:
            d1, m1, y1, d2, m2, y2 = mr.groups()
            y2i = int(y2)
            out["inscricao_inicio"] = _iso(int(d1), int(m1), int(y1) if y1 else y2i)
            out["inscricao_fim"] = _iso(int(d2), int(m2), y2i)
            out["inscricao_texto"] = line
            continue
        md = DATE_RE.search(line)
        if md and len(nline) <= 40:
            out["inscricao_fim"] = _iso(int(md.group(1)), int(md.group(2)), int(md.group(3)))
            out["inscricao_texto"] = line
            continue
        resto.append(line)
    if resto:
        out["orgao"] = resto[0]
        if len(resto) > 1:
            out["cargos"] = " / ".join(resto[1:])[:400]
    return out


def parse_listing(html: str, regiao: str):
    """Extrai os concursos de uma página de listagem regional."""
    soup = BeautifulSoup(html, "lxml")
    seen = set()
    results = []
    # blocos candidatos: qualquer container que tenha um link para /noticias/
    for a in soup.find_all("a", href=re.compile(r"/noticias/")):
        # sobe na árvore até achar o menor container que pareça uma ficha
        block, text = None, ""
        node = a
        for _ in range(6):
            node = node.find_parent(["div", "li", "article", "tr", "section"])
            if node is None:
                break
            t = node.get_text("\n", strip=True)
            if len(t) > 700:  # container grande demais = página inteira
                break
            nt = _norm(t)
            if DATE_RE.search(t) and ("vaga" in nt or "r$" in nt):
                block, text = node, t
                break
        if block is None:
            continue
        url = a["href"]
        if url.startswith("/"):
            url = BASE + url
        if url in seen:
            continue
        seen.add(url)
        data = _classify_lines(text.split("\n"))
        if not data["orgao"]:
            data["orgao"] = a.get_text(strip=True) or a.get("title") or "Órgão não identificado"
        if regiao == "Nacional" and not data["uf"]:
            data["uf"] = "BR"
        data["regiao"] = regiao_da_uf(data["uf"]) or regiao
        data["url_fonte"] = url
        results.append(data)
    return results


# -------------------------------------------------------------- detalhe
def parse_detail(html: str):
    """Extrai informações extras da página de notícia do concurso."""
    soup = BeautifulSoup(html, "lxml")
    # zona principal do artigo
    article = soup.find("article") or soup.find("div", id="materia") or soup
    text = article.get_text(" ", strip=True)
    out = {}

    # frases
    sentences = re.split(r"(?<=[\.\!\?;])\s+", text)

    # data da prova
    for s in sentences:
        ns = _norm(s)
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

    # período de inscrição (frases com "inscri")
    if "prova_data" in out or True:
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
            # datas por extenso na frase de inscrição
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
    for banca in BANCAS:
        if re.search(r"\b" + re.escape(_norm(banca)) + r"\b", _norm(text)):
            out["banca"] = banca
            break

    # taxa de inscrição
    mt = re.search(r"taxa[^.]{0,80}?R\$\s*([\d\.]+,\d{2})", text, re.I) or \
         re.search(r"R\$\s*([\d\.]+,\d{2})[^.]{0,60}?taxa", text, re.I)
    if mt:
        out["taxa"] = "R$ " + mt.group(1)

    # link de inscrição (primeiro link externo que não é PCI/rede social)
    for a in article.find_all("a", href=True):
        href = a["href"]
        if href.startswith("http") and "pciconcursos" not in href and \
           not re.search(r"facebook|twitter|whatsapp|instagram|telegram|t\.me|youtube", href):
            out["url_inscricao"] = href
            break

    # resumo = primeiras ~2 frases
    if sentences:
        out["resumo"] = " ".join(sentences[:2])[:500]

    out["_texto"] = text
    return out


# ------------------------------------------------------------------ rss
RSS_FEEDS = [
    ("Gran Cursos", "https://blog.grancursosonline.com.br/feed/"),
    ("Estratégia", "https://www.estrategiaconcursos.com.br/blog/feed/"),
]
RSS_KEYWORDS = re.compile(r"concurso|edital|inscri|vaga|prova|banca|resultado|gabarito", re.I)


def collect_rss(session: requests.Session) -> dict:
    """Coleta notícias de editais dos feeds do Gran e do Estratégia."""
    added = errors = 0
    for fonte, url in RSS_FEEDS:
        try:
            r = session.get(url, headers=HEADERS, timeout=30)
            r.raise_for_status()
            feed = feedparser.parse(r.content)
            with dbm.get_db() as db:
                for entry in feed.entries[:40]:
                    titulo = (entry.get("title") or "").strip()
                    link = (entry.get("link") or "").strip()
                    if not titulo or not link:
                        continue
                    if not RSS_KEYWORDS.search(titulo):
                        continue
                    pub = None
                    if entry.get("published_parsed"):
                        pub = time.strftime("%Y-%m-%dT%H:%M:%S", entry.published_parsed)
                    resumo = BeautifulSoup(entry.get("summary", ""), "lxml").get_text(" ", strip=True)[:400]
                    if dbm.upsert_noticia(db, url=link, titulo=titulo, fonte=fonte,
                                          publicado_em=pub, resumo=resumo):
                        added += 1
        except Exception as e:
            errors += 1
            log.warning("RSS %s falhou: %s", fonte, e)
    return {"added": added, "errors": errors}


# ----------------------------------------------------------------- run
def run_scrape(max_details: int = 80, delay: float = 1.0) -> dict:
    """Executa a coleta completa. Retorna resumo p/ log."""
    started = dbm.now_iso()
    found = created = updated = errors = 0
    detail_msgs = []
    session = requests.Session()

    with dbm.get_db() as db:
        db.execute(
            "INSERT INTO scrape_logs (started_at, detail) VALUES (?, ?)",
            (started, "em andamento"),
        )
        log_id = db.execute("SELECT last_insert_rowid() AS i").fetchone()["i"]

    listings = []
    for regiao, slugs in REGIOES_SLUGS.items():
        ok = False
        for slug in slugs:
            url = f"{BASE}/concursos/{slug}/"
            try:
                html = fetch(url, session)
                items = parse_listing(html, regiao)
                listings.extend(items)
                detail_msgs.append(f"{regiao}: {len(items)} concursos")
                ok = True
                break
            except Exception as e:  # tenta próximo slug
                last_err = e
        if not ok:
            errors += 1
            detail_msgs.append(f"{regiao}: ERRO {last_err}")
            log.warning("Falha na região %s: %s", regiao, last_err)
        time.sleep(delay)

    found = len(listings)

    with dbm.get_db() as db:
        for item in listings:
            item.setdefault("materias", detectar_materias(item.get("cargos"), item.get("orgao")))
            try:
                res = dbm.upsert_concurso(db, item)
                created += res == "created"
                updated += res == "updated"
            except Exception as e:
                errors += 1
                log.warning("Upsert falhou p/ %s: %s", item.get("url_fonte"), e)

        # detalhes pendentes (novos primeiro)
        pend = db.execute(
            "SELECT id, url_fonte, cargos, orgao FROM concursos "
            "WHERE detalhado=0 AND status='aberto' AND url_fonte IS NOT NULL "
            "ORDER BY id DESC LIMIT ?", (max_details,),
        ).fetchall()

    enriched = 0
    for row in pend:
        try:
            html = fetch(row["url_fonte"], session)
            det = parse_detail(html)
            texto = det.pop("_texto", "")
            det["materias"] = detectar_materias(texto, row["cargos"], row["orgao"])
            det["detalhado"] = 1
            det["url_fonte"] = row["url_fonte"]
            with dbm.get_db() as db:
                sets, vals = [], []
                for k, v in det.items():
                    if k == "url_fonte" or v in (None, ""):
                        continue
                    if k == "materias":
                        import json as _json
                        old = db.execute("SELECT materias FROM concursos WHERE id=?", (row["id"],)).fetchone()
                        merged = sorted(set(_json.loads(old["materias"] or "[]")) | set(v))
                        v = _json.dumps(merged, ensure_ascii=False)
                    sets.append(f"{k}=?")
                    vals.append(v)
                sets.append("detalhado=1")
                sets.append("updated_at=?")
                vals.append(dbm.now_iso())
                db.execute(f"UPDATE concursos SET {', '.join(sets)} WHERE id=?", vals + [row["id"]])
            enriched += 1
        except Exception as e:
            errors += 1
            log.warning("Detalhe falhou p/ %s: %s", row["url_fonte"], e)
        time.sleep(delay)

    # re-detecção de matérias nos abertos (aplica padrões novos ao que já existe)
    import json as _json
    with dbm.get_db() as db:
        for r in db.execute("SELECT id, orgao, cargos, resumo, materias FROM concursos WHERE status='aberto'").fetchall():
            novas = set(detectar_materias(r["orgao"], r["cargos"], r["resumo"]))
            atuais = set(_json.loads(r["materias"] or "[]"))
            if novas - atuais:
                db.execute("UPDATE concursos SET materias=?, updated_at=? WHERE id=?",
                           (_json.dumps(sorted(atuais | novas), ensure_ascii=False), dbm.now_iso(), r["id"]))

    rss = collect_rss(session)
    errors += rss["errors"]
    detail_msgs.append(f"RSS: {rss['added']} notícias novas")

    with dbm.get_db() as db:
        closed = dbm.close_expired(db)
        db.execute(
            "UPDATE scrape_logs SET finished_at=?, found=?, created=?, updated=?, closed=?, errors=?, detail=? WHERE id=?",
            (dbm.now_iso(), found, created, updated, closed, errors,
             "; ".join(detail_msgs) + f"; detalhes enriquecidos: {enriched}", log_id),
        )

    summary = {"found": found, "created": created, "updated": updated,
               "closed": closed, "errors": errors, "enriched": enriched}
    log.info("Coleta concluída: %s", summary)
    return summary
