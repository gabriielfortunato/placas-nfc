import os
import re
import uuid
from urllib.parse import urlparse

import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, request, redirect, send_file, session
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__, static_folder="static")
SECRET_CONFIGURED = bool(os.environ.get("FLASK_SECRET_KEY"))
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or "development-insecure-only"
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("RENDER") == "true",
    PERMANENT_SESSION_LIFETIME=60 * 60 * 8,
    MAX_CONTENT_LENGTH=1024 * 1024,
)

CATEGORIES = {"google", "instagram", "menu", "wifi", "whatsapp", "custom"}
SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def db():
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL não configurada no servidor.")
    return psycopg.connect(url, row_factory=dict_row, connect_timeout=10)


def init_db():
    """Cria apenas estruturas auxiliares; nunca apaga nem recria placas existentes."""
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS public.admin_users (
                id text PRIMARY KEY,
                password_hash text NOT NULL,
                created_at timestamptz NOT NULL DEFAULT now()
            )
        """)
        conn.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS admin_users_singleton_idx ON public.admin_users ((true))
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS scan_logs_scanned_at_idx
            ON public.scan_logs (scanned_at DESC)
        """)


@app.before_request
def ensure_schema():
    if request.endpoint == "health":
        return None
        return None
    if not getattr(app, "_schema_checked", False):
        try:
            init_db()
            app._schema_checked = True
        except Exception:
            app.logger.exception("Database initialization failed")


def json_error(message, status=400):
    return jsonify({"erro": message}), status


def csrf_valid():
    return bool(session.get("csrf_token")) and request.headers.get("X-CSRF-Token") == session.get("csrf_token")


def admin_required(fn):
    from functools import wraps
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not session.get("admin_id"):
            return json_error("Acesso administrativo necessário.", 401)
        if request.method not in ("GET", "HEAD", "OPTIONS") and not csrf_valid():
            return json_error("Token de segurança inválido. Atualize a página.", 403)
        return fn(*args, **kwargs)
    return wrapped


def valid_target(value):
    if not isinstance(value, str) or len(value) > 2048:
        return False
    parsed = urlparse(value.strip())
    try:
        port = parsed.port
        return parsed.scheme in ("http", "https") and bool(parsed.hostname) and (port is None or 1 <= port <= 65535) and not any(c.isspace() for c in value)
    except ValueError:
        return False


def plate_json(row):
    return {
        "id": row["id"], "clientName": row["client_name"], "slug": row["slug"],
        "category": row["category"], "targetUrl": row["target_url"],
        "active": row["active"], "scans": int(row["scans"] or 0),
        "location": row["location"] or "", "createdAt": row["created_at"].isoformat() if row["created_at"] else "",
        "accentColor": row["accent_color"], "heading": row["heading"] or "",
        "subtitle": row["subtitle"] or "",
    }


@app.get("/health")
def health():
    try:
        with db() as conn:
            conn.execute("SELECT 1")
        return jsonify({"status": "ok", "database": "connected"})
    except Exception:
        app.logger.exception("Health check database failure")
        return jsonify({"status": "degraded", "database": "unavailable"}), 503


@app.get("/api/auth/status")
def auth_status():
    if not SECRET_CONFIGURED:
        return json_error("Configuração incompleta: defina FLASK_SECRET_KEY no Render.", 503)
    try:
        with db() as conn:
            count = conn.execute("SELECT count(*) AS n FROM public.admin_users").fetchone()["n"]
        if "csrf_token" not in session:
            session["csrf_token"] = str(uuid.uuid4())
        return jsonify({
            "authenticated": bool(session.get("admin_id")),
            "setup_required": count == 0,
            "csrf_token": session["csrf_token"],
        })
    except Exception:
        app.logger.exception("Auth status failure")
        return json_error("Banco de dados indisponível. Verifique a configuração do servidor.", 503)


@app.post("/api/auth/setup")
def auth_setup():
    if not SECRET_CONFIGURED:
        return json_error("Configuração incompleta: defina FLASK_SECRET_KEY no Render.", 503)
    data = request.get_json(silent=True) or {}
    token = os.environ.get("ADMIN_SETUP_TOKEN", "")
    password = data.get("password", "")
    if not token or not data.get("setup_token") or not __import__("hmac").compare_digest(str(data["setup_token"]), token):
        return json_error("Código de configuração inválido.", 403)
    if not isinstance(password, str) or len(password) < 12 or len(password) > 256:
        return json_error("A senha deve ter entre 12 e 256 caracteres.", 400)
    try:
        with db() as conn:
            with conn.transaction():
                exists = conn.execute("SELECT id FROM public.admin_users LIMIT 1").fetchone()
                if exists:
                    return json_error("O administrador já foi configurado. Entre com sua senha.", 409)
                admin_id = str(uuid.uuid4())
                conn.execute("INSERT INTO public.admin_users (id, password_hash) VALUES (%s, %s)",
                             (admin_id, generate_password_hash(password)))
        session.clear()
        session["admin_id"] = admin_id
        session["csrf_token"] = str(uuid.uuid4())
        session.permanent = True
        return jsonify({"status": "configured"})
    except Exception:
        app.logger.exception("Admin setup failure")
        return json_error("Não foi possível configurar o administrador.", 503)


@app.post("/api/auth/login")
def auth_login():
    if not SECRET_CONFIGURED:
        return json_error("Configuração incompleta: defina FLASK_SECRET_KEY no Render.", 503)
    data = request.get_json(silent=True) or {}
    password = data.get("password", "")
    try:
        with db() as conn:
            user = conn.execute("SELECT id, password_hash FROM public.admin_users LIMIT 1").fetchone()
        if not user or not isinstance(password, str) or not check_password_hash(user["password_hash"], password):
            return json_error("Senha incorreta.", 401)
        session.clear()
        session["admin_id"] = user["id"]
        session["csrf_token"] = str(uuid.uuid4())
        session.permanent = True
        return jsonify({"status": "authenticated"})
    except Exception:
        app.logger.exception("Login failure")
        return json_error("Não foi possível autenticar no momento.", 503)


@app.post("/api/auth/logout")
@admin_required
def auth_logout():
    session.clear()
    return jsonify({"status": "logged_out"})


@app.get("/")
def index():
    return send_file(os.path.join(app.root_path, "index.html"))


@app.get("/api/placas")
@admin_required
def list_plates():
    with db() as conn:
        rows = conn.execute("""
            SELECT id, slug, client_name, category, target_url, active, scans,
                   location, created_at, accent_color, heading, subtitle
            FROM public.plates ORDER BY created_at DESC
        """).fetchall()
    return jsonify([plate_json(row) for row in rows])


@app.get("/api/logs")
@admin_required
def list_logs():
    with db() as conn:
        rows = conn.execute("""
            SELECT id, plate_id, plate_name, scan_type, scanned_at
            FROM public.scan_logs ORDER BY scanned_at DESC LIMIT 100
        """).fetchall()
    return jsonify([{
        "id": str(r["id"]), "plateId": r["plate_id"], "plateName": r["plate_name"],
        "type": r["scan_type"], "timestamp": r["scanned_at"].astimezone(timezone.utc).strftime("%d/%m/%Y %H:%M UTC")
    } for r in rows])


@app.post("/api/placas")
@admin_required
def create_plate():
    data = request.get_json(silent=True) or {}
    slug = str(data.get("slug", "")).strip().lower()
    name = str(data.get("clientName", "")).strip()
    category = data.get("category", "custom")
    target = str(data.get("targetUrl", "")).strip()
    if not isinstance(data.get("clientName"), str) or not name or len(name) > 160:
        return json_error("Informe um nome válido para o estabelecimento.")
    if not SLUG_RE.fullmatch(slug) or len(slug) > 80:
        return json_error("Identificador inválido. Use letras minúsculas, números e hífens.")
    if not isinstance(category, str) or category not in CATEGORIES:
        return json_error("Categoria inválida.")
    if not valid_target(target):
        return json_error("O destino deve ser uma URL completa iniciada por http:// ou https://.")
    if "active" in data and not isinstance(data["active"], bool):
        return json_error("O estado ativo deve ser verdadeiro ou falso.")
    plate_id = str(uuid.uuid4())
    try:
        with db() as conn:
            conn.execute("""
                INSERT INTO public.plates
                (id, slug, client_name, category, target_url, active, location, accent_color, heading, subtitle)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """, (plate_id, slug, name, category, target, bool(data.get("active", True)),
                  str(data.get("location", ""))[:200], str(data.get("accentColor", "#4285F4"))[:20],
                  str(data.get("heading", ""))[:160], str(data.get("subtitle", ""))[:300]))
        return jsonify({"status": "created", "id": plate_id, "slug": slug, "fixed_url": request.host_url.rstrip("/") + "/r/" + slug}), 201
    except psycopg.errors.UniqueViolation:
        return json_error("Este identificador já está reservado e não pode ser reutilizado.", 409)


def update_plate(slug):
    data = request.get_json(silent=True) or {}
    if "slug" in data and data["slug"] != slug:
        return json_error("O identificador de uma placa é permanente e não pode ser alterado.", 409)
    allowed = {
        "clientName": ("client_name", 160), "category": ("category", 30),
        "targetUrl": ("target_url", 2048), "location": ("location", 200),
        "active": ("active", None), "accentColor": ("accent_color", 20),
        "heading": ("heading", 160), "subtitle": ("subtitle", 300),
    }
    updates = []
    values = []
    for key, (column, limit) in allowed.items():
        if key not in data:
            continue
        value = data[key]
        if key == "clientName":
            value = str(value).strip()
            if not value or len(value) > 160:
                return json_error("Informe um nome válido para o estabelecimento.")
        if key == "targetUrl":
            value = str(value).strip()
            if not valid_target(value):
                return json_error("O destino deve ser uma URL http:// ou https:// válida.")
        elif key == "category" and (not isinstance(value, str) or value not in CATEGORIES):
            return json_error("Categoria inválida.")
        elif key == "active":
            if not isinstance(value, bool):
                return json_error("O estado ativo deve ser verdadeiro ou falso.")
        else:
            value = str(value).strip()
            if limit and len(value) > limit:
                return json_error("Um dos campos ultrapassa o limite permitido.")
        updates.append(column + " = %s")
        values.append(value)
    if not updates:
        return jsonify({"status": "unchanged"})
    updates.append("updated_at = now()")
    values.append(slug)
    with db() as conn:
        result = conn.execute("UPDATE public.plates SET " + ", ".join(updates) + " WHERE slug = %s RETURNING id", values).fetchone()
    if not result:
        return json_error("Placa não encontrada.", 404)
    return jsonify({"status": "updated", "id": result["id"], "slug": slug})


@app.route("/api/placas/<slug>", methods=["PUT", "PATCH", "DELETE"])
@admin_required
def manage_plate(slug):
    if request.method == "DELETE":
        # Compatibility safety: DELETE only deactivates. The slug is never deleted.
        return deactivate_plate(slug)
    return update_plate(slug)


def deactivate_plate(slug):
    with db() as conn:
        row = conn.execute("UPDATE public.plates SET active = false, updated_at = now() WHERE slug = %s RETURNING id", (slug,)).fetchone()
    if not row:
        return json_error("Placa não encontrada.", 404)
    return jsonify({"status": "archived", "slug": slug})


@app.get("/r/<slug>")
def redirect_plate(slug):
    source = request.args.get("source", "qr").lower()
    scan_type = "NFC" if source == "nfc" else "QR Code"
    with db() as conn:
        row = conn.execute("""
            SELECT id, client_name, target_url, active
            FROM public.plates WHERE slug = %s
        """, (slug,)).fetchone()
        if not row:
            return "<h1>Placa não encontrada.</h1>", 404
        if not row["active"]:
            return "<h1>Esta placa está temporariamente indisponível.</h1>", 410
        with conn.transaction():
            conn.execute("UPDATE public.plates SET scans = scans + 1, updated_at = now() WHERE id = %s", (row["id"],))
            conn.execute("""
                INSERT INTO public.scan_logs (plate_id, plate_name, scan_type)
                VALUES (%s,%s,%s)
            """, (row["id"], row["client_name"], scan_type))
    response = redirect(row["target_url"], code=302)
    response.headers["Cache-Control"] = "no-store"
    return response


@app.errorhandler(500)
def internal_error(_error):
    app.logger.exception("Unhandled server error")
    return jsonify({"erro": "Erro interno. Consulte os logs do servidor."}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "5000")))


@app.after_request
def security_headers(response):
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if request.path == "/" or request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response
