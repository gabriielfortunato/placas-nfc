# PlacaGO

Aplicação Flask para administrar placas NFC/QR dinâmicas. O identificador público `/r/<slug>` é permanente: editar o destino não altera a URL impressa. Arquivar/desativar preserva o registro e impede que o slug seja reutilizado.

## Arquitetura

- Flask + Gunicorn no Render.
- PostgreSQL/Neon como fonte única dos dados.
- `index.html` é o painel completo; os cadastros e métricas não ficam em `localStorage`.
- `/r/<slug>` redireciona sem autenticação.
- `/r/<slug>?source=nfc` registra leituras NFC; a URL sem parâmetro registra QR Code. QR Codes já impressos continuam válidos.
- A simulação do painel é apenas visual e não altera métricas reais.

## Variáveis obrigatórias no Render

Configure em **Environment** (não no repositório):

1. `DATABASE_URL`: connection string do projeto Neon PlacaGO, mantida como segredo.
2. `FLASK_SECRET_KEY`: segredo aleatório longo e exclusivo para assinar sessões.
3. `ADMIN_SETUP_TOKEN`: código aleatório de uso único para criar a primeira senha de administrador.

Não publique esses valores em arquivos, commits, prints ou mensagens. Use geradores seguros de segredos. Depois da primeira configuração, o token de setup pode ser removido das variáveis do Render.

## Primeira configuração

1. Configure as três variáveis acima no Render e aguarde o deploy.
2. Acesse o painel. Na primeira visita, informe o `ADMIN_SETUP_TOKEN` e crie uma senha exclusiva com pelo menos 12 caracteres.
3. Após criar o administrador, o setup fica bloqueado pelo banco; remova `ADMIN_SETUP_TOKEN` do Render.
4. Entre com a senha de administrador.

## Persistência e segurança

- O backend não usa SQLite nem depende de disco local do Render.
- As tabelas existentes `public.plates` e `public.scan_logs` são utilizadas; a inicialização apenas cria a tabela auxiliar `admin_users` e um índice, sem apagar placas.
- A API administrativa exige sessão e token CSRF.
- Slugs são únicos e imutáveis. O endpoint DELETE legado apenas desativa a placa.
- Destinos aceitam somente URLs HTTP/HTTPS completas.
- Placas inativas retornam HTTP 410 e mantêm o slug reservado.

## Verificações antes de produção

- Definir as variáveis secretas no Render.
- Testar login, cadastro, edição de destino sem mudança de slug, arquivamento, ativação, leitura QR, leitura NFC, logs e backup.
- Confirmar deploy e smoke tests antes de apontar clientes para o serviço.
