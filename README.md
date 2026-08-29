# Despachante

Sistema web para consulta, envio e processamento de documentos de trânsito, com
uma base de atendimento por Kanban. O projeto está sendo preparado para atender
múltiplas empresas com dados isolados e, em etapas posteriores, receberá a
integração com WhatsApp (WAHA) e n8n.

## Funcionalidades disponíveis

- Autenticação, cadastro, perfil e recuperação de senha do Django.
- Envio de PDFs individual ou em lote.
- Processamento de documentos por Gemini, com opção de pipeline OpenAI e
  fallback para Gemini.
- Pesquisa por placa, histórico, fila de processamento e download protegido de
  documentos.
- Estrutura inicial de atendimento: contatos, serviços, conversas, mensagens,
  documentos recebidos e tarefas em Kanban.
- Multiempresa: empresas, vínculo usuário–empresa, empresa ativa por sessão e
  isolamento dos dados de negócio.

## Arquitetura

```text
Navegador
    │
    ▼
Django (webapp/)
    ├── documentos/   Upload, OCR, busca e histórico
    ├── atendimento/  Conversas e Kanban
    ├── empresas/     Tenant, vínculo de usuários e empresa ativa
    └── config/       Configurações e rotas
    │
    ├── PostgreSQL em produção (recomendado)
    └── SQLite apenas para desenvolvimento local

Workers Django
    ├── processar_documentos
    └── processar_conversas
```

O desenho futuro para atendimento é `WAHA → n8n → API interna Django`. Essa
integração ainda não foi implementada; veja `docs/IMPLEMENTACAO_MULTIEMPRESA.md`
para o estado atual e os próximos passos.

## Pré-requisitos

- Python 3.11 ou superior.
- Ambiente virtual Python.
- PostgreSQL para produção.
- Node.js/npm somente quando for necessário recompilar o CSS.

Dependências Python estão em `webapp/requirements.txt`.

## Execução local no Windows

Na raiz do projeto:

```powershell
cd webapp
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Abra `http://127.0.0.1:8000/`.

> O repositório já pode conter um ambiente virtual local. Nesse caso, use o
> ambiente existente em vez de criar outro.

## Configuração por ambiente

Crie as variáveis de ambiente conforme `deploy/despachante.env.example`. Nunca
versione chaves ou senhas.

Variáveis principais:

```dotenv
DJANGO_SECRET_KEY=gere-uma-chave-forte
DJANGO_DEBUG=1

# Produção: configure PostgreSQL.
POSTGRES_DB=
POSTGRES_USER=despachante
POSTGRES_PASSWORD=
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.5-flash
OPENAI_API_KEY=
OPENAI_MODEL=gpt-4o-mini
```

Sem `POSTGRES_DB`, o sistema usa `webapp/db.sqlite3`. SQLite é adequado para
desenvolvimento, mas não para a operação concorrente de múltiplas empresas e
workers em produção.

## Banco de dados e multiempresa

Após atualizar o código, sempre aplique as migrações:

```powershell
cd webapp
.\venv\Scripts\python.exe manage.py migrate
```

Cada usuário possui uma empresa ativa na sessão. Para usuários com mais de uma
empresa, a troca é feita por uma requisição `POST` autenticada a
`/empresas/selecionar/`, com `empresa_id` e, opcionalmente, `next`.

Os usuários existentes no momento da migração são vinculados à **Empresa
padrão**. Cadastros novos recebem uma empresa inicial própria, evitando que um
novo usuário tenha acesso a dados de uma empresa já existente.

## Comandos de operação

Na pasta `webapp`:

```powershell
# Verificar a configuração Django
.\venv\Scripts\python.exe manage.py check

# Executar todos os testes
.\venv\Scripts\python.exe manage.py test

# Processar um documento pendente e sair
.\venv\Scripts\python.exe manage.py processar_documentos --once

# Iniciar o worker de documentos
.\venv\Scripts\python.exe manage.py processar_documentos

# Processar uma conversa pendente e sair
.\venv\Scripts\python.exe manage.py processar_conversas --once
```

## Testes

A suíte usa um banco de testes temporário e mídia temporária; ela não altera o
banco de desenvolvimento.

```powershell
cd webapp
.\venv\Scripts\python.exe manage.py test --verbosity 1
```

Ela cobre, entre outros pontos:

- upload individual e em lote;
- validação de PDFs e deduplicação por pipeline;
- permissões de documento;
- processamento e fallback de OCR;
- cadastro e perfil;
- vínculos usuário–empresa;
- isolamento de tarefas do Kanban entre empresas.

## Produção

As instruções de implantação por systemd, Cloudflare Tunnel e CSS estão em
[`DEPLOY.md`](DEPLOY.md). Antes de publicar:

1. Configure PostgreSQL e execute backup.
2. Defina `DJANGO_SECRET_KEY` forte e `DJANGO_DEBUG=0`.
3. Configure HTTPS no proxy/Tunnel.
4. Execute `manage.py migrate`, `collectstatic --noinput`, `check` e `test`.
5. Valide o isolamento usando duas empresas de teste.

## Documentação adicional

- [`docs/IMPLEMENTACAO_MULTIEMPRESA.md`](docs/IMPLEMENTACAO_MULTIEMPRESA.md):
  decisões, alterações feitas, migrações e roteiro de testes multiempresa.
- [`docs/FLUXO_SAAS_ONBOARDING.md`](docs/FLUXO_SAAS_ONBOARDING.md):
  proposta de onboarding SaaS para despachantes e equipes.
- [`docs/FASES_4_8_IMPLEMENTACAO.md`](docs/FASES_4_8_IMPLEMENTACAO.md):
  API interna, WAHA, n8n, piloto e análise documental.
- [`docs/PILOTO_VALIDACAO.md`](docs/PILOTO_VALIDACAO.md):
  checklist de validação com empresa piloto.
- [`docs/REFINAMENTOS_PENDENTES.md`](docs/REFINAMENTOS_PENDENTES.md):
  backlog detalhado do que ainda não está pronto (para priorização).
- [`DEPLOY.md`](DEPLOY.md): implantação e operação do servidor.
- [`comparativo_ocr_placa.md`](comparativo_ocr_placa.md): material de OCR.
