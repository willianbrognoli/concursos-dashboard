"""Camada de banco de dados (SQLite) do Dashboard de Oportunidades."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

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
    "resumo", "url_inscricao", "status", "origem", "detalhado",
]


def upsert_concurso(db, data: dict) -> str:
    """Insere ou atualiza pelo url_fonte. Retorna 'created' ou 'updated'."""
    data = dict(data)
    if isinstance(data.get("materias"), (list, tuple)):
        data["materias"] = json.dumps(sorted(set(data["materias"])), ensure_ascii=False)
    existing = None
    if data.get("url_fonte"):
        existing = db.execute(
            "SELECT * FROM concursos WHERE url_fonte = ?", (data["url_fonte"],)
        ).fetchone()
    ts = now_iso()
    if existing:
        # não sobrescrever com vazio; preservar edições manuais de matérias se scraper não achou nada
        merged = {}
        for f in CONCURSO_FIELDS:
            new_val = data.get(f)
            if f == "materias":
                old = json.loads(existing["materias"] or "[]")
                new = json.loads(new_val) if new_val else []
                merged[f] = json.dumps(sorted(set(old) | set(new)), ensure_ascii=False)
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


def close_expired(db) -> int:
    """Marca como encerrado tudo cuja inscrição terminou antes de hoje."""
    today = datetime.now().date().isoformat()
    cur = db.execute(
        "UPDATE concursos SET status='encerrado', updated_at=? "
        "WHERE status='aberto' AND inscricao_fim IS NOT NULL AND inscricao_fim < ?",
        (now_iso(), today),
    )
    return cur.rowcount


def query_concursos(db, *, q=None, materias=None, uf=None, regiao=None,
                    inscricao_ate=None, prova_de=None, prova_ate=None,
                    status="aberto", order="inscricao_fim", limit=500):
    sql = "SELECT * FROM concursos WHERE 1=1"
    params: list = []
    if status and status != "todos":
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
    try:
        d["materias"] = json.loads(d.get("materias") or "[]")
    except Exception:
        d["materias"] = []
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
