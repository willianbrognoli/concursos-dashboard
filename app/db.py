"""Camada de banco de dados (SQLite) do Dashboard de Oportunidades."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from .materias import STATUS_EDITAL

DB_PATH = os.environ.get("DB_PATH", "/data/concursos.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    is_admin INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    email TEXT,
    success INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT 'login', -- login | register | logout
    ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS concursos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_fonte TEXT UNIQUE,
    orgao TEXT NOT NULL,
    uf TEXT,                -- sigla (PR, SP...) ou 'BR' p/ nacional
    regiao TEXT,            -- Norte, Nordeste, Centro-Oeste, Sudeste, Sul, Nacional
    vagas INTEGER,
    vagas_texto TEXT,
    salario TEXT,
    salario_num REAL,
    cargos TEXT,
    escolaridade TEXT,
    inscricao_inicio TEXT,  -- ISO date
    inscricao_fim TEXT,     -- ISO date
    inscricao_texto TEXT,
    prova_data TEXT,        -- ISO date
    prova_texto TEXT,
    banca TEXT,
    taxa TEXT,
    materias TEXT NOT NULL DEFAULT '[]',  -- JSON list
    etapas TEXT NOT NULL DEFAULT '[]',    -- JSON list (fases do certame)
    edital_status TEXT,                   -- status citado no texto (pipeline do edital)
    texto_base TEXT,                      -- texto do artigo p/ re-detecção
    resumo TEXT,
    url_inscricao TEXT,
    status TEXT NOT NULL DEFAULT 'aberto', -- aberto | encerrado
    origem TEXT NOT NULL DEFAULT 'scraper', -- scraper | manual
    detalhado INTEGER NOT NULL DEFAULT 0,   -- página de detalhe já processada
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_concursos_uf ON concursos(uf);
CREATE INDEX IF NOT EXISTS idx_concursos_regiao ON concursos(regiao);
CREATE INDEX IF NOT EXISTS idx_concursos_inscricao_fim ON concursos(inscricao_fim);
CREATE INDEX IF NOT EXISTS idx_concursos_prova ON concursos(prova_data);
CREATE INDEX IF NOT EXISTS idx_concursos_status ON concursos(status);

CREATE TABLE IF NOT EXISTS noticias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL UNIQUE,
    titulo TEXT NOT NULL,
    fonte TEXT NOT NULL,          -- Gran Cursos | Estratégia
    publicado_em TEXT,            -- ISO datetime
    resumo TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_noticias_pub ON noticias(publicado_em);

CREATE TABLE IF NOT EXISTS scrape_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    found INTEGER DEFAULT 0,
    created INTEGER DEFAULT 0,
    updated INTEGER DEFAULT 0,
    closed INTEGER DEFAULT 0,
    errors INTEGER DEFAULT 0,
    detail TEXT
);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = sqlite3.connect(DB_PATH, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


@contextmanager
def get_db():
    con = connect()
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def init_db():
    with get_db() as db:
        db.executescript(SCHEMA)
        # migrações de bancos antigos
        cols = [r["name"] for r in db.execute("PRAGMA table_info(concursos)").fetchall()]
        if "etapas" not in cols:
            db.execute("ALTER TABLE concursos ADD COLUMN etapas TEXT NOT NULL DEFAULT '[]'")
        if "edital_status" not in cols:
            db.execute("ALTER TABLE concursos ADD COLUMN edital_status TEXT")
        if "texto_base" not in cols:
            db.execute("ALTER TABLE concursos ADD COLUMN texto_base TEXT")


# ---------------------------------------------------------------- users
def create_user(db, name, email, password_hash, is_admin=False):
    cur = db.execute(
        "INSERT INTO users (name, email, password_hash, is_admin, created_at) VALUES (?,?,?,?,?)",
        (name.strip(), email.strip().lower(), password_hash, int(is_admin), now_iso()),
    )
    return cur.lastrowid


def get_user_by_email(db, email):
    return db.execute("SELECT * FROM users WHERE email = ?", (email.strip().lower(),)).fetchone()


def get_user(db, user_id):
    return db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def count_users(db) -> int:
    return db.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]


def log_access(db, *, user_id=None, email=None, success=True, kind="login", ip=None, user_agent=None):
    db.execute(
        "INSERT INTO login_logs (user_id, email, success, kind, ip, user_agent, created_at) VALUES (?,?,?,?,?,?,?)",
        (user_id, email, int(success), kind, ip, (user_agent or "")[:300], now_iso()),
    )


# ------------------------------------------------------------- noticias
def upsert_noticia(db, *, url, titulo, fonte, publicado_em=None, resumo=None) -> bool:
    """Insere notícia se nova. Retorna True se criou."""
    try:
        db.execute(
            "INSERT INTO noticias (url, titulo, fonte, publicado_em, resumo, created_at) VALUES (?,?,?,?,?,?)",
            (url, titulo[:300], fonte, publicado_em, (resumo or "")[:400], now_iso()),
        )
        return True
    except sqlite3.IntegrityError:
        return False


def latest_noticias(db, limit=20):
    return [dict(r) for r in db.execute(
        "SELECT * FROM noticias ORDER BY COALESCE(publicado_em, created_at) DESC LIMIT ?",
        (limit,)).fetchall()]


# ------------------------------------------------------------ concursos
CONCURSO_FIELDS = [
    "url_fonte", "orgao", "uf", "regiao", "vagas", "vagas_texto", "salario",
    "salario_num", "cargos", "escolaridade", "inscricao_inicio", "inscricao_fim",
    "inscricao_texto", "prova_data", "prova_texto", "banca", "taxa", "materias",
    "etapas", "edital_status", "texto_base", "resumo", "url_inscricao", "status",
    "origem", "detalhado",
]

_JSON_LIST_FIELDS = ("materias", "etapas")


def upsert_concurso(db, data: dict) -> str:
    """Insere ou atualiza pelo url_fonte. Retorna 'created' ou 'updated'."""
    data = dict(data)
    for jf in _JSON_LIST_FIELDS:
        if isinstance(data.get(jf), (list, tuple)):
            data[jf] = json.dumps(sorted(set(data[jf])), ensure_ascii=False)
    existing = None
    if data.get("url_fonte"):
        existing = db.execute(
            "SELECT * FROM concursos WHERE url_fonte = ?", (data["url_fonte"],)
        ).fetchone()
    # anti-duplicata: mesmo órgão+UF ainda aberto = mesmo concurso, mesmo que o
    # PCI tenha publicado uma notícia nova (retificação/prorrogação) com outra URL
    if existing is None and data.get("orgao"):
        existing = db.execute(
            "SELECT * FROM concursos WHERE status='aberto' "
            "AND lower(trim(orgao)) = lower(trim(?)) AND COALESCE(uf,'') = COALESCE(?, '')",
            (data["orgao"], data.get("uf")),
        ).fetchone()
    ts = now_iso()
    if existing:
        # não sobrescrever com vazio; preservar edições manuais de matérias se scraper não achou nada
        merged = {}
        for f in CONCURSO_FIELDS:
            new_val = data.get(f)
            if f in _JSON_LIST_FIELDS:
                try:
                    old = json.loads(existing[f] or "[]")
                except (KeyError, IndexError, TypeError, ValueError):
                    old = []
                new = json.loads(new_val) if new_val else []
                merged[f] = json.dumps(sorted(set(old) | set(new)), ensure_ascii=False)
            elif f == "edital_status" and new_val and existing["edital_status"]:
                # nunca regredir no pipeline (notícia antiga não volta o status)
                try:
                    avanca = STATUS_EDITAL.index(new_val) >= STATUS_EDITAL.index(existing["edital_status"])
                except ValueError:
                    avanca = True
                merged[f] = new_val if avanca else existing["edital_status"]
            elif new_val not in (None, "", []):
                merged[f] = new_val
            else:
                merged[f] = existing[f]
        sets = ", ".join(f"{f}=?" for f in CONCURSO_FIELDS)
        db.execute(
            f"UPDATE concursos SET {sets}, updated_at=? WHERE id=?",
            [merged[f] for f in CONCURSO_FIELDS] + [ts, existing["id"]],
        )
        return "updated"
    else:
        for f in CONCURSO_FIELDS:
            data.setdefault(f, None)
        data["materias"] = data.get("materias") or "[]"
        data["etapas"] = data.get("etapas") or "[]"
        data["status"] = data.get("status") or "aberto"
        data["origem"] = data.get("origem") or "scraper"
        data["detalhado"] = data.get("detalhado") or 0
        cols = ", ".join(CONCURSO_FIELDS)
        marks = ", ".join("?" for _ in CONCURSO_FIELDS)
        db.execute(
            f"INSERT INTO concursos ({cols}, created_at, updated_at) VALUES ({marks},?,?)",
            [data[f] for f in CONCURSO_FIELDS] + [ts, ts],
        )
        return "created"


def purge_old(db, days: int = 90) -> int:
    """Remove concursos muito antigos (prova realizada ou inscrição encerrada há mais de N dias)."""
    from datetime import timedelta
    cutoff = (datetime.now().date() - timedelta(days=days)).isoformat()
    stale = (datetime.now().date() - timedelta(days=days + 30)).isoformat()
    cur = db.execute(
        "DELETE FROM concursos WHERE origem != 'manual' AND ("
        " (prova_data IS NOT NULL AND prova_data < ?) OR"
        " (prova_data IS NULL AND inscricao_fim IS NOT NULL AND inscricao_fim < ?) OR"
        " (prova_data IS NULL AND inscricao_fim IS NULL AND substr(updated_at,1,10) < ?))",
        (cutoff, cutoff, stale),
    )
    return cur.rowcount


def dedupe_open(db) -> int:
    """Remove duplicatas abertas (mesmo órgão+UF), mantendo a mais completa/recente.
    Mescla as matérias antes de excluir."""
    rows = db.execute(
        "SELECT id, orgao, uf, materias, etapas, detalhado, updated_at FROM concursos "
        "WHERE status='aberto' ORDER BY detalhado DESC, updated_at DESC, id DESC"
    ).fetchall()
    seen: dict = {}
    removed = 0
    for r in rows:
        key = ((r["orgao"] or "").strip().lower(), (r["uf"] or "").strip().upper())
        if key in seen:
            keeper = seen[key]
            keeper["materias"] |= set(json.loads(r["materias"] or "[]"))
            keeper["etapas"] |= set(json.loads(r["etapas"] or "[]"))
            db.execute("UPDATE concursos SET materias=?, etapas=?, updated_at=? WHERE id=?",
                       (json.dumps(sorted(keeper["materias"]), ensure_ascii=False),
                        json.dumps(sorted(keeper["etapas"]), ensure_ascii=False),
                        now_iso(), keeper["id"]))
            db.execute("DELETE FROM concursos WHERE id=?", (r["id"],))
            removed += 1
        else:
            seen[key] = {"id": r["id"],
                         "materias": set(json.loads(r["materias"] or "[]")),
                         "etapas": set(json.loads(r["etapas"] or "[]"))}
    return removed


def close_expired(db) -> int:
    """Marca como encerrado tudo cuja inscrição terminou antes de hoje."""
    today = datetime.now().date().isoformat()
    cur = db.execute(
        "UPDATE concursos SET status='encerrado', updated_at=? "
        "WHERE status='aberto' AND inscricao_fim IS NOT NULL AND inscricao_fim < ?",
        (now_iso(), today),
    )
    return cur.rowcount


# status efetivo = status citado no texto corrigido pelas datas
_EFFECTIVE_STATUS_SQL = """
CASE
  WHEN edital_status = 'Homologado' THEN 'Homologado'
  WHEN prova_data IS NOT NULL AND prova_data < ? THEN 'Prova Realizada'
  WHEN inscricao_fim IS NOT NULL AND inscricao_fim < ? THEN 'Inscrições Encerradas'
  WHEN inscricao_fim IS NOT NULL THEN 'Inscrições Abertas'
  WHEN edital_status IS NOT NULL THEN edital_status
  WHEN banca IS NOT NULL OR prova_data IS NOT NULL THEN 'Edital Aberto'
  ELSE NULL
END
"""


def query_concursos(db, *, q=None, materias=None, etapas=None, uf=None, regiao=None,
                    inscricao_ate=None, prova_de=None, prova_ate=None,
                    status="aberto", fase=None, edital_status=None,
                    order="inscricao_fim", limit=500):
    today = datetime.now().date().isoformat()
    sql = f"SELECT *, ({_EFFECTIVE_STATUS_SQL}) AS status_efetivo FROM concursos WHERE 1=1"
    params: list = [today, today]
    if edital_status:
        sql += f" AND ({_EFFECTIVE_STATUS_SQL}) = ?"
        params += [today, today, edital_status]
    if fase:
        # fase deriva das datas e tem prioridade sobre status
        if fase == "abertas":
            sql += " AND status = 'aberto'"
        elif fase == "aguardando_prova":
            sql += (" AND inscricao_fim IS NOT NULL AND inscricao_fim < ?"
                    " AND (prova_data IS NULL OR prova_data >= ?)")
            params += [today, today]
        elif fase == "prova_realizada":
            sql += " AND prova_data IS NOT NULL AND prova_data < ?"
            params.append(today)
        # fase == 'todas' -> sem condição
    elif status and status != "todos":
        sql += " AND status = ?"
        params.append(status)
    if q:
        sql += " AND (orgao LIKE ? OR cargos LIKE ? OR resumo LIKE ? OR banca LIKE ?)"
        like = f"%{q}%"
        params += [like, like, like, like]
    if uf:
        sql += " AND uf = ?"
        params.append(uf.upper())
    if regiao:
        sql += " AND regiao = ?"
        params.append(regiao)
    if inscricao_ate:
        sql += " AND inscricao_fim IS NOT NULL AND inscricao_fim <= ?"
        params.append(inscricao_ate)
    if prova_de:
        sql += " AND prova_data IS NOT NULL AND prova_data >= ?"
        params.append(prova_de)
    if prova_ate:
        sql += " AND prova_data IS NOT NULL AND prova_data <= ?"
        params.append(prova_ate)
    if materias:
        for m in materias:
            sql += " AND materias LIKE ?"
            params.append(f'%"{m}"%')
    if etapas:
        for e in etapas:
            sql += " AND etapas LIKE ?"
            params.append(f'%"{e}"%')
    orders = {
        "inscricao_fim": "CASE WHEN inscricao_fim IS NULL THEN 1 ELSE 0 END, inscricao_fim ASC",
        "prova_data": "CASE WHEN prova_data IS NULL THEN 1 ELSE 0 END, prova_data ASC",
        "vagas": "vagas DESC NULLS LAST",
        "salario": "salario_num DESC NULLS LAST",
        "recentes": "created_at DESC",
    }
    sql += " ORDER BY " + orders.get(order, orders["inscricao_fim"])
    sql += " LIMIT ?"
    params.append(limit)
    rows = db.execute(sql, params).fetchall()
    return [row_to_dict(r) for r in rows]


def row_to_dict(r: sqlite3.Row) -> dict:
    d = dict(r)
    for jf in _JSON_LIST_FIELDS:
        try:
            d[jf] = json.loads(d.get(jf) or "[]")
        except Exception:
            d[jf] = []
    return d


def all_materias(db) -> list:
    """Lista de matérias distintas presentes na base (para o filtro)."""
    out = set()
    for r in db.execute("SELECT materias FROM concursos WHERE status='aberto'"):
        try:
            out.update(json.loads(r["materias"] or "[]"))
        except Exception:
            pass
    return sorted(out)


def stats(db) -> dict:
    row = db.execute(
        "SELECT COUNT(*) AS total, COALESCE(SUM(vagas),0) AS vagas FROM concursos WHERE status='aberto'"
    ).fetchone()
    provas = db.execute(
        "SELECT COUNT(*) AS c FROM concursos WHERE status='aberto' AND prova_data IS NOT NULL"
    ).fetchone()["c"]
    ultimo = db.execute(
        "SELECT finished_at FROM scrape_logs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "total": row["total"],
        "vagas": row["vagas"],
        "com_prova": provas,
        "ultima_coleta": ultimo["finished_at"] if ultimo else None,
    }
