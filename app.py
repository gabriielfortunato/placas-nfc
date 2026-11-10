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
    if not os.environ.get("DATABASE_URL"):
        return None
    if not getattr(app, "_schema_checked", False):
        try:
            init_db()
            app._schema_checked = True
        except Exception:
            app.logger.exception("Database initialization failed")


