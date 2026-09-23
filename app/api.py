"""API de sincronização para sistemas externos (/api/v1).

Modelo: o sistema parceiro faz uma carga inicial completa e depois pede só o que
mudou, usando um cursor. Nada se perde: criações e atualizações vêm em
/api/v1/concursos, exclusões em /api/v1/concursos/removidos.
Opcional: webhook "fino" avisa o parceiro quando há novidade (ele então sincroniza).

Variáveis de ambiente:
  API_KEYS        chaves aceitas, separadas por vírgula (sem chave = API desligada)
  WEBHOOK_URLS    URLs que recebem o aviso, separadas por vírgula (opcional)
  WEBHOOK_SECRET  segredo da assinatura HMAC-SHA256 do aviso (recomendado)
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import threading
import time
from datetime import datetime

import requests
from fastapi import APIRouter, Header, HTTPException, Query

from . import db as dbm

log = logging.getLogger("api")
router = APIRouter(prefix="/api/v1", tags=["sync"])

API_KEYS = {k.strip() for k in os.environ.get("API_KEYS", "").split(",") if k.strip()}
WEBHOOK_URLS = [u.strip() for u in os.environ.get("WEBHOOK_URLS", "").split(",") if u.strip()]
WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
MAX_LIMIT = 1000

# campos entregues (texto_base é o artigo bruto: só com ?texto=1)
CAMPOS = [
    "id", "url_fonte", "orgao", "uf", "regiao", "vagas", "vagas_texto", "salario", "salario_num",
    "cargos", "escolaridade", "inscricao_inicio", "inscricao_fim", "inscricao_texto", "prova_data",
    "prova_texto", "banca", "taxa", "materias", "etapas", "edital_status", "status_efetivo", "resumo",
    "url_inscricao", "status", "origem", "created_at", "updated_at",
]


# ------------------------------------------------------------ autenticação
def _auth(x_api_key: str | None, authorization: str | None):
    if not API_KEYS:
        raise HTTPException(503, "API desativada: defina API_KEYS no servidor.")
    key = x_api_key or ""
    if not key and authorization and authorization.lower().startswith("bearer "):
        key = authorization[7:].strip()
    if not any(hmac.compare_digest(key, k) for k in API_KEYS):
        raise HTTPException(401, "Chave de API inválida ou ausente (header X-API-Key).")


# ------------------------------------------------------------ cursor
def _enc(updated_at: str, rid: int) -> str:
    return base64.urlsafe_b64encode(f"{updated_at}|{rid}".encode()).decode().rstrip("=")


def _dec(cursor: str):
    try:
        raw = base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4)).decode()
        ts, rid = raw.rsplit("|", 1)
        return ts, int(rid)
    except Exception:
        raise HTTPException(400, "Cursor inválido.")


def _saida(row, com_texto: bool) -> dict:
    d = dbm.row_to_dict(row)
    out = {k: d.get(k) for k in CAMPOS}
    if com_texto:
        out["texto_base"] = d.get("texto_base")
    return out


# ------------------------------------------------------------ rotas
@router.get("/concursos")
def listar_concursos(cursor: str | None = None, limit: int = Query(200, ge=1, le=MAX_LIMIT),
                     texto: bool = False,
                     x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    """Criações e atualizações em ordem (updated_at, id).
    Sem cursor = carga completa desde o início. Guarde `next_cursor` e reenvie."""
    _auth(x_api_key, authorization)
    today = datetime.now().date().isoformat()
    sql = f"SELECT *, ({dbm._EFFECTIVE_STATUS_SQL}) AS status_efetivo FROM concursos"
    params: list = [today, today]
    if cursor:
        ts, rid = _dec(cursor)
        sql += " WHERE (updated_at > ? OR (updated_at = ? AND id > ?))"
        params += [ts, ts, rid]
    sql += " ORDER BY updated_at, id LIMIT ?"
    params.append(limit + 1)
    with dbm.get_db() as db:
        rows = db.execute(sql, params).fetchall()
    has_more = len(rows) > limit
    rows = rows[:limit]
    data = [_saida(r, texto) for r in rows]
    nxt = _enc(rows[-1]["updated_at"], rows[-1]["id"]) if rows else cursor
    return {"data": data, "count": len(data), "has_more": has_more, "next_cursor": nxt}


@router.get("/concursos/removidos")
def listar_removidos(desde: str | None = None, limit: int = Query(500, ge=1, le=MAX_LIMIT),
                     x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    """Concursos excluídos (antigos, duplicatas ou apagados no admin).
    Use `desde` = o `ate` da última resposta."""
    _auth(x_api_key, authorization)
    sql = "SELECT * FROM concursos_removidos"
    params: list = []
    if desde:
        sql += " WHERE removido_em > ?"
        params.append(desde)
    sql += " ORDER BY removido_em, id LIMIT ?"
    params.append(limit + 1)
    with dbm.get_db() as db:
        rows = [dict(r) for r in db.execute(sql, params).fetchall()]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"data": rows, "count": len(rows), "has_more": has_more,
            "ate": rows[-1]["removido_em"] if rows else desde}


@router.get("/concursos/{cid}")
def obter_concurso(cid: int, texto: bool = False,
                   x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    _auth(x_api_key, authorization)
    today = datetime.now().date().isoformat()
    with dbm.get_db() as db:
        r = db.execute(f"SELECT *, ({dbm._EFFECTIVE_STATUS_SQL}) AS status_efetivo FROM concursos WHERE id=?",
                       (today, today, cid)).fetchone()
        if not r:
            rem = db.execute("SELECT * FROM concursos_removidos WHERE id=?", (cid,)).fetchone()
            if rem:
                raise HTTPException(410, {"removido": dict(rem)})
            raise HTTPException(404, "Concurso não encontrado.")
    return _saida(r, texto)


@router.get("/noticias")
def listar_noticias(desde_id: int = 0, limit: int = Query(200, ge=1, le=MAX_LIMIT),
                    x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    """Notícias em ordem de id (não mudam depois de criadas). Use `desde_id` = `ultimo_id`."""
    _auth(x_api_key, authorization)
    with dbm.get_db() as db:
        rows = [dict(r) for r in db.execute(
            "SELECT * FROM noticias WHERE id > ? ORDER BY id LIMIT ?", (desde_id, limit + 1)).fetchall()]
    has_more = len(rows) > limit
    rows = rows[:limit]
    return {"data": rows, "count": len(rows), "has_more": has_more,
            "ultimo_id": rows[-1]["id"] if rows else desde_id}


@router.get("/status")
def status(x_api_key: str | None = Header(None), authorization: str | None = Header(None)):
    _auth(x_api_key, authorization)
    with dbm.get_db() as db:
        st = dbm.stats(db)
        st["total_geral"] = db.execute("SELECT COUNT(*) AS c FROM concursos").fetchone()["c"]
    return st


# ------------------------------------------------------------ webhook
def _assinar(corpo: bytes) -> str:
    return "sha256=" + hmac.new(WEBHOOK_SECRET.encode(), corpo, hashlib.sha256).hexdigest()


def _enviar(url: str, corpo: bytes):
    headers = {"Content-Type": "application/json", "User-Agent": "concursos-dashboard-webhook/1"}
    if WEBHOOK_SECRET:
        headers["X-Signature"] = _assinar(corpo)
    for tentativa in range(1, 4):
        try:
            r = requests.post(url, data=corpo, headers=headers, timeout=10)
            if r.status_code < 300:
                return
            log.warning("Webhook %s respondeu %s (tentativa %s)", url, r.status_code, tentativa)
        except Exception as e:
            log.warning("Webhook %s falhou (tentativa %s): %s", url, tentativa, e)
        time.sleep(5 * tentativa)


def notificar_webhooks(evento: str, resumo: dict | None = None):
    """Aviso fino e assíncrono: 'há novidade, sincronize'. Falha não afeta nada:
    a próxima sincronização pelo cursor recupera tudo."""
    if not WEBHOOK_URLS:
        return
    corpo = json.dumps({"evento": evento, "em": dbm.now_iso(), "resumo": resumo or {}},
                       ensure_ascii=False).encode()
    for url in WEBHOOK_URLS:
        threading.Thread(target=_enviar, args=(url, corpo), daemon=True).start()
