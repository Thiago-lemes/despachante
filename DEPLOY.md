# Despachante Kingdom Tech

O Node nao e necessario em producao. O CSS compilado fica em
`webapp/documentos/static/documentos/app.css`.

## Variaveis de ambiente

```dotenv
DJANGO_SECRET_KEY=
DJANGO_DEBUG=0

# Se POSTGRES_DB estiver vazio, o app usa SQLite (webapp/db.sqlite3) automaticamente.
POSTGRES_DB=
POSTGRES_USER=despachante
POSTGRES_PASSWORD=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini

EMAIL_HOST=
EMAIL_PORT=587
EMAIL_HOST_USER=
EMAIL_HOST_PASSWORD=
EMAIL_USE_TLS=1
EMAIL_USE_SSL=0
DEFAULT_FROM_EMAIL=Kingdom Tech <nao-responda@kingdomtech.com.br>
```

Use apenas TLS ou SSL. O backend de e-mail permanece inativo quando `EMAIL_HOST`
nao esta definido.

## Atualizacao

```bash
cd /home/rodrigo/Desenvolvimentos/Clientes/Teixeira/Despachante/webapp
python3 manage.py migrate
python3 manage.py collectstatic --noinput
python3 manage.py check
python3 manage.py test
```

## Instalacao no servidor

O instalador cria o arquivo de ambiente quando necessario, executa as
migracoes e instala os dois servicos:

```bash
sudo ./deploy/install.sh
```

Para uma instalacao manual, crie `/etc/kingdom-tech/despachante.env` a partir de
`deploy/despachante.env.example` e gere uma chave aleatoria forte para
`DJANGO_SECRET_KEY`.

Instale `deploy/despachante-web.service` e
`deploy/despachante-worker.service` em `/etc/systemd/system/`, ajuste o usuario
e os caminhos quando necessario, e execute:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now despachante-web.service
sudo systemctl enable --now despachante-worker.service
```

O servico web escuta somente em `127.0.0.1:8001`, que e a origem configurada
para `despachante.kingdomtech.com.br` no Cloudflare Tunnel.

Com Postgres configurado (`POSTGRES_DB` definido), essa restricao de instancia unica
do worker deixa de existir — a trava vinha do bloqueio de escrita do SQLite. Nao ha
recomendacao ativa de rodar multiplas instancias hoje, so o registro de que a limitacao
tecnica anterior nao se aplica mais.

## Build do CSS

Em uma maquina com Node/npm:

```bash
npm install
npm run build:css
```

Tambem e possivel usar o binario standalone do Tailwind 3.4.17 com o arquivo
`tailwind.config.js`.
