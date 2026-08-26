"""Dashboard de Oportunidades — concursos públicos abertos.

FastAPI + SQLite + scraper agendado (PCI Concursos).
"""
import json
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from . import auth, db as dbm, scraper
from .materias import ETAPAS, MATERIAS_PATTERNS, REGIOES, STATUS_EDITAL, UFS, regiao_da_uf

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("app")

BASE_DIR = Path(__file__).parent
ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "").strip().lower()
OPEN_REGISTRATION = os.environ.get("OPEN_REGISTRATION", "true").lower() in ("1", "true", "yes")
SCRAPE_HOUR = os.environ.get("SCRAPE_HOUR", "6")
SCRAPE_ON_START = os.environ.get("SCRAPE_ON_START", "true").lower() in ("1", "true", "yes")
TZ = os.environ.get("TZ", "America/Sao_Paulo")

app = FastAPI(title="Dashboard de Oportunidades", docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

_scrape_lock = threading.Lock()
_scrape_running = {"flag": False}


# ------------------------------------------------------------- helpers
def current_user(request: Request):
    uid = auth.read_session_token(request.cookies.get(auth.COOKIE_NAME))
    if not uid:
        return None
    with dbm.get_db() as db:
        user = dbm.get_user(db, uid)
    if user and user["is_active"]:
        return dict(user)
    return None


def require_login(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    return user, None


def client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def run_scrape_bg(trigger: str = "agendado"):
    if _scrape_running["flag"]:
        log.info("Coleta já em andamento; ignorando disparo (%s).", trigger)
        return
    def _job():
        with _scrape_lock:
            _scrape_running["flag"] = True
            try:
                scraper.run_scrape()
            except Exception:
                log.exception("Coleta falhou")
            finally:
                _scrape_running["flag"] = False
    threading.Thread(target=_job, daemon=True, name=f"scrape-{trigger}").start()


# ------------------------------------------------------------- startup
@app.on_event("startup")
def startup():
    dbm.init_db()
    scheduler = BackgroundScheduler(timezone=TZ)
    scheduler.add_job(run_scrape_bg, CronTrigger(hour=SCRAPE_HOUR, minute=15),
                      id="scrape-diario", kwargs={"trigger": "cron"})
    scheduler.start()
    app.state.scheduler = scheduler
    if SCRAPE_ON_START:
        with dbm.get_db() as db:
            n = db.execute("SELECT COUNT(*) AS c FROM concursos").fetchone()["c"]
            last = db.execute(
                "SELECT finished_at FROM scrape_logs WHERE finished_at IS NOT NULL ORDER BY id DESC LIMIT 1"
            ).fetchone()
        stale = True
        if last and last["finished_at"]:
            try:
                dtl = datetime.fromisoformat(last["finished_at"])
                stale = (datetime.now(dtl.tzinfo) - dtl).total_seconds() > 20 * 3600
            except Exception:
                pass
        if n == 0 or stale:
            log.info("Base vazia/defasada — disparando coleta inicial.")
            run_scrape_bg("startup")


# ---------------------------------------------------------------- auth
@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    if current_user(request):
        return RedirectResponse("/", status_code=302)
    return templates.TemplateResponse("login.html", {"request": request, "error": None,
                                                     "open_registration": OPEN_REGISTRATION})


@app.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...)):
    ip, ua = client_ip(request), request.headers.get("user-agent", "")
    with dbm.get_db() as db:
        user = dbm.get_user_by_email(db, email)
        ok = bool(user) and user["is_active"] and auth.verify_password(password, user["password_hash"])
        dbm.log_access(db, user_id=user["id"] if user else None, email=email,
                       success=ok, kind="login", ip=ip, user_agent=ua)
    if not ok:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "E-mail ou senha inválidos.",
             "open_registration": OPEN_REGISTRATION},
            status_code=401)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, auth.create_session_token(user["id"]),
                    max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    if not OPEN_REGISTRATION:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse("register.html", {"request": request, "error": None})


@app.post("/register")
def register(request: Request, name: str = Form(...), email: str = Form(...),
             password: str = Form(...), password2: str = Form(...)):
    if not OPEN_REGISTRATION:
        return RedirectResponse("/login", status_code=302)
    error = None
    if len(password) < 8:
        error = "A senha precisa ter pelo menos 8 caracteres."
    elif password != password2:
        error = "As senhas não conferem."
    elif "@" not in email or "." not in email:
        error = "E-mail inválido."
    elif not name.strip():
        error = "Informe seu nome."
    if error:
        return templates.TemplateResponse("register.html", {"request": request, "error": error},
                                          status_code=400)
    ip, ua = client_ip(request), request.headers.get("user-agent", "")
    with dbm.get_db() as db:
        if dbm.get_user_by_email(db, email):
            return templates.TemplateResponse(
                "register.html", {"request": request, "error": "Este e-mail já está cadastrado."},
                status_code=400)
        first = dbm.count_users(db) == 0
        is_admin = first or (ADMIN_EMAIL and email.strip().lower() == ADMIN_EMAIL)
        uid = dbm.create_user(db, name, email, auth.hash_password(password), is_admin=is_admin)
        dbm.log_access(db, user_id=uid, email=email, success=True, kind="register", ip=ip, user_agent=ua)
    resp = RedirectResponse("/", status_code=302)
    resp.set_cookie(auth.COOKIE_NAME, auth.create_session_token(uid),
                    max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax")
    return resp


@app.get("/logout")
def logout(request: Request):
    user = current_user(request)
    if user:
        with dbm.get_db() as db:
            dbm.log_access(db, user_id=user["id"], email=user["email"], success=True,
                           kind="logout", ip=client_ip(request),
                           user_agent=request.headers.get("user-agent", ""))
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie(auth.COOKIE_NAME)
    return resp


# ----------------------------------------------------------- dashboard
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    user, redir = require_login(request)
    if redir:
        return redir
    with dbm.get_db() as db:
        materias = dbm.all_materias(db)
        st = dbm.stats(db)
        noticias = dbm.latest_noticias(db, limit=12)
    # lista completa do dicionário + o que existir na base (edições manuais)
    materias = sorted(set(materias) | set(MATERIAS_PATTERNS.keys()))
    return templates.TemplateResponse("dashboard.html", {
        "request": request, "user": user, "materias": materias, "etapas": ETAPAS,
        "status_edital": STATUS_EDITAL,
        "ufs": {k: v[0] for k, v in UFS.items()}, "regioes": REGIOES, "stats": st,
        "noticias": noticias,
    })


@app.get("/api/concursos")
def api_concursos(request: Request, q: str = None, materia: str = None, etapa: str = None,
                  uf: str = None, regiao: str = None, inscricao_ate: str = None,
                  prova_de: str = None, prova_ate: str = None, status: str = "aberto",
                  fase: str = None, edital_status: str = None, order: str = "inscricao_fim"):
    user = current_user(request)
    if not user:
        return JSONResponse({"error": "não autenticado"}, status_code=401)
    materias = [m for m in (materia.split("|") if materia else []) if m]
    etapas = [e for e in (etapa.split("|") if etapa else []) if e]
    with dbm.get_db() as db:
        rows = dbm.query_concursos(db, q=q, materias=materias, etapas=etapas, uf=uf or None,
                                   regiao=regiao or None, inscricao_ate=inscricao_ate or None,
                                   prova_de=prova_de or None, prova_ate=prova_ate or None,
                                   status=status, fase=fase or None,
                                   edital_status=edital_status or None, order=order)
        st = dbm.stats(db)
    return {"concursos": rows, "stats": st, "count": len(rows)}


# --------------------------------------------------------------- admin
def require_admin(request: Request):
    user = current_user(request)
    if not user:
        return None, RedirectResponse("/login", status_code=302)
    if not user["is_admin"]:
        return None, RedirectResponse("/", status_code=302)
    return user, None


@app.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    user, redir = require_admin(request)
    if redir:
        return redir
    with dbm.get_db() as db:
        users = [dict(r) for r in db.execute("SELECT * FROM users ORDER BY created_at DESC").fetchall()]
        logs = [dict(r) for r in db.execute(
            "SELECT l.*, u.name AS user_name FROM login_logs l LEFT JOIN users u ON u.id=l.user_id "
            "ORDER BY l.id DESC LIMIT 200").fetchall()]
        scrapes = [dict(r) for r in db.execute(
            "SELECT * FROM scrape_logs ORDER BY id DESC LIMIT 30").fetchall()]
        manuais = [dbm.row_to_dict(r) for r in db.execute(
            "SELECT * FROM concursos WHERE origem='manual' ORDER BY updated_at DESC LIMIT 100").fetchall()]
        st = dbm.stats(db)
    return templates.TemplateResponse("admin.html", {
        "request": request, "user": user, "users": users, "logs": logs,
        "scrapes": scrapes, "manuais": manuais, "stats": st,
        "scrape_running": _scrape_running["flag"],
        "materias_all": sorted(MATERIAS_PATTERNS.keys()),
        "etapas_all": ETAPAS,
        "status_edital_all": STATUS_EDITAL,
        "ufs": {k: v[0] for k, v in UFS.items()},
        "open_registration": OPEN_REGISTRATION,
    })


@app.post("/admin/scrape")
def admin_scrape(request: Request):
    user, redir = require_admin(request)
    if redir:
        return redir
    run_scrape_bg("manual")
    return RedirectResponse("/admin?msg=coleta+iniciada", status_code=302)


@app.post("/admin/user/{uid}/toggle-admin")
def toggle_admin(uid: int, request: Request):
    user, redir = require_admin(request)
    if redir:
        return redir
    if uid == user["id"]:
        return RedirectResponse("/admin", status_code=302)
    with dbm.get_db() as db:
        db.execute("UPDATE users SET is_admin = 1 - is_admin WHERE id=?", (uid,))
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/user/{uid}/toggle-active")
def toggle_active(uid: int, request: Request):
    user, redir = require_admin(request)
    if redir:
        return redir
    if uid == user["id"]:
        return RedirectResponse("/admin", status_code=302)
    with dbm.get_db() as db:
        db.execute("UPDATE users SET is_active = 1 - is_active WHERE id=?", (uid,))
    return RedirectResponse("/admin", status_code=302)


@app.post("/admin/concurso")
def admin_add_concurso(request: Request, orgao: str = Form(...), uf: str = Form(""),
                       vagas: str = Form(""), salario: str = Form(""), cargos: str = Form(""),
                       inscricao_fim: str = Form(""), prova_data: str = Form(""),
                       banca: str = Form(""), url_inscricao: str = Form(""),
                       materias: str = Form(""), etapas: str = Form(""),
                       edital_status: str = Form(""), resumo: str = Form("")):
    user, redir = require_admin(request)
    if redir:
        return redir
    mats = [m.strip() for m in materias.split(",") if m.strip()]
    etps = [e.strip() for e in etapas.split(",") if e.strip()]
    data = {
        "orgao": orgao.strip(), "uf": uf.upper() or None, "regiao": regiao_da_uf(uf),
        "vagas": int(vagas) if vagas.strip().isdigit() else None,
        "salario": salario.strip() or None, "cargos": cargos.strip() or None,
        "inscricao_fim": inscricao_fim or None, "prova_data": prova_data or None,
        "banca": banca.strip() or None, "url_inscricao": url_inscricao.strip() or None,
        "materias": mats, "etapas": etps, "edital_status": edital_status or None,
        "resumo": resumo.strip() or None,
        "origem": "manual", "detalhado": 1, "status": "aberto",
        "url_fonte": f"manual:{orgao.strip()}:{inscricao_fim or ''}",
    }
    with dbm.get_db() as db:
        dbm.upsert_concurso(db, data)
    return RedirectResponse("/admin?msg=concurso+salvo#concursos", status_code=302)


@app.post("/admin/concurso/{cid}/delete")
def admin_del_concurso(cid: int, request: Request):
    user, redir = require_admin(request)
    if redir:
        return redir
    with dbm.get_db() as db:
        db.execute("DELETE FROM concursos WHERE id=?", (cid,))
    return RedirectResponse("/admin#concursos", status_code=302)


@app.get("/health")
def health():
    return {"ok": True}
