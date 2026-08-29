# Refinamentos pendentes — backlog para decisão

**Projeto:** Despachante  
**Versão:** 1.0  
**Data:** agosto/2026  
**Contexto:** fases 1–3 (multiempresa) e 4–8 (integração WAHA/n8n/API) implementadas em versão inicial. Este documento lista o que **ainda não está pronto** ou está **parcial**, com detalhes para priorização futura.

**Documentos relacionados:**

- [`FASES_4_8_IMPLEMENTACAO.md`](FASES_4_8_IMPLEMENTACAO.md) — o que já foi feito
- [`FLUXO_SAAS_ONBOARDING.md`](FLUXO_SAAS_ONBOARDING.md) — proposta de onboarding
- [`PILOTO_VALIDACAO.md`](PILOTO_VALIDACAO.md) — checklist do piloto
- [`IMPLEMENTACAO_MULTIEMPRESA.md`](IMPLEMENTACAO_MULTIEMPRESA.md) — isolamento por empresa

---

## Como usar este documento

Cada item traz:

| Campo | Significado |
| --- | --- |
| **Situação atual** | O que existe hoje no código |
| **Gap** | O que falta para considerar “pronto” |
| **Impacto** | Risco ou limitação se não fizer |
| **Esforço** | Estimativa grosseira (P/M/G) |
| **Quando priorizar** | Em que momento faz sentido |
| **Decisão necessária** | Pergunta para você ou o cliente responder |

**Legenda de esforço:** P = pequeno (1–3 dias), M = médio (1–2 semanas), G = grande (2+ semanas).

---

## Resumo executivo

| # | Refinamento | Esforço | Urgência sugerida |
| --- | --- | --- | --- |
| 1 | [Segurança de webhooks e API em produção](#1-segurança-de-webhooks-e-api-em-produção) | P | Alta — antes de produção |
| 2 | [Download automático de mídia WAHA](#2-download-automático-de-mídia-waha) | M | Alta — para fluxo de documentos |
| 3 | [UI de revisão documental](#3-ui-de-revisão-documental) | M | Média — após piloto |
| 4 | [Workflows n8n completos](#4-workflows-n8n-completos) | M | Alta — piloto depende disso |
| 5 | [Onboarding SaaS](#5-onboarding-saas-criar-despachante-e-equipe) | G | Média — antes de múltiplos clientes |
| 6 | [Seleção de empresa na interface](#6-seleção-de-empresa-na-interface) | P | Baixa — só se usuário multi-empresa |
| 7 | [Worker de conversas em produção](#7-worker-de-conversas-em-produção) | P | Média — se usar análise automática |
| 8 | [Triagem por IA real (substituir mock)](#8-triagem-por-ia-real-substituir-mock) | M | Média — pode ficar no n8n |
| 9 | [Armazenamento seguro de mídia](#9-armazenamento-seguro-de-mídia) | M | Média — produção com volume |
| 10 | [Unificação DocumentoRecebido ↔ Documento](#10-unificação-documentorecebido--documento) | M | Baixa — organização de dados |
| 11 | [Permissões por papel](#11-permissões-por-papel) | M | Média — equipes maiores |
| 12 | [Painel do operador da plataforma](#12-painel-do-operador-da-plataforma) | G | Baixa — muitos clientes |
| 13 | [Monitoramento e observabilidade](#13-monitoramento-e-observabilidade) | M | Média — produção |
| 14 | [Legado Meta WhatsApp](#14-legado-meta-whatsapp-cloud-api) | P | Baixa — desligar após WAHA |
| 15 | [Billing, planos e limites](#15-billing-planos-e-limites) | G | Baixa — modelo SaaS maduro |
| 16 | [Fila assíncrona (Celery/Redis)](#16-fila-assíncrona-celeryredis) | G | Baixa — alto volume |

---

## 1. Segurança de webhooks e API em produção

### Situação atual

- API interna autenticada por **um único token global** (`INTEGRACAO_API_TOKEN`).
- Escopo de empresa via header `X-Empresa-Id` (confiança no chamador).
- Webhook WAHA aceita requisições **sem verificar assinatura** por padrão (`WAHA_WEBHOOK_VERIFICAR_ASSINATURA=0`).
- Cada `WahaSessao` gera `webhook_secret`, mas a verificação só ocorre se a flag estiver ativa.

### Gap

- Qualquer pessoa com o token pode operar em nome de **qualquer empresa** (se souber o ID).
- Webhook público pode receber payloads falsos se a URL vazar.
- Sem rate limiting, rotação de token ou tokens por empresa/n8n.

### Impacto

- **Alto** em produção multi-tenant: vazamento de token = acesso a todos os tenants.
- Webhook sem HMAC = injeção de mensagens falsas.

### Esforço

**P** para ativar HMAC + checklist de produção. **M** para tokens por empresa e rate limit.

### Quando priorizar

**Antes de abrir WAHA em produção** com clientes reais.

### Opções

| Opção | Prós | Contras |
| --- | --- | --- |
| A) Só ativar HMAC (`WAHA_WEBHOOK_VERIFICAR_ASSINATURA=1`) | Rápido | Não resolve token global |
| B) Token por empresa + n8n usa token da empresa piloto | Isolamento melhor | Mais gestão de credenciais |
| C) mTLS ou IP allowlist no Cloudflare/Tunnel | Muito seguro | Mais complexo de operar |

### Decisão necessária

- [ ] HMAC obrigatório em produção?
- [ ] Um token global basta no piloto ou já nasce token por empresa?
- [ ] Quem rotaciona tokens quando vazarem?

---

## 2. Download automático de mídia WAHA

### Situação atual

- Webhook WAHA processa **mensagens de texto** (`body`, `caption`).
- `DocumentoRecebido` tem campo `arquivo`, mas o fluxo **não baixa** PDF/imagem do WhatsApp automaticamente.
- `waha_client.baixar_midia()` existe, mas **não é chamado** no pipeline.

### Gap

- Cliente envia CRLV em PDF no WhatsApp → sistema não anexa ao `DocumentoRecebido`.
- Análise documental (fase 8) exige upload manual ou via API com bytes.

### Impacto

- **Alto** para o fluxo “mensagem → documento → OCR → Kanban” prometido ao cliente.
- Piloto funciona só com texto; documentos exigem intervenção manual.

### Esforço

**M** — detectar tipo de mídia no webhook, baixar via WAHA, salvar em `DocumentoRecebido`, disparar análise.

### Quando priorizar

**Logo após** webhook de texto estável no piloto.

### Implementação sugerida (referência)

1. No webhook WAHA, identificar `type: document` / `image` com `mimetype: application/pdf`.
2. Chamar `baixar_midia(sessao, mediaUrl)`.
3. Associar ao `DocumentoExigido` pendente da conversa.
4. Transicionar conversa para `aguardando_analise`.
5. Disparar análise (worker ou API).

### Decisão necessária

- [ ] Aceitar só PDF ou também foto de documento?
- [ ] Tamanho máximo de arquivo no WhatsApp?
- [ ] Onde armazenar (disco local vs S3 — ver item 9)?

---

## 3. UI de revisão documental

### Situação atual

- Revisão humana só via:
  - **API:** `PATCH /api/v1/integracao/documentos-recebidos/<id>/revisao/`
  - **Django Admin:** editar `DocumentoRecebido` manualmente
- Kanban mostra tarefas, mas **não** exibe documentos pendentes de revisão nem resultado da IA.

### Gap

- Atendente não tem tela para aprovar/reprovar documento com contexto (placa, processo, PDF).
- Fluxo operacional depende de Admin ou Postman.

### Impacto

- **Médio** — piloto pode usar Admin; operação real fica ruim.

### Esforço

**M** — painel no Kanban ou modal no card da tarefa com preview + botões aprovar/reprovar.

### Quando priorizar

Após primeiro piloto com documentos chegando (mesmo que manualmente).

### Decisão necessária

- [ ] Revisão no Kanban ou tela separada “Fila de documentos”?
- [ ] Quem pode revisar: só admin ou qualquer atendente?
- [ ] Reprovação dispara mensagem automática ao cliente pedindo reenvio?

---

## 4. Workflows n8n completos

### Situação atual

- Existe **um** workflow de referência: `n8n/workflows/mensagem-recebida.json`.
- Triagem é **keyword simples** (“licen” → licenciamento).
- Não há workflows para:
  - solicitação de documentos por tipo
  - recebimento de mídia
  - confirmação de serviço
  - escalonamento para humano
  - retry/erro de API

### Gap

- Orquestração real ainda não está desenhada no n8n — só esboço.
- Worker Django (`processar_conversas`) ainda tem lógica de bot **paralela** ao n8n (pode duplicar comportamento).

### Impacto

- **Alto** para fase 7 (piloto end-to-end) — depende de fluxos n8n maduros.

### Esforço

**M** por fluxo principal; **G** para suite completa com tratamento de erros.

### Quando priorizar

**Durante o piloto** — iterar com a empresa piloto.

### Decisão necessária

- [ ] Toda triagem no n8n ou parte no Django?
- [ ] Desligar worker `processar_conversas` quando n8n assumir?
- [ ] Quem mantém workflows: dev ou operação?

---

## 5. Onboarding SaaS (criar despachante e equipe)

### Situação atual

- Cadastro público (`/cadastro/`) cria **empresa fantasma** por usuário (`Conta de joao #N`).
- Entrada em empresa existente = vínculo **manual** no Admin.
- Proposta documentada em [`FLUXO_SAAS_ONBOARDING.md`](FLUXO_SAAS_ONBOARDING.md), **não implementada**.

### Gap

- Não há “Criar minha despachante”.
- Não há convite de funcionário.
- Não há solicitação por CNPJ + aprovação.
- Não há tela “aguardando aprovação”.

### Impacto

- **Baixo** no piloto com 1 empresa criada no Admin.
- **Alto** ao abrir para várias despachantes em self-service.

### Esforço

**G** — modelos (`ConviteEmpresa`, `SolicitacaoAcesso`), telas, e-mails, remover signal de empresa automática.

### Quando priorizar

Antes do **segundo cliente** em produção ou abertura de cadastro público.

### Decisão necessária

- [ ] Self-service imediato ou provisionamento manual no início?
- [ ] Convite vs CNPJ — qual é o canal principal?
- [ ] CNPJ obrigatório na criação da empresa?

---

## 6. Seleção de empresa na interface

### Situação atual

- Troca de empresa só via `POST /empresas/selecionar/` (sem UI).
- Middleware define empresa ativa pela sessão.

### Gap

- Usuário vinculado a A e B não tem seletor no header.
- Depende de formulário manual ou Admin.

### Impacto

- **Baixo** se cada usuário pertence a uma empresa só.
- **Médio** para contadores/admins que atendem várias despachantes.

### Esforço

**P** — dropdown no `base.html` + formulário POST.

### Decisão necessária

- [ ] Haverá usuários multi-empresa na operação?
- [ ] Qual empresa vem selecionada por padrão?

---

## 7. Worker de conversas em produção

### Situação atual

- `manage.py processar_conversas` — triagem mock, coleta de docs, análise pendente.
- **Não há** unit systemd em produção (`deploy/despachante-conversas-worker.service` foi criado, mas não integrado ao `install.sh`).
- Só `processar_documentos` está no deploy atual.

### Gap

- Análise automática de `DocumentoRecebido` em `aguardando_analise` **não roda** em produção sem o worker.
- Bot legado no Django pode conflitar com n8n.

### Impacto

- **Médio** — se n8n + API assumirem tudo, worker pode ser opcional.
- **Alto** — se análise documental depender do worker.

### Esforço

**P** — adicionar ao `install.sh` e documentar no `DEPLOY.md`.

### Decisão necessária

- [ ] Manter worker Django ou migrar 100% para n8n + API?
- [ ] Se manter, incluir no deploy de produção?

---

## 8. Triagem por IA real (substituir mock)

### Situação atual

- `atendimento/services.py` → `chamar_ia_triagem()` usa **palavras-chave** (`licen`, `transfer`).
- Comentário no código: “depois integra com Gemini/OpenAI real”.
- Envio WhatsApp no worker antigo **só loga**, não envia (n8n/WAHA assumem envio na arquitetura nova).

### Gap

- Triagem inteligente não está no Django.
- Pode ser implementada no **n8n** (HTTP para Gemini) em vez do Django.

### Impacto

- **Médio** — piloto pode usar regras simples no n8n.

### Esforço

**M** no Django **ou** **M** no n8n (recomendado manter no n8n).

### Decisão necessária

- [ ] IA de triagem no n8n ou no Django?
- [ ] Qual modelo e custo aceitável por conversa?
- [ ] Desativar `processar_triagem` no Django?

---

## 9. Armazenamento seguro de mídia

### Situação atual

- Arquivos em `MEDIA_ROOT` local (`webapp/media/`).
- `Documento` (upload web) e `DocumentoRecebido` (atendimento) usam `FileField` no disco.
- Sem criptografia, sem URLs assinadas, sem expiração.

### Gap

- Backup e permissões de disco são responsabilidade do servidor.
- Em multi-worker, disco local não compartilha arquivos (precisa NFS ou object storage).
- Documentos de WhatsApp podem conter dados sensíveis (CPF, CRLV).

### Impacto

- **Baixo** no piloto single-server.
- **Alto** com múltiplos workers ou compliance (LGPD).

### Esforço

**M** — S3/MinIO + `django-storages` + URLs assinadas para download.

### Decisão necessária

- [ ] Manter disco local até quantos clientes?
- [ ] Política de retenção e exclusão de mídia?
- [ ] Backup de `media/` incluído no plano de DR?

---

## 10. Unificação DocumentoRecebido ↔ Documento

### Situação atual

- `documentos.Documento` — upload manual/web, pipeline OCR completo, histórico, lotes.
- `atendimento.DocumentoRecebido` — documentos do fluxo WhatsApp, análise separada.
- **Sem FK** entre os dois; deduplicação por hash só no módulo `documentos`.

### Gap

- Mesmo PDF pode existir duas vezes (upload + WhatsApp) sem vínculo.
- Relatórios e busca por placa não cruzam os dois mundos automaticamente.

### Impacto

- **Baixo** no piloto.
- **Médio** quando operação quiser visão única do veículo/cliente.

### Esforço

**M** — opcionalmente criar `Documento` a partir de `DocumentoRecebido` após aprovação, ou FK `documento_recebido.documento_id`.

### Decisão necessária

- [ ] Após aprovação, promover para `documentos.Documento`?
- [ ] Busca por placa unificada inclui atendimento?

---

## 11. Permissões por papel

### Situação atual

- Modelo `EmpresaUsuario.Papel`: `administrador`, `atendente`, `operador_documentos`.
- Isolamento por **empresa** funciona; papéis **não restringem** views/API ainda.
- Qualquer usuário da empresa acessa Kanban, upload, histórico.

### Gap

- Operador de documentos poderia ver Kanban; atendente poderia ver Admin se for staff.
- API interna não valida papel (só token).

### Impacto

- **Baixo** em equipe pequena e confiável.
- **Médio** em despachante com dezenas de funcionários.

### Esforço

**M** — decorators/mixins por papel nas views; opcional na API.

### Decisão necessária

- [ ] Quais telas cada papel acessa?
- [ ] Atendente pode aprovar documento ou só admin?

---

## 12. Painel do operador da plataforma

### Situação atual

- Superusuário Django Admin vê tudo.
- Sem dashboard de tenants, saúde WAHA, volume de mensagens, inadimplência.

### Gap

- Vocês (operador do SaaS) dependem do Admin genérico para gerenciar clientes.

### Impacto

- **Baixo** com poucos clientes.
- **Alto** com dezenas de despachantes.

### Esforço

**G** — app `plataforma` com métricas, ativar/desativar empresa, visão global.

### Decisão necessária

- [ ] Admin Django basta por quanto tempo?
- [ ] Quais métricas são obrigatórias no dia 1?

---

## 13. Monitoramento e observabilidade

### Situação atual

- Logs em arquivo/console (gunicorn, workers).
- `EventoAtendimento` guarda auditoria no banco, mas **sem UI** de consulta além do Admin.
- Sem alertas, métricas Prometheus, Sentry ou health agregado.

### Gap

- Difícil saber se WAHA caiu, n8n parou ou fila de análise travou.
- Debug de webhook duplicado ou mensagem perdida é manual.

### Impacto

- **Médio** em produção — tempo de resposta a incidentes alto.

### Esforço

**M** — healthcheck composto, alertas básicos (uptime, worker), dashboard de eventos.

### Decisão necessária

- [ ] Ferramenta de monitoramento (Uptime Kuma, Datadog, etc.)?
- [ ] Retenção de `EventoAtendimento` (30/90/365 dias)?

---

## 14. Legado Meta WhatsApp (Cloud API)

### Situação atual

- `atendimento/views.webhook_receive` ainda aceita webhook **Meta**.
- Todas as mensagens Meta vão para **Empresa padrão** (`_empresa_webhook_padrao()`).
- `enviar_mensagem_whatsapp` corrigido para `graph.facebook.com`, mas pouco usado.

### Gap

- Dois caminhos de entrada (Meta vs WAHA) podem confundir operação.
- Meta não mapeia por tenant.

### Impacto

- **Baixo** se WAHA substituir Meta completamente.

### Esforço

**P** — desativar rotas Meta ou redirecionar para integração com mapeamento explícito.

### Decisão necessária

- [ ] Data para desligar Meta?
- [ ] Manter compatibilidade temporária?

---

## 15. Billing, planos e limites

### Situação atual

- Não implementado.
- Sem trial, assinatura, limite de usuários, mensagens ou documentos por mês.

### Gap

- Impossível cobrar automaticamente ou suspender inadimplente.

### Impacto

- **Nenhum** no piloto gratuito/interno.
- **Alto** para SaaS comercial.

### Esforço

**G** — integração Stripe/Asaas, planos, webhooks de pagamento, flag `empresa.ativa` automática.

### Decisão necessária

- [ ] Modelo de preço (por usuário, por mensagem, flat)?
- [ ] Período de trial?

---

## 16. Fila assíncrona (Celery/Redis)

### Situação atual

- Workers via `management command` em loop (`processar_documentos`, `processar_conversas`).
- Análise OCR é **síncrona** dentro do worker (pode demorar minutos).
- Sem Redis, sem retry sofisticado, sem prioridade de fila.

### Gap

- Pico de documentos trava worker.
- Escalar horizontalmente exige cuidado com `select_for_update`.

### Impacto

- **Baixo** no volume atual.
- **Alto** com muitas despachantes e OCR simultâneo.

### Esforço

**G** — Celery + Redis, refatorar workers, deploy de broker.

### Decisão necessária

- [ ] Volume esperado de PDFs/dia no ano 1?
- [ ] Manter commands até qual escala?

---

## Matriz de priorização sugerida

Use esta ordem se não houver outra restrição de negócio:

```text
Antes do piloto em produção
  → 1 Segurança (HMAC + token)
  → 4 Workflows n8n (fluxo mínimo completo)
  → 2 Download de mídia WAHA

Durante o piloto
  → 3 UI revisão documental
  → 8 Triagem IA (no n8n)
  → 13 Monitoramento básico

Antes do 2º cliente
  → 5 Onboarding SaaS
  → 11 Permissões por papel
  → 7 Decisão worker vs n8n

Escala / comercialização
  → 9 Armazenamento S3
  → 12 Painel plataforma
  → 15 Billing
  → 16 Celery/Redis
```

---

## Registro de decisões

Preencha quando for priorizar:

| Item | Decisão | Data | Responsável |
| --- | --- | --- | --- |
| 1 Segurança | | | |
| 2 Mídia WAHA | | | |
| 3 UI revisão | | | |
| 4 n8n | | | |
| 5 Onboarding | | | |
| … | | | |

---

## Histórico

| Data | Alteração |
| --- | --- |
| ago/2026 | Documento inicial após implementação das fases 4–8 |
