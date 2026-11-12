import os
import sqlite3
import uuid
from datetime import timedelta
from urllib.parse import urlparse

from flask import Flask, request, redirect, jsonify, render_template_string, session, url_for
from werkzeug.security import check_password_hash

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
USE_POSTGRES = bool(DATABASE_URL)

if USE_POSTGRES:
    try:
        import psycopg
        from psycopg.rows import dict_row
        from psycopg.errors import UniqueViolation
    except ImportError as exc:
        raise RuntimeError("DATABASE_URL foi configurada, mas psycopg não está instalado.") from exc

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY") or os.urandom(32),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_SAMESITE="Lax",
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

LOGIN_HTML = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Entrar | PlacaGO</title>
    <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center p-5">
    <main class="w-full max-w-sm bg-slate-900 border border-slate-800 rounded-2xl p-7 shadow-2xl">
        <div class="text-center mb-7">
            <h1 class="text-3xl font-bold text-white">Placa<span class="text-sky-400">GO</span></h1>
            <p class="text-sm text-slate-400 mt-2">Acesso administrativo</p>
        </div>
        {% if erro %}
        <div class="mb-4 rounded-xl border border-red-500/30 bg-red-500/10 p-3 text-sm text-red-300">{{ erro }}</div>
        {% endif %}
        <form method="post" class="space-y-4">
            <div>
                <label for="username" class="block text-xs font-semibold text-slate-300 mb-2">Usuário</label>
                <input id="username" name="username" autocomplete="username" required
                    class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-sky-500">
            </div>
            <div>
                <label for="password" class="block text-xs font-semibold text-slate-300 mb-2">Senha</label>
                <input id="password" name="password" type="password" autocomplete="current-password" required
                    class="w-full rounded-xl border border-slate-700 bg-slate-950 px-4 py-3 text-sm text-white outline-none focus:border-sky-500">
            </div>
            <button type="submit" class="w-full rounded-xl bg-sky-600 hover:bg-sky-500 py-3 text-sm font-bold text-white">Entrar</button>
        </form>
    </main>
</body>
</html>
"""

@app.before_request
def exigir_login():
    if request.endpoint in ("login", "logout", "redirecionar", "static"):
        return None
    if not session.get("authenticated"):
        if request.path.startswith("/api/"):
            return jsonify({"erro": "Autenticação necessária."}), 401
        return redirect(url_for("login", next=request.path))
    return None


# ==========================================
# 1. BANCO DE DADOS
# ==========================================
def get_db():
    if USE_POSTGRES:
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, connect_timeout=10)
    conn = sqlite3.connect(os.environ.get("DATABASE_PATH", "placas.db"))
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    try:
        if USE_POSTGRES:
            # O Neon já possui o esquema public.plates. Esta consulta valida
            # a conexão e a estrutura sem alterar nem apagar dados.
            conn.execute("SELECT id, slug, client_name, category, target_url, active, scans, location, created_at FROM public.plates LIMIT 0")
        else:
            conn.execute("""CREATE TABLE IF NOT EXISTS placas
                (id INTEGER PRIMARY KEY AUTOINCREMENT,
                 cliente TEXT NOT NULL,
                 slug TEXT UNIQUE NOT NULL,
                 categoria TEXT DEFAULT 'google',
                 destino TEXT NOT NULL,
                 localizacao TEXT DEFAULT '',
                 ativo INTEGER DEFAULT 1,
                 acessos INTEGER DEFAULT 0,
                 criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""")
        conn.commit()
    finally:
        conn.close()


def get_placas():
    conn = get_db()
    try:
        if USE_POSTGRES:
            rows = conn.execute("""
                SELECT id, client_name AS cliente, slug,
                       category AS categoria, target_url AS destino,
                       location AS localizacao, active AS ativo,
                       scans AS acessos, created_at AS criado_em
                FROM public.plates ORDER BY created_at DESC
            """).fetchall()
        else:
            rows = conn.execute("SELECT * FROM placas ORDER BY id DESC").fetchall()
        return [dict(row) for row in rows]
    finally:
        conn.close()


def create_placa(data):
    conn = get_db()
    try:
        if USE_POSTGRES:
            conn.execute("""
                INSERT INTO public.plates
                    (id, client_name, slug, category, target_url, location, active, scans)
                VALUES (%s, %s, %s, %s, %s, %s, TRUE, 0)
            """, (str(uuid.uuid4()), data["cliente"], data["slug"],
                  data.get("categoria", "google"), data["destino"],
                  data.get("localizacao", "")))
        else:
            conn.execute(
                "INSERT INTO placas (cliente, slug, destino) VALUES (?, ?, ?)",
                (data["cliente"], data["slug"], data["destino"])
            )
        conn.commit()
        return True
    finally:
        conn.close()


def update_destino(slug, destino):
    conn = get_db()
    try:
        if USE_POSTGRES:
            conn.execute("""
                UPDATE public.plates
                SET target_url = %s, updated_at = NOW()
                WHERE slug = %s
            """, (destino, slug))
        else:
            conn.execute("UPDATE placas SET destino = ? WHERE slug = ?", (destino, slug))
        conn.commit()
    finally:
        conn.close()


def delete_placa(slug):
    conn = get_db()
    try:
        if USE_POSTGRES:
            conn.execute("DELETE FROM public.plates WHERE slug = %s", (slug,))
        else:
            conn.execute("DELETE FROM placas WHERE slug = ?", (slug,))
        conn.commit()
    finally:
        conn.close()


def get_destino(slug):
    conn = get_db()
    try:
        if USE_POSTGRES:
            row = conn.execute(
                "SELECT target_url AS destino FROM public.plates WHERE slug = %s AND active = TRUE",
                (slug,)
            ).fetchone()
            if row:
                conn.execute("UPDATE public.plates SET scans = scans + 1, updated_at = NOW() WHERE slug = %s", (slug,))
        else:
            row = conn.execute("SELECT destino FROM placas WHERE slug = ? AND ativo = 1", (slug,)).fetchone()
            if row:
                conn.execute("UPDATE placas SET acessos = acessos + 1 WHERE slug = ?", (slug,))
        conn.commit()
        return row["destino"] if row else None
    finally:
        conn.close()

# ==========================================
# 2. FRONT-END INTEGRADO (PlacaGO React)
# ==========================================
HTML_PAINEL = """
<!DOCTYPE html>
<html lang="pt-BR">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>PlacaGO - Hub de Gestão de Placas NFC & QR Code</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js" crossorigin></script>
    <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
    <script src="https://cdnjs.cloudflare.com/ajax/libs/qrcodejs/1.0.0/qrcode.min.js"></script>
</head>
<body class="bg-slate-950 text-slate-100 min-h-screen">
    <div id="root"></div>

    <style>
        .qr-preview img, .qr-preview canvas {
            width: 160px;
            height: 160px;
            image-rendering: pixelated;
        }
    </style>
    <script type="text/babel">
        const { useState, useEffect, useRef } = React;

        function App() {
            const [placas, setPlacas] = useState([]);
            const [cliente, setCliente] = useState('');
            const [slug, setSlug] = useState('');
            const [destino, setDestino] = useState('');
            const [categoria, setCategoria] = useState('google');
            const [abaAtiva, setAbaAtiva] = useState('instagram');

            const carregarPlacas = async () => {
                const res = await fetch('/api/placas');
                const data = await res.json();
                setPlacas(data);
            };

            useEffect(() => {
                carregarPlacas();
            }, []);

            const handleCadastrar = async (e) => {
                e.preventDefault();
                const slugLimpo = slug.trim().toLowerCase().replace(/\s+/g, '-');
                
                const res = await fetch('/api/placas', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({ cliente, slug: slugLimpo, destino, categoria })
                });

                if (res.ok) {
                    setCliente('');
                    setSlug('');
                    setDestino('');
                    carregarPlacas();
                } else {
                    const err = await res.json();
                    alert(err.erro || 'Erro ao salvar placa.');
                }
            };

            const handleEditarDestino = async (slugAtual, destinoAtual) => {
                const novoDestino = prompt(`Novo destino para a placa /r/${slugAtual}:`, destinoAtual);
                if (novoDestino && novoDestino !== destinoAtual) {
                    await fetch('/api/placas/' + slugAtual, {
                        method: 'PUT',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({ destino: novoDestino })
                    });
                    carregarPlacas();
                }
            };

            const handleDeletar = async (slugDeletar) => {
                if (confirm(`Excluir a placa /r/${slugDeletar}?`)) {
                    await fetch('/api/placas/' + slugDeletar, { method: 'DELETE' });
                    carregarPlacas();
                }
            };

            return (
                <div className="max-w-6xl mx-auto p-6 space-y-8">
                    <header className="flex justify-between items-center border-b border-slate-800 pb-4">
                        <h1 className="text-2xl font-bold text-white">Placa<span className="text-sky-400">GO</span> - QR Code Dinâmico Fixo</h1>
                        <div className="flex items-center gap-3">
                            <span className="text-xs bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-full border border-emerald-500/20">Acesso protegido</span>
                            <form method="post" action="/logout">
                                <button type="submit" className="text-xs bg-slate-800 hover:bg-slate-700 text-slate-300 px-3 py-2 rounded-lg border border-slate-700">Sair</button>
                            </form>
                        </div>
                    </header>

                    {/* Form de Cadastro */}
                    <section className="bg-slate-900 border border-slate-800 p-6 rounded-2xl shadow-xl">
                        <h2 className="text-lg font-bold text-white mb-4">Cadastrar Nova Placa Física</h2>
                        <form onSubmit={handleCadastrar} className="grid grid-cols-1 md:grid-cols-4 gap-4">
                            <input
                                type="text"
                                placeholder="Nome do Cliente"
                                required
                                value={cliente}
                                onChange={e => {
                                    setCliente(e.target.value);
                                    if(!slug) setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9]/g, '-'));
                                }}
                                className="bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-xs text-white"
                            />
                            <input
                                type="text"
                                placeholder="Slug Fixo (ex: barbearia-top)"
                                required
                                value={slug}
                                onChange={e => setSlug(e.target.value.toLowerCase().replace(/\s+/g, '-'))}
                                className="bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-xs text-white font-mono"
                            />
                            <select
                                value={categoria}
                                onChange={e => setCategoria(e.target.value)}
                                className="bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-xs text-white"
                            >
                                <option value="instagram">Instagram</option>
                                <option value="whatsapp">WhatsApp</option>
                                <option value="google">Google</option>
                            </select>
                            <input
                                type="url"
                                placeholder="URL Destino (ex: https://instagram.com/loja)"
                                required
                                value={destino}
                                onChange={e => setDestino(e.target.value)}
                                className="bg-slate-950 border border-slate-800 rounded-xl p-2.5 text-xs text-white font-mono"
                            />
                            <button type="submit" className="bg-sky-600 hover:bg-sky-500 font-bold text-xs p-2.5 rounded-xl transition">
                                Cadastrar Placa
                            </button>
                        </form>
                    </section>

                    {/* Abas de categorias: uma categoria por vez; tocar na aba ativa recolhe o conteúdo */}
                    {(() => {
                        const grupos = [
                            { key: 'instagram', title: 'Instagram' },
                            { key: 'whatsapp', title: 'WhatsApp' },
                            { key: 'google', title: 'Google' },
                            { key: 'outros', title: 'Outras placas' }
                        ];
                        const contar = (key) => placas.filter(p => key === 'outros'
                            ? !['instagram', 'whatsapp', 'google'].includes(String(p.categoria || '').toLowerCase())
                            : String(p.categoria || '').toLowerCase() === key).length;
                        return (
                            <section className="space-y-5">
                                <div className="flex flex-wrap gap-2 border-b border-slate-800 pb-3" role="tablist" aria-label="Categorias de placas">
                                    {grupos.map(grupo => (
                                        <button
                                            key={grupo.key}
                                            type="button"
                                            role="tab"
                                            aria-selected={abaAtiva === grupo.key}
                                            onClick={() => setAbaAtiva(abaAtiva === grupo.key ? null : grupo.key)}
                                            className={`inline-flex items-center gap-2 rounded-xl border px-4 py-2.5 text-xs font-bold transition ${abaAtiva === grupo.key ? 'bg-sky-600 border-sky-500 text-white' : 'bg-slate-900 border-slate-800 text-slate-300 hover:bg-slate-800'}`}
                                        >
                                            {grupo.title}
                                            <span className={`rounded-full px-2 py-0.5 text-[10px] ${abaAtiva === grupo.key ? 'bg-white/20 text-white' : 'bg-slate-800 text-slate-400'}`}>{contar(grupo.key)}</span>
                                        </button>
                                    ))}
                                </div>
                                {abaAtiva ? grupos.filter(grupo => grupo.key === abaAtiva).map(grupo => {
                                    const itens = placas
                                        .filter(p => grupo.key === 'outros'
                                            ? !['instagram', 'whatsapp', 'google'].includes(String(p.categoria || '').toLowerCase())
                                            : String(p.categoria || '').toLowerCase() === grupo.key)
                                        .sort((a, b) => {
                                            const numeroA = Number((a.slug.match(/(\\d+)$/) || [0, 0])[1]);
                                            const numeroB = Number((b.slug.match(/(\\d+)$/) || [0, 0])[1]);
                                            return numeroA - numeroB || a.slug.localeCompare(b.slug);
                                        });
                                    return (
                                        <div key={grupo.key} role="tabpanel" className="space-y-4">
                                            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
                                                <h2 className="text-lg font-bold text-white">{grupo.title}</h2>
                                                <span className="text-xs text-slate-400 bg-slate-800 px-3 py-1 rounded-full">{itens.length} placas</span>
                                            </div>
                                            {itens.length ? (
                                                <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                                    {itens.map(p => (
                                                        <PlacaCard key={p.id} placa={p} onEditar={handleEditarDestino} onDeletar={handleDeletar} />
                                                    ))}
                                                </div>
                                            ) : <p className="text-sm text-slate-500 py-6">Ainda não há placas nesta categoria.</p>}
                                        </div>
                                    );
                                }) : <p className="text-sm text-slate-500 py-6">Selecione uma categoria para visualizar as placas. Toque novamente na aba ativa para recolher.</p>}
                            </section>
                        );
                    })()}
                </div>
            );
        }

        function PlacaCard({ placa, onEditar, onDeletar }) {
            const qrRef = useRef(null);
            const urlFixaNfc = `${window.location.origin}/r/${placa.slug}`;

            useEffect(() => {
                if (qrRef.current) {
                    qrRef.current.innerHTML = '';
                    // O QR Code aponta SEMPRE para o link fixo do seu servidor Flask
                    new QRCode(qrRef.current, {
                        text: urlFixaNfc,
                        width: 512,
                        height: 512,
                        colorDark: "#000000",
                        colorLight: "#ffffff"
                    });
                }
            }, [placa.slug]);

            return (
                <div className="bg-slate-900 border border-slate-800 p-5 rounded-2xl flex flex-col justify-between space-y-4">
                    <div>
                        <div className="flex justify-between items-center">
                            <h3 className="font-bold text-white truncate">{placa.cliente}</h3>
                            <span className="text-[10px] bg-sky-500/10 text-sky-400 font-mono px-2 py-0.5 rounded border border-sky-500/20">
                                {placa.acessos} acessos
                            </span>
                        </div>
                        <p className="text-xs text-slate-400 mt-2 truncate">
                            Destino Atual: <a href={placa.destino} target="_blank" className="text-sky-400 underline">{placa.destino}</a>
                        </p>
                        <p className="text-[11px] text-slate-500 font-mono mt-1 truncate">
                            Link Fixo (QR/NFC): {urlFixaNfc}
                        </p>
                    </div>

                    {/* Container onde o QR Code imutável é renderizado */}
                    <div className="bg-white p-3 rounded-xl flex justify-center border-2 border-slate-800 qr-preview" ref={qrRef}></div>

                    <button
                        type="button"
                        onClick={() => {
                            const canvas = qrRef.current?.querySelector('canvas');
                            const img = qrRef.current?.querySelector('img');
                            const dataUrl = canvas ? canvas.toDataURL('image/png') : (img?.src || null);
                            if (!dataUrl) {
                                alert('Não foi possível gerar a imagem do QR Code. Tente novamente.');
                                return;
                            }
                            const link = document.createElement('a');
                            link.href = dataUrl;
                            link.download = `qrcode_${placa.slug}.png`;
                            document.body.appendChild(link);
                            link.click();
                            link.remove();
                        }}
                        className="w-full bg-sky-600 hover:bg-sky-500 text-white text-xs py-2.5 rounded-xl transition font-bold"
                    >
                        Baixar QR Code (PNG)
                    </button>

                    <div className="flex gap-2">
                        <button
                            onClick={() => onEditar(placa.slug, placa.destino)}
                            className="flex-1 bg-amber-500/10 hover:bg-amber-500/20 text-amber-400 border border-amber-500/20 text-xs py-2 rounded-xl transition font-semibold"
                        >
                            Alterar Destino
                        </button>
                        <button
                            onClick={() => onDeletar(placa.slug)}
                            className="bg-red-500/10 hover:bg-red-500/20 text-red-400 border border-red-500/20 text-xs px-3 py-2 rounded-xl transition font-semibold"
                        >
                            Excluir
                        </button>
                    </div>
                </div>
            );
        }

        ReactDOM.createRoot(document.getElementById('root')).render(<App />);
    </script>
</body>
</html>
"""

# ==========================================
# 3. ROTAS DA API E REDIRECIONADOR
# ==========================================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if session.get("authenticated"):
        return redirect(url_for("index"))

    erro = None
    if request.method == "POST":
        usuario_configurado = os.environ.get("ADMIN_USERNAME", "")
        hash_configurado = os.environ.get("ADMIN_PASSWORD_HASH", "")
        usuario = request.form.get("username", "")
        senha = request.form.get("password", "")

        if not usuario_configurado or not hash_configurado:
            return render_template_string(LOGIN_HTML, erro="Login administrativo não configurado."), 503

        if usuario == usuario_configurado and check_password_hash(hash_configurado, senha):
            session.clear()
            session["authenticated"] = True
            session.permanent = True
            return redirect(request.args.get("next") if request.args.get("next", "").startswith("/") and not request.args.get("next", "").startswith("//") else url_for("index"))

        erro = "Usuário ou senha incorretos."

    return render_template_string(LOGIN_HTML, erro=erro)


@app.route('/logout', methods=['POST'])
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route('/')
def index():
    return render_template_string(HTML_PAINEL)


@app.route('/api/placas', methods=['GET', 'POST'])
def api_placas():
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cliente = str(data.get('cliente', '')).strip()
        slug = str(data.get('slug', '')).strip().lower()
        destino = str(data.get('destino', '')).strip()
        categoria = str(data.get('categoria', 'google')).strip().lower()

        if categoria not in ('instagram', 'whatsapp', 'google'):
            return jsonify({'erro': 'Selecione uma categoria válida.'}), 400

        if not cliente or not slug or not destino:
            return jsonify({'erro': 'Preencha cliente, slug e URL de destino.'}), 400
        if not slug or any(ch not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for ch in slug):
            return jsonify({'erro': 'O slug deve conter apenas letras sem acento, números e hífens.'}), 400

        try:
            create_placa({'cliente': cliente, 'slug': slug, 'destino': destino, 'categoria': categoria})
            return jsonify({'status': 'sucesso'})
        except Exception as exc:
            if USE_POSTGRES and isinstance(exc, UniqueViolation):
                return jsonify({'erro': 'Este identificador (slug) já está em uso por outra placa.'}), 400
            if not USE_POSTGRES and isinstance(exc, sqlite3.IntegrityError):
                return jsonify({'erro': 'Este identificador (slug) já está em uso por outra placa.'}), 400
            app.logger.exception("Falha ao cadastrar placa")
            return jsonify({'erro': 'Não foi possível salvar a placa. Tente novamente.'}), 500

    try:
        return jsonify(get_placas())
    except Exception:
        app.logger.exception("Falha ao listar placas")
        return jsonify({'erro': 'Não foi possível carregar as placas.'}), 500


@app.route('/api/placas/<slug>', methods=['PUT', 'DELETE'])
def gerenciar_placa(slug):
    if request.method == 'PUT':
        data = request.get_json(silent=True) or {}
        destino = str(data.get('destino', '')).strip()
        if not destino:
            return jsonify({'erro': 'Informe uma URL de destino válida.'}), 400
        update_destino(slug, destino)
        return jsonify({'status': 'atualizado'})

    delete_placa(slug)
    return jsonify({'status': 'deletado'})


@app.route('/r/<slug>')
def redirecionar(slug):
    destino = get_destino(slug)
    if not destino:
        return "<h1>Placa não encontrada ou inativa no sistema.</h1>", 404

    if not destino.startswith(('http://', 'https://')):
        destino = 'https://' + destino

    return redirect(destino, code=302)


# Inicializa/verifica o banco também quando Gunicorn importa o módulo.
init_db()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)