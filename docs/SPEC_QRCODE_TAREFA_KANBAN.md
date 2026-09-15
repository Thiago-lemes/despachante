# Spec — QR Code no cadastro, Tarefa automática no Kanban, sidebar no Kanban e limpeza de código morto

**Projeto:** Despachante
**Data:** setembro/2026
**Branch de referência:** `feature/chat-whatsaap-poc`

**Documentos relacionados:**
- [`REFINAMENTOS_PENDENTES.md`](REFINAMENTOS_PENDENTES.md) — backlog geral, itens 1 e 4 se cruzam com esta spec (segurança de webhook e workflows n8n)
- [`FASES_4_8_IMPLEMENTACAO.md`](FASES_4_8_IMPLEMENTACAO.md) — o que já foi implementado da integração WAHA/n8n

Esta spec cobre apenas os 4 pedidos abertos nesta rodada. Cada um vira uma frente de trabalho com escopo, decisões necessárias e critério de pronto.

---

## Estado atual (resumo do levantamento)

- **QR Code:** já existe todo o encanamento (`WahaSessao`, `WahaService`, view `gerar_qr_code_empresa` em `webapp/integracao/views.py`), mas ele é disparado **na view de cadastro** (`usuario/views.py:cadastro_despachante`) via `redirect()` para uma view que devolve **JSON puro**, não uma página. O usuário recém-cadastrado cai numa tela em branco com JSON. O modal de QR Code + polling que deveria consumir esse endpoint foi começado dentro de `documentos/base.html` mas **ainda não está commitado** (aparece como `modified` no `git status`).
- **Tarefa automática no Kanban a partir da conversa:** existem **3 implementações concorrentes** do webhook que recebe mensagens do WhatsApp:
  1. `integracao/views.py` (`webhook_waha`) — não cria Tarefa.
  2. `integracao/api/views.py` (`webhook_waha`, sobrescreve a primeira definição do módulo) — cria Tarefa, mas com **empresa hard-coded (`id=3`)**.
  3. `atendimento/views.py` (`webhook_receive`) — cria Tarefa, resolve empresa corretamente via `WahaSessao`, é a versão mais correta para multiempresa.
  4. Existe ainda um 4º caminho "oficial" via n8n → `POST /conversas/<id>/tarefas/` → `services/conversas.py:criar_tarefa`, que é o único ponto pensado para official multiempresa + auditoria, mas está desconectado do webhook direto.
- **Sidebar no Kanban:** `atendimento/templates/atendimento/kanban.html` é um HTML standalone (`<!DOCTYPE html>` próprio), não estende `documentos/base.html` — não tem sidebar, header, seletor de empresa nem logout.
- **Código morto:** função duplicada em `integracao/api/views.py`, rotas duplicadas em `config/urls.py`, módulo `atendimento/services.py` vs pacote `atendimento/services/` colidindo, webhook legado Meta/Cloud API sem uso, `print()`s de debug em produção, bug no drag-and-drop do Kanban (JSON vs `request.POST`), scripts de POC de OCR na raiz do repo.

---

## Frente 1 — QR Code no fluxo de cadastro

**Objetivo:** ao criar a conta, o sistema dispara a criação da sessão WAHA e o usuário vê, na própria tela (sem sair para uma URL de API), um QR Code para escanear; quando a sessão WAHA reportar `WORKING`, a UI libera/mostra "dispositivo vinculado".

### Tarefas

1. **Corrigir o redirect pós-cadastro** (`usuario/views.py:cadastro_despachante`): não redirecionar para `gerar_qr_code_empresa` (view JSON). Redirecionar para uma página HTML normal (ex.: `busca` ou uma tela de "conta criada") que já carregue o modal/componente de vínculo do WhatsApp.
2. **Finalizar e commitar o modal de QR Code** em `documentos/base.html` (hoje é trabalho não commitado): botão "Vincular WhatsApp" abre modal, chama `gerar_qr_code_empresa` via `fetch`, exibe a imagem do QR (`dados_qr` retornado pelo WAHA), com polling em intervalo curto (ex. 3s) enquanto o status não for `WORKING`.
3. Ajustar a view `gerar_qr_code_empresa` (`integracao/views.py`) para deixar claro o contrato JSON de resposta: `{status: "aguardando" | "pronto" | "conectado", qr_base64?: str}` — hoje mistura HTTP 202 com corpo, revisar consistência.
4. **Trigger automático no cadastro:** decidir se a sessão WAHA + QR Code devem ser criados automaticamente assim que a `Empresa` é criada (hoje já ocorre isso na view de cadastro, linha a linha) ou se deve ser uma ação explícita do usuário ("Vincular WhatsApp" como botão, sem nada automático no submit do form). Ver decisão (D1) abaixo.
5. Corrigir a URL de webhook hard-coded para produção em `gerar_qr_code_empresa` (`https://despachante.kingdomtech.com.br/...`) — usar `settings.SITE_URL`/env, para funcionar em homologação/dev também.
6. **Botão "vincular dispositivo" só habilita quando o QR estiver pronto** — hoje o requisito do usuário já bate com o desenho do modal (botão desabilitado até `dados_qr` chegar, texto muda para "Conectado" quando status vira `WORKING`).

### Decisão necessária

- **(D1)** Disparo automático da sessão WAHA no submit do cadastro, ou botão manual "Vincular WhatsApp" que só existe depois do login (mais simples, evita sessão órfã se o usuário nunca escanear o QR)? **Recomendação:** manual, os únicos custos são cliques a mais e evita `WahaSessao` órfãs.
- **(D2)** O que fazer se o usuário fechar o modal sem escanear? Deve reaparecer a cada login até conectar, ou ficar disponível sob demanda no menu (já existe "Vincular WhatsApp" no sidebar)?

### Critério de pronto

- Cadastro → login automático → tela normal do sistema (sidebar visível), sem tela de JSON cru.
- Botão "Vincular WhatsApp" no sidebar abre modal, mostra QR real do WAHA, atualiza sozinho quando conectar.
- Nenhuma URL hard-coded de produção no código.

---

## Frente 2 — Criar Tarefa no Kanban ao final da conversa

**Objetivo:** quando o cliente termina de conversar e pede o que quer (serviço identificado), o sistema cria automaticamente um card no Kanban, sem duplicar lógica em múltiplos lugares.

### Decisão necessária (bloqueante para implementar)

- **(D3) Fonte da verdade do webhook de recebimento de mensagens.** Hoje há 3 implementações ativas competindo por rota (ver `config/urls.py`, que inclui `integracao.urls` duas vezes e `atendimento.urls` duas vezes). Escolher uma:
  - **Opção A (recomendada):** `atendimento/views.py:webhook_receive` — já resolve empresa corretamente por `WahaSessao`, já cria Tarefa. Descartar as duas cópias em `integracao/` (a comentada e a hard-coded para empresa id=3).
  - **Opção B:** consolidar em `integracao/api/views.py` usando `services/waha_webhook.py` + `services/conversas.py` (arquitetura com idempotência via `WebhookRecebido` e auditoria via `EventoAtendimento`, hoje desconectada) — mais robusta, mas exige mais trabalho de ligar os fios que já existem, porém não são chamados.
  - Se a resposta for "n8n decide quando criar a tarefa" (fluxo já existe: `POST /conversas/<id>/tarefas/`), então o webhook direto (A ou B) só deveria **registrar mensagens**, e a criação de Tarefa fica **exclusivamente** a cargo do n8n chamando essa rota depois que a triagem (keyword ou IA) identificar a intenção do cliente. Isso evita duplicar tarefas.
- **(D4)** "Terminar de conversar e pedir o que quiser" — qual é o gatilho exato de "fim da conversa com intenção capturada"? Hoje o único critério implementado é keyword simples ("licen" → licenciamento) no workflow n8n. Precisa: (a) manter regra por palavra-chave, (b) evoluir para IA de triagem (Gemini/OpenAI) no n8n, ou (c) exigir um passo explícito do bot tipo "digite 1 para X, 2 para Y" antes de criar a tarefa? Isso decide se a spec de frente 2 é só "arrumação de bug/duplicação" ou "nova feature de triagem".

### Tarefas (assumindo D3 = Opção A, mais simples e rápida; ajustar se D3 for B)

1. Remover a segunda definição de `webhook_waha` em `integracao/api/views.py` (bloco morto + bloco hard-coded `Empresa id=3`), e o bloco comentado.
2. Remover `webhook_waha` de `integracao/views.py` se não for mais necessário, ou mantê-lo só para registro de mensagem (sem criar Tarefa) se D3 apontar para "n8n cria a tarefa".
3. Corrigir `config/urls.py` para não incluir `atendimento.urls` e `integracao.urls` duas vezes cada — decidir **um único caminho de URL canônico** por webhook (ex.: `POST /api/v1/integracao/webhooks/waha/<sessao>/`), atualizar `docker-compose.homolog.yml` (`WHATSAPP_HOOK_URL`) e o workflow n8n se o path mudar.
4. Garantir que a criação de Tarefa (seja no webhook direto ou via n8n) sempre passe por `services/conversas.py:criar_tarefa` (única função com auditoria via `EventoAtendimento` e atualização de estado da conversa) — não duplicar a lógica de `get_or_create` de `Servico`/`Tarefa` em 3 lugares.
5. Evitar tarefa duplicada: usar `Tarefa` já existente para a `Conversa` em aberto (checar antes de criar) ou usar `get_or_create` com chave (conversa + serviço).
6. Registrar teste manual: mandar mensagem de teste no WhatsApp vinculado → verificar 1 único card criado no Kanban da empresa correta.

### Critério de pronto

- Existe **um único** endpoint de webhook ativo, sem código morto/comentado ao redor.
- Enviar mensagem no WhatsApp de uma empresa não cria/afeta tarefas de outra empresa (sem hard-code de id).
- Nenhuma tarefa duplicada quando o mesmo evento de webhook chega mais de uma vez (idempotência via `WebhookRecebido`, se D3 = B, ou verificação de tarefa existente, se D3 = A).

---

## Frente 3 — Sidebar no Kanban

**Objetivo:** a tela de Kanban (`atendimento/templates/atendimento/kanban.html`) deve ter o mesmo menu lateral, header, seletor de empresa e logout das outras telas.

### Tarefas

1. Fazer `atendimento/templates/atendimento/kanban.html` estender `documentos/base.html` (`{% extends 'documentos/base.html' %}`), movendo o conteúdo hoje em `<body>` para dentro do bloco de conteúdo (`{% block content %}` ou equivalente — conferir nome do block em `base.html`).
2. Migrar o CSS inline específico do Kanban para um `{% block extra_css %}`/`<style>` isolado dentro do template (ou arquivo estático próprio), evitando colidir com estilos do `base.html`.
3. Conferir que o JS do Kanban (drag-and-drop, fetch de status) continua funcionando dentro do layout novo (ids/classes não devem colidir com os do sidebar).
4. **Aproveitar para corrigir o bug do drag-and-drop:** o JS (`kanban.html`) envia `fetch` com corpo JSON `{tarefa_id, novo_status}`, mas a view `atualizar_status_tarefa` (`atendimento/views.py`) lê `request.POST.get('status')` (nome de campo errado e formato errado — `request.POST` não é populado por JSON). Ajustar a view para ler `json.loads(request.body)` com as chaves corretas, ou ajustar o JS para enviar form-encoded — escolher um lado e alinhar.

### Decisão necessária

- **(D5)** O Kanban deve rodar como "página cheia" (largura maior, sem os paddings padrão de `documentos/base.html`) para caber todas as colunas? Se sim, pode exigir um `{% block content_class %}`/variação de largura no `base.html` em vez de reuso 100% idêntico.

### Critério de pronto

- Navegar para o Kanban a partir do sidebar mantém o sidebar visível, com o item "Atendimento (Kanban)" destacado como ativo.
- Drag-and-drop entre colunas funciona (status realmente muda no banco).
- Sem regressão visual nas outras telas que usam `documentos/base.html`.

---

## Frente 4 — Revisão geral / remoção de código morto

**Objetivo:** eliminar duplicidade e código morto identificado, deixando o fluxo de integração WhatsApp → Kanban único e rastreável.

### Itens concretos (independentes das decisões D1–D5, podem ser feitos em paralelo)

1. **`integracao/api/views.py`** — remover o bloco de `webhook_waha` comentado (referências a `verificar_assinatura_webhook`/`processar_webhook_waha`) e decidir, junto com a Frente 2 (D3), o destino da versão ativa hard-coded (`Empresa id=3`).
2. **`config/urls.py`** — remover as inclusões duplicadas de `atendimento.urls` (`/atendimento/` e `/whatsapp/`) e de `integracao.urls` (`/api/` e `/api/v1/integracao/`); manter só os paths realmente usados por n8n/WAHA e pelo front-end.
3. **`atendimento/services.py` vs `atendimento/services/`** — resolver a ambiguidade de import (módulo `.py` e pacote com mesmo nome no mesmo diretório). Sugestão: mover o conteúdo de `services.py` para dentro do pacote (ex. `services/legado_meta.py`) ou eliminar se `enviar_mensagem_whatsapp` (Cloud API Meta) não for mais usado (ver item 4).
4. **Webhook/legado Meta Cloud API** — `atendimento/views.py:webhook_verify` e `enviar_mensagem_whatsapp` (Cloud API oficial do Meta) não são usados pelo fluxo WAHA atual. Confirmar com o usuário se pode remover (item 14 do `REFINAMENTOS_PENDENTES.md` já lista isso como baixa urgência) — se sim, remover view, rota e função.
5. **`print()` de debug** em `integracao/views.py` e `integracao/api/views.py` — trocar por `logger.debug/info` ou remover.
6. **Scripts de POC na raiz** (`gemini_extrai_tudo.py`, `gemini_placa.py`, `leitor_placa.py`, `comparativo_ocr_placa.md`) — confirmar se ainda são usados fora do Django; se não, remover ou mover para uma pasta `experimentos/` fora do caminho de deploy.
7. Reforçar `.env.example`/`deploy/despachante.env.example` — hoje tem valor real de `WAHA_API_KEY` de homologação preenchido; trocar por placeholder e rotacionar a chave exposta.

### Decisão necessária

- **(D6)** Pode remover o legado Meta Cloud API (webhook_verify + enviar_mensagem_whatsapp) agora, ou ainda há algum cliente piloto usando Meta em vez de WAHA?
- **(D7)** Os scripts de OCR na raiz (`gemini_*.py`, `leitor_placa.py`) ainda são usados manualmente por alguém, ou são só POC morta?

### Critério de pronto

- Uma única definição de cada view/rota de webhook, sem blocos comentados "por precaução".
- `git grep` por `print(` no diretório `webapp/integracao` e `webapp/atendimento` não retorna nada em código de produção.
- `.env.example` sem segredo real.

---

## Ordem sugerida de execução

1. **Frente 4, itens 1–2 e 5** (limpeza de duplicidade de webhook/rotas) — desbloqueia a Frente 2 com menos ambiguidade de qual código está realmente rodando.
2. **Frente 2** (Tarefa automática) — depende da decisão D3.
3. **Frente 1** (QR Code no cadastro) — pode andar em paralelo, não depende das anteriores.
4. **Frente 3** (Sidebar no Kanban) — independente, pode ser feito em paralelo a qualquer momento.
5. **Frente 4, itens restantes** (legado Meta, scripts de POC, `.env.example`) — ao final, depois de confirmado com o usuário (D6/D7).

## Decisões tomadas

| # | Decisão | Status |
| --- | --- | --- |
| D1 | Vinculação manual pelo botão do menu; ao desconectar, pede novo QR automaticamente | ✅ implementado |
| D2 | Entrada sempre disponível no menu lateral | ✅ implementado |
| D3 | Webhook único em `integracao/api/views.py`, usando `services/waha_webhook.py` + `services/conversas.py` (**Opção B**, não a A originalmente sugerida — ver nota abaixo) | ✅ implementado |
| D4 | Bot de WhatsApp com menu de opções — **adiado**, será feito no futuro. Até lá, a tarefa é criada na primeira mensagem da conversa | ⏸ futuro |
| D5 | Kanban usa largura cheia (`page-larga`), as demais telas seguem na coluna padrão | ✅ implementado |
| D6 | Legado Meta Cloud API: `webhook_verify` removido junto da consolidação. `atendimento/services.py:enviar_mensagem_whatsapp` **ainda não** foi removido | 🔸 parcial |
| D7 | Scripts de OCR na raiz do repo | ❓ em aberto |

### Nota sobre D3 — por que Opção B e não a A

A spec recomendava originalmente a Opção A (`atendimento/views.py`), por ser o caminho mais curto.
A escolha mudou para a **Opção B** depois de uma evidência concreta em teste: quando o Django
recusou os webhooks por `ALLOWED_HOSTS`, o WAHA **reentregou o mesmo evento a cada ~2 segundos por
vários minutos**. Sem idempotência, isso teria criado uma enxurrada de mensagens e tarefas
duplicadas. A Opção B já tinha essa proteção pronta (`WebhookRecebido`) e só precisava ser ligada,
além de trazer a trilha de auditoria (`EventoAtendimento`) de graça.

## Perguntas ainda em aberto

| # | Pergunta |
| --- | --- |
| D6b | Pode remover `atendimento/services.py:enviar_mensagem_whatsapp` (Cloud API do Meta, sem uso)? |
| D7 | Scripts de OCR na raiz (`gemini_*.py`, `leitor_placa.py`) ainda são usados? |
