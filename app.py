from flask import Flask, request, redirect, jsonify, render_template_string
import sqlite3

app = Flask(__name__)

# ==========================================
# 1. BANCO DE DADOS (SQLite)
# ==========================================
def get_db():
    conn = sqlite3.connect('placas.db')
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS placas
                    (id INTEGER PRIMARY KEY AUTOINCREMENT,
                     cliente TEXT NOT NULL,
                     slug TEXT UNIQUE NOT NULL,
                     categoria TEXT DEFAULT 'google',
                     destino TEXT NOT NULL,
                     localizacao TEXT DEFAULT '',
                     ativo INTEGER DEFAULT 1,
                     acessos INTEGER DEFAULT 0,
                     criado_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
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

    <script type="text/babel">
        const { useState, useEffect, useRef } = React;

        function App() {
            const [placas, setPlacas] = useState([]);
            const [cliente, setCliente] = useState('');
            const [slug, setSlug] = useState('');
            const [destino, setDestino] = useState('');

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
                    body: JSON.stringify({ cliente, slug: slugLimpo, destino })
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
                        <span className="text-xs bg-emerald-500/10 text-emerald-400 px-3 py-1 rounded-full border border-emerald-500/20">Flask + SQLite Active</span>
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
                            <input
                                type="url"
                                placeholder="URL Destino (ex: instagram.com/loja)"
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

                    {/* Lista de Placas */}
                    <section className="grid grid-cols-1 md:grid-cols-3 gap-6">
                        {placas.map(p => (
                            <PlacaCard
                                key={p.id}
                                placa={p}
                                onEditar={handleEditarDestino}
                                onDeletar={handleDeletar}
                            />
                        ))}
                    </section>
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
                        width: 130,
                        height: 130,
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
                    <div className="bg-white p-3 rounded-xl flex justify-center border-2 border-slate-800" ref={qrRef}></div>

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

@app.route('/')
def index():
    return render_template_string(HTML_PAINEL)

@app.route('/api/placas', methods=['GET', 'POST'])
def api_placas():
    conn = get_db()
    if request.method == 'POST':
        data = request.json
        try:
            conn.execute(
                'INSERT INTO placas (cliente, slug, destino) VALUES (?, ?, ?)',
                (data['cliente'], data['slug'], data['destino'])
            )
            conn.commit()
            return jsonify({'status': 'sucesso'})
        except sqlite3.IntegrityError:
            return jsonify({'erro': 'Este identificador (slug) já está em uso por outra placa.'}), 400
        finally:
            conn.close()

    cur = conn.execute('SELECT * FROM placas ORDER BY id DESC')
    placas = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify(placas)

@app.route('/api/placas/<slug>', methods=['PUT', 'DELETE'])
def gerenciar_placa(slug):
    conn = get_db()
    if request.method == 'PUT':
        data = request.json
        conn.execute('UPDATE placas SET destino = ? WHERE slug = ?', (data['destino'], slug))
        conn.commit()
        conn.close()
        return jsonify({'status': 'atualizado'})

    if request.method == 'DELETE':
        conn.execute('DELETE FROM placas WHERE slug = ?', (slug,))
        conn.commit()
        conn.close()
        return jsonify({'status': 'deletado'})

# ROTA DE REDIRECIONAMENTO HTTP 302 (Usada nos QR Codes e Tags NFC)
@app.route('/r/<slug>')
def redirecionar(slug):
    conn = get_db()
    cur = conn.execute('SELECT destino FROM placas WHERE slug = ?', (slug,))
    row = cur.fetchone()

    if row:
        # Incrementa métrica de leitura
        conn.execute('UPDATE placas SET acessos = acessos + 1 WHERE slug = ?', (slug,))
        conn.commit()
        conn.close()
        
        destino = row['destino']
        if not destino.startswith('http://') and not destino.startswith('https://'):
            destino = 'https://' + destino
            
        return redirect(destino, code=302)

    conn.close()
    return "<h1>Placa não encontrada ou inativa no sistema.</h1>", 404

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)