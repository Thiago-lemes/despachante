# Fases 4 a 8 — implementação

Este documento descreve o que foi implementado para integração WhatsApp (WAHA → n8n → Django), análise documental e validação piloto.

## Visão geral

```text
WhatsApp (WAHA)
    → webhook Django (/api/v1/integracao/webhooks/waha/<sessao>/)
    → n8n (triagem, respostas, documentos)
    → API interna Django (/api/v1/integracao/...)
    → atendimento (conversas, tarefas, Kanban)
    → worker processar_conversas (análise documental — fase 8)
```

## Fase 4 — API interna autenticada

Novo app `webapp/integracao/` com:

| Componente | Função |
| --- | --- |
| `WahaSessao` | Mapeia sessão WAHA → empresa |
| `WebhookRecebido` | Deduplicação idempotente de webhooks |
| `EventoAtendimento` | Auditoria append-only |
| Autenticação | `Authorization: Bearer <INTEGRACAO_API_TOKEN>` + header `X-Empresa-Id` |

### Endpoints

| Método | Rota | Descrição |
| --- | --- | --- |
| GET | `/api/v1/integracao/health/` | Health check público |
| POST | `/api/v1/integracao/mensagens/` | Ingestão idempotente de mensagem |
| POST | `/api/v1/integracao/mensagens/enviar/` | Registra saída e envia via WAHA |
| GET/PATCH | `/api/v1/integracao/conversas/<id>/` | Consulta/atualiza estado |
| POST | `/api/v1/integracao/conversas/<id>/tarefas/` | Cria card no Kanban |
| POST | `/api/v1/integracao/documentos-recebidos/` | Registra documento exigido |
| POST | `/api/v1/integracao/documentos-recebidos/<id>/analisar/` | Dispara OCR/IA |
| PATCH | `/api/v1/integracao/documentos-recebidos/<id>/revisao/` | Revisão humana (aprovar/reprovar) |
| GET | `/api/v1/integracao/sessoes/<nome>/health/` | Status da sessão WAHA |
| POST | `/api/v1/integracao/webhooks/waha/<sessao>/` | Webhook WAHA com deduplicação |

### Variáveis de ambiente

```dotenv
INTEGRACAO_API_TOKEN=token-forte
WAHA_BASE_URL=http://localhost:3000
WAHA_API_KEY=
WAHA_WEBHOOK_SECRET=
WAHA_WEBHOOK_VERIFICAR_ASSINATURA=0
```

## Fase 5 — WAHA em homologação

1. Subir stack: `docker compose -f deploy/docker-compose.homolog.yml up -d`
2. No Admin Django, criar `WahaSessao` vinculada à empresa piloto (`nome_sessao=piloto`)
3. Configurar WAHA para apontar webhook para:
   `http://<host>:8000/api/v1/integracao/webhooks/waha/piloto/`
4. Escanear QR Code da sessão WAHA
5. Verificar: `GET /api/v1/integracao/sessoes/piloto/health/` (com token)

Arquivos: `deploy/docker-compose.homolog.yml`, `integracao/services/waha_client.py`

## Fase 6 — Fluxos n8n

Workflow de referência: `n8n/workflows/mensagem-recebida.json`

Variáveis no n8n:

- `DJANGO_BASE_URL` — ex.: `http://host.docker.internal:8000`
- `INTEGRACAO_API_TOKEN`
- `EMPRESA_ID` — ID da empresa piloto

Importar o JSON em `http://localhost:5678` e ativar o workflow.

## Fase 7 — Validação piloto

Ver checklist completo em [`PILOTO_VALIDACAO.md`](PILOTO_VALIDACAO.md).

Resumo do caminho feliz:

1. Mensagem WhatsApp → webhook WAHA → Django registra mensagem
2. n8n faz triagem → responde cliente → cria tarefa
3. Atendente vê card em `/atendimento/kanban/`
4. Documento PDF → análise → revisão humana via API

## Fase 8 — Análise documental com revisão humana

- `atendimento/services/analise_documento.py` reutiliza pipeline Gemini/OpenAI
- Campos novos em `DocumentoRecebido`: `analisado_em`, `erro_analise`, `revisado_por`, `revisado_em`
- Worker `processar_conversas` processa estado `aguardando_analise`
- Revisão: `PATCH /api/v1/integracao/documentos-recebidos/<id>/revisao/` com `{"aprovado": true}`

## Comandos

```powershell
cd webapp
.\venv\Scripts\python.exe manage.py migrate
.\venv\Scripts\python.exe manage.py test integracao --verbosity 1
.\venv\Scripts\python.exe manage.py processar_conversas --once
```

## Próximos refinamentos

Ver backlog detalhado em [`REFINAMENTOS_PENDENTES.md`](REFINAMENTOS_PENDENTES.md) — inclui impacto, esforço, opções e decisões a tomar.

Resumo:

- UI de revisão documental no Kanban (hoje só via API/Admin)
- Onboarding SaaS (`FLUXO_SAAS_ONBOARDING.md`)
- Assinatura HMAC obrigatória em produção (`WAHA_WEBHOOK_VERIFICAR_ASSINATURA=1`)
- Download de mídia WAHA → `DocumentoRecebido.arquivo` automático
