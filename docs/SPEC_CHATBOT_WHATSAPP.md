# Spec — Chatbot de atendimento no WhatsApp

**Projeto:** Despachante
**Data:** setembro/2026
**Contexto:** fecha a decisão **D4** da [`SPEC_QRCODE_TAREFA_KANBAN.md`](SPEC_QRCODE_TAREFA_KANBAN.md), que foi adiada com a nota "bot no WhatsApp futuramente, com as opções".

**Status:** ✅ implementada. As decisões foram fechadas e o código está em
[`atendimento/services/bot.py`](../webapp/atendimento/services/bot.py). O que falta é o
pré-requisito de dados (§3) e as pendências listadas em §8.

---

## Resumo em uma frase

O bot **já está escrito** em [`atendimento/services.py`](../webapp/atendimento/services.py), mas está
desligado do fluxo atual e tem quatro defeitos que impedem ligá-lo como está. O trabalho é menos
"construir um bot" e mais **decidir onde ele roda, corrigir os defeitos e conectar**.

> **Achado durante a implementação:** o `atendimento/services.py` não estava só desligado — estava
> **morto**. Existe também o pacote `atendimento/services/` (com `analise_documento.py`), e um pacote
> sombreia um módulo de mesmo nome. `from atendimento.services import processar_triagem`, em
> `processar_conversas.py`, já falhava com `ImportError`. O motor foi reescrito dentro do pacote,
> como `atendimento/services/bot.py`, e o `services.py` foi removido.

---

## 1. O que já existe

| Peça | Onde | Estado |
| --- | --- | --- |
| Envio de mensagem ao cliente | `integracao/services/waha_client.py:enviar_texto` | ✅ funciona |
| Resposta do bot + registro da saída | `atendimento/services.py:enviar_resposta_bot` | ⚠️ funciona, mas ver defeito **B** |
| Triagem por palavra-chave | `atendimento/services.py:chamar_ia_triagem` | ⚠️ existe, regras fixas no código |
| Coleta de documentos | `atendimento/services.py:processar_coleta_documentos` | ⚠️ existe, nunca exercitada |
| Máquina de estados da conversa | `Conversa.Estado` + `Conversa.Modo` (bot/humano) | ✅ modelada |
| Serviços e documentos exigidos | `Servico` + `DocumentoExigido` | ✅ modelados, ❌ **sem dados** |
| Worker que roda o bot | `manage.py processar_conversas` | ❌ ver defeito **A** |
| Fluxo paralelo no n8n | `n8n/workflows/mensagem-recebida.json` | ⚠️ triagem por keyword, concorre com o Django |

---

## 2. Defeitos que precisam ser corrigidos antes de ligar

Estes não são melhorias — são motivos pelos quais ligar o bot hoje quebraria.

### A. O worker responde em loop, a cada 2 segundos

`processar_conversas.py` seleciona conversas em `modo=bot` e estado `triagem`/`coletando_documentos`
e chama `processar_triagem` **a cada 2 segundos**, sem nenhuma marca de "já respondi a esta
mensagem". Não existe controle de qual foi a última mensagem processada.

**Efeito:** o cliente receberia "Qual serviço você precisa?" a cada 2 segundos, para sempre.

**Correção:** processar **por evento** (quando a mensagem chega no webhook), não por varredura. Ou,
mantendo o worker, guardar na conversa a última mensagem processada e só agir quando houver
mensagem nova.

### B. O envio quebra para contatos com LID

`enviar_resposta_bot` usa `conversa.contato.wa_id` como destino, e `enviar_texto` acrescenta
`@c.us` quando não há `@`. Para contatos novos do WhatsApp, `wa_id` é um **LID**
(ex.: `127878373056719`), e o destino correto seria `...@lid` — o envio iria para um endereço
inexistente.

**Correção:** guardar o `chat_id` completo que o WAHA informou (`from`) e usar esse valor no envio,
em vez de remontar a partir do `wa_id`.

### C. Nada impede o bot de responder a si mesmo

`_extrair_mensagem_waha` descarta apenas mensagens de grupo (`@g.us`). **Não há verificação de
`fromMe`.** Se o WAHA entregar de volta as mensagens que o próprio sistema enviou, o bot responde à
própria resposta — loop infinito, com custo real de mensagens.

**Correção:** descartar `payload.fromMe == true` na extração. É a primeira linha de defesa e vale
mesmo sem bot.

### D. `criar_tarefa` existe duas vezes

`atendimento/services.py:criar_tarefa` e `integracao/services/conversas.py:criar_tarefa` fazem a
mesma coisa, com regras levemente diferentes de resumo e estado. É o mesmo padrão de duplicação já
resolvido nos webhooks.

**Correção:** manter apenas a de `integracao/services/conversas.py`, que tem auditoria
(`EventoAtendimento`).

### E. O webhook atual cria a tarefa antes da triagem

Hoje o card do Kanban nasce na **primeira mensagem**. Com bot, a tarefa deve nascer quando o pedido
estiver caracterizado — senão cada "Oi" vira um card.

---

## 3. Pré-requisito de dados (bloqueia o piloto)

Hoje existem **2 serviços cadastrados**, ambos o genérico "Atendimento Despachante" criado
automaticamente pelo código antigo, e **zero** `DocumentoExigido`.

Sem isso o bot não tem menu para oferecer nem documentos para pedir. É necessário cadastrar, por
empresa:

- os serviços reais (Licenciamento, Transferência, Segunda via de CRLV, …);
- para cada serviço, os documentos exigidos com instruções ao cliente.

Existe Django Admin para os dois modelos. **Decisão (D-BOT-5)** abaixo trata de criar ou não uma
tela no sistema para isso.

---

## 4. Decisões necessárias

### D-BOT-1 — Onde o bot roda

| Opção | Prós | Contras |
| --- | --- | --- |
| **A) Django, no próprio webhook** (recomendada) | Resposta imediata; um lugar só; testável; reaproveita `services.py` | Regra de conversa em código, exige deploy para mudar texto |
| B) Worker Django (o `processar_conversas` de hoje) | Não segura a resposta do webhook | Precisa resolver o defeito **A**; atraso de até 2s; mais uma peça no deploy |
| C) n8n | Operação edita o fluxo sem deploy | Regra de negócio espalhada em dois sistemas; já é fonte de duplicação hoje |

**Recomendação:** **A**, enquanto o fluxo for menu fixo. O envio ao WAHA é rápido (~40ms medidos) e
não justifica fila. Se o texto do menu passar a mudar toda semana, reconsiderar C.

### D-BOT-2 — Menu fixo ou IA

Você descreveu "com as opções", o que aponta para **menu numerado**:

```
Olá! Sou o assistente da Despachante X.
Digite o número do serviço:
1 - Licenciamento
2 - Transferência de propriedade
3 - Falar com um atendente
```

| Opção | Prós | Contras |
| --- | --- | --- |
| **Menu numerado** (recomendada) | Determinístico; sem custo por conversa; fácil de testar e auditar | Rígido; cliente que escreve livremente precisa de fallback |
| IA (Gemini/OpenAI) | Entende linguagem natural | Custo por conversa; não determinístico; precisa de guarda contra alucinação |

**Recomendação:** menu numerado agora, com fallback "não entendi" → repete o menu → após N
tentativas, transfere para humano. IA pode entrar depois só na etapa de interpretar a primeira
mensagem, sem trocar o resto.

### D-BOT-3 — Quando criar a tarefa no Kanban

| Opção | Efeito |
| --- | --- |
| **Ao confirmar o serviço** (recomendada) | Card nasce com serviço definido e pedido claro |
| Ao completar os documentos | Kanban só vê casos prontos, mas atendente perde visibilidade de quem está no meio do fluxo |
| Na primeira mensagem (hoje) | Todo "Oi" vira card |

**Recomendação:** criar ao confirmar o serviço, e ir atualizando a tarefa conforme os documentos
chegam. Assim o atendente enxerga o funil inteiro.

### D-BOT-4 — Regras de transferência para humano

**Decidido:**

- [x] **Opção explícita no menu.** A última opção é sempre "Falar com um atendente". A palavra
      `atendente` (ou `humano`, `pessoa`) em qualquer etapa também transfere.
- [x] **3 respostas não entendidas** seguidas e o bot transfere (`MAX_TENTATIVAS_INVALIDAS`).
      O contador vive em `Conversa.tentativas_invalidas` e zera a cada acerto.
- [x] **Assumir o card cala o bot.** Mover a tarefa para qualquer coluna diferente de "Aberta" põe
      `Conversa.modo = humano`. **Devolver para "Aberta" não religa o bot**: quem já falou com uma
      pessoa não volta para a triagem automática no meio do assunto. Para religar, hoje é no Admin.
- [x] **Sem regra de horário.** O bot responde 24/7; o atendente vê o card no dia seguinte.
- [x] **48 h de inatividade encerram a conversa**, verificadas de forma preguiçosa: quando chega
      mensagem, `obter_ou_criar_conversa` encerra a antiga e abre uma nova na triagem. Não há worker
      novo. Conversa em `modo=humano` **nunca** expira sozinha.

### D-BOT-5 — Tela de cadastro de serviços e documentos

| Opção | Quando faz sentido |
| --- | --- |
| Django Admin | Já existe, custo zero, você mesmo cadastra |
| **Tela no sistema** (decidida) | Quando cada despachante cadastrar os próprios serviços em self-service |

**Decidido: tela no sistema**, em `/atendimento/chatbot/`, restrita ao papel
`ADMINISTRADOR` — o vínculo que nasce da aba "Sou empresa" do cadastro. Funcionário
aprovado (`ATENDENTE`) não vê o item no menu nem alcança a URL. O Django Admin continua
funcionando para suporte.

A tela vai além do catálogo: ela também edita o **comportamento** do bot, que antes
estava fixo em `services/bot.py`. Ver §10.

---

## 5. Frentes de trabalho

### Frente A — Blindagem (independe das decisões, pode começar já)

1. Descartar `fromMe` na extração do webhook (defeito **C**).
2. Guardar o `chat_id` completo do WhatsApp no contato e usá-lo no envio (defeito **B**).
3. Remover `atendimento/services.py:criar_tarefa`, usando só a de `integracao/services/conversas.py` (defeito **D**).
4. Remover `enviar_mensagem_whatsapp` (Cloud API do Meta, sem uso) — é a pendência **D6b** da spec anterior.

### Frente B — Motor do bot

1. Rodar o bot no webhook, após registrar a mensagem, apenas quando `conversa.modo == 'bot'`.
2. Reescrever a triagem como **menu numerado**, montado a partir dos `Servico` ativos da empresa.
3. Estados: `triagem` → (escolha do serviço) → `coletando_documentos` → `aguardando_humano`.
4. Contador de tentativas não entendidas na conversa, com transferência automática.
5. Criar a tarefa no ponto definido na D-BOT-3.

### Frente C — Integração com o Kanban

1. Assumir um card no Kanban passa a conversa para `modo=humano` (o bot cala).
2. Devolver o card para "Aberta" devolve para `modo=bot`? (definir junto da D-BOT-4)
3. Mostrar no card em que etapa do bot o cliente está.

### Frente D — Desligar o que ficou duplicado

1. Decidir o destino do worker `processar_conversas` (aposentar se o bot rodar no webhook).
   → **Reduzido à análise de documentos.** Triagem e coleta saíram: eram a causa do defeito **A**.
2. Decidir o destino do fluxo de triagem do n8n, que hoje concorre com o Django.
   → **Aposentado.** Ver §9.3.

---

## 6. Ordem sugerida

```
1. Frente A          — blindagem; sem ela, ligar o bot gera loop e envio quebrado
2. Cadastrar serviços e documentos reais (pré-requisito de dados)
3. Frente B          — motor do menu
4. Frente C          — integração com o Kanban
5. Frente D          — remover duplicações
```

## 7. Como validar

- Mandar "Oi" de um número de teste → recebe o menu **uma vez** (não em loop).
- Escolher uma opção inválida três vezes → é transferido para humano.
- Escolher um serviço → card aparece no Kanban com o serviço correto.
- Assumir o card no Kanban → mandar nova mensagem → o bot **não** responde.
- Conferir que o bot nunca responde a uma mensagem enviada pelo próprio sistema.

Cada item acima tem teste automatizado em `atendimento/tests.py` (`BotTests`,
`KanbanSilenciaBotTests`, `ExpiracaoDeConversaTests`) e `integracao/tests.py`.

---

## 8. Onde o código ficou

| Peça | Onde |
| --- | --- |
| Motor do bot (menu, coleta, transferência) | `atendimento/services/bot.py` |
| Gatilho por evento + defesa contra `fromMe` | `integracao/services/waha_webhook.py` |
| Expiração de 48 h e criação de tarefa | `integracao/services/conversas.py` |
| Kanban cala o bot ao assumir o card | `atendimento/views.py:atualizar_status_tarefa` |
| Cadastro de serviços + documentos | `/atendimento/chatbot/` (§10) e Django Admin |

**Mudanças de contrato:**

- `Contato.chat_id` guarda o endereço completo do WAHA (`...@c.us` / `...@lid`) e é o destino de
  envio. Contatos anteriores à migração `0005` têm o campo vazio e caem no `wa_id` antigo — o
  envio para eles só volta a funcionar na próxima mensagem que receberem.
- `criar_tarefa(..., assumir_por_humano=False)` cria o card **sem** encerrar o turno do bot. É o
  que permite o card nascer na escolha do serviço e o bot continuar pedindo documentos.
- O webhook **não cria mais tarefa na primeira mensagem** (defeito **E**). Quem cria é o bot.
- Mensagens só com anexo (sem legenda) passam a ser registradas com o texto
  `[arquivo enviado pelo cliente]` — antes eram descartadas, e sem elas a coleta de documentos não
  teria como avançar.
- `manage.py processar_conversas` agora é só o worker de **análise** de documentos.

## 9. Pendências conhecidas

1. **O arquivo do documento não é baixado.** Quando o cliente manda a foto, o bot registra o
   `DocumentoRecebido` e segue para o próximo, mas não puxa a mídia do WAHA — o registro fica sem
   arquivo, e portanto sem análise por OCR/IA. `baixar_midia` já existe em `waha_client.py`; falta
   decidir se o download entra no webhook (mais latência) ou em um worker.
2. ~~**Religar o bot é operação de Admin.**~~ **Resolvido:** a tela do chatbot (§10) lista as
   conversas em `modo=humano` e tem o botão "Devolver ao bot". Ainda não há atalho no card do
   Kanban.
3. **Fluxo do n8n `mensagem-recebida.json` está aposentado**, não removido. Ele tem nós próprios de
   triagem e criação de card que agora duplicariam o Django. **Não apontar o webhook do WAHA para
   ele.** O arquivo segue no repositório como referência do que a operação editava sem deploy.
4. **A suíte do app `documentos` está vermelha** (15 erros, 2 falhas) desde antes deste trabalho,
   por motivo não relacionado ao bot. `atendimento` e `integracao` estão verdes.

---

## 10. Tela de configuração do chatbot

**Rota:** `/atendimento/chatbot/` · **Quem entra:** apenas `EmpresaUsuario.Papel.ADMINISTRADOR`
da empresa ativa, pelo decorator `empresas.permissoes.somente_administrador` — o mesmo portão que
a tela de Equipe passou a usar.

### O que a tela edita

| Seção | O que faz |
| --- | --- |
| O menu | Saudação, **as opções (os `Servico`) e a última opção, na mesma seção e na ordem em que o cliente as lê**. Cada opção se edita com seus `DocumentoExigido` no mesmo formulário; a ordem se define **arrastando a linha ou pelas setas**, e é salva na hora |
| Comportamento | O que o bot faz fora do menu: liga/desliga, texto de "não entendi", de transferência e de conclusão, limite de tentativas e palavras que chamam um atendente |
| Prévia do menu | Mostra o texto exato que o cliente recebe, **atualizada enquanto se digita** — antes de salvar |
| Conversas em atendimento humano | Lista `modo=humano` e devolve ao bot, reabrindo a triagem e reenviando o menu |

### Mudanças de contrato

- **`ConfiguracaoBot` é criada sob demanda** por `ConfiguracaoBot.para(empresa)`, com defaults
  iguais aos textos que estavam fixos em `bot.py`. Empresa que nunca abrir a tela atende
  exatamente como antes — é o que mantém a suíte existente verde.
- **`MAX_TENTATIVAS_INVALIDAS` e `PEDIDO_DE_ATENDENTE` continuam em `bot.py`, mas como
  documentação do padrão**: o motor lê `config.max_tentativas_invalidas` e
  `config.regex_atendente()`.
- **Bot desligado não é silêncio.** Com `ativo=False`, a mensagem do cliente vai direto para
  `_transferir_para_humano(motivo='bot_desligado')`: ele recebe resposta e o card nasce no Kanban.
- **`Servico.ordem`** (migration `0006`) entra com `0` para todo serviço existente, e o menu
  ordena por `('ordem', 'nome')` — o mesmo resultado de antes até alguém mexer na ordem.
- **`ordem` não é campo do formulário de serviço.** Ela se define só na lista, por
  `POST /atendimento/chatbot/servicos/ordem/`, que renumera de 1 a N. Dois lugares para digitar a
  mesma posição é como se criam empates e ordens que não batem com o que a tela mostra. Serviço
  novo nasce no fim (`max(ordem) + 1`).
- **A reordenação exige a lista completa** dos serviços da empresa. Uma lista parcial deixaria os
  ausentes com o número antigo, empatando com os novos; o endpoint devolve 400.
- **A prévia é montada no navegador**, a partir dos campos em edição e da ordem atual da lista —
  não do banco. É o que permite ver o menu antes de salvar. Com o atendimento automático
  desmarcado, ela avisa que aquele menu não será enviado.
- **Os campos da configuração ficam fora do `<form>`**, ligados a ele pelo atributo HTML `form=`
  (`ConfiguracaoBotForm.ID_DO_FORM`). É o que permite intercalar a lista de opções — que tem forms
  próprios de excluir, e portanto não pode ficar aninhada — entre a saudação e a última opção.
  Campo sem esse atributo deixa de ser enviado em silêncio; `test_campos_da_configuracao_ficam_ligados_ao_form`
  existe por isso.
- **A posição mostrada na lista conta só as opções ativas**, e a inativa aparece como `—`. Mostrar
  a posição bruta faria a lista discordar da prévia.
- **Excluir serviço já usado não é possível** (FK `PROTECT` em `Conversa` e `Tarefa`): a tela
  desativa em vez de excluir e avisa. Sem atendimento algum, exclui junto com os documentos.
- **Devolver ao bot reenvia o menu.** Sem isso a próxima mensagem do cliente seria lida como
  escolha de uma opção que ele não está mais vendo. Sem serviço ativo cadastrado, a conversa
  continua com o humano.

Cobertura em `atendimento/tests.py`: `ConfiguracaoBotAplicadaTests`, `TelaChatbotTests`,
`ReligarConversaTests`.

---

## 11. Ramificação da conversa (sub-opções)

Fecha o pedido "tratar o rumo da conversa em cada opção". O exemplo que motivou:

```
Bot:  2 - Transferência
Cli:  2
Bot:  Transferência de carro ou moto?
      1 - Carro
      2 - Moto
      3 - Falar com um atendente
Cli:  2
Bot:  Para agilizar, separe os documentos.

      Perfeito! Para *Moto* vou precisar de alguns documentos.
      Primeiro: *CRLV* ...
```

### Modelo

`Servico.pai` (auto-FK, `CASCADE`) transforma o catálogo em árvore, **sem limite de
profundidade**. `Servico.mensagem_apos_escolha` é enviada assim que a opção é escolhida e tem dois
papéis conforme o nó: numa **folha** é o recado antes dos documentos; num nó **com sub-opções
ativas** é a pergunta que abre o submenu (em branco, `Servico.PERGUNTA_PADRAO`). Um campo só, com
um significado só — "o que o bot diz ao escolherem isto" —, e a tela adapta o texto de ajuda.

### Regras

- **Só a folha conclui.** Escolher um nó com sub-opções ativas apenas abre o submenu: a conversa
  segue em `triagem`, `Conversa.servico` guarda onde o cliente está na árvore, e **nenhum card
  nasce** — o pedido ainda não está caracterizado. O card nasce na folha, com
  `resumo_triagem` trazendo o caminho inteiro (`Transferência › Moto`), porque só o nome da folha
  ("Moto") não diria ao atendente o que foi pedido.
- **Sem filho ativo, o nó vira folha.** Desativar todas as sub-opções faz o pai voltar a concluir
  o pedido sozinho, com os documentos dele.
- **"Não entendi" repete o menu em que o cliente está**, não o principal, e sem a saudação.
- **Devolver ao bot zera `Conversa.servico`**, senão o cliente voltaria preso no submenu de uma
  ramificação antiga.
- **Guarda contra ciclo.** `Servico.ancestrais()` carrega um conjunto de visitados: um `pai`
  apontando para o próprio descendente — possível por escrita direta no banco — travaria o bot num
  laço infinito em vez de só exibir um caminho estranho.
- **Unicidade é entre irmãos**, não por empresa: "Moto" pode existir sob "Transferência" e sob
  "Licenciamento". São duas constraints, separadas por `condition`, porque em SQL `NULL != NULL` e
  uma constraint sobre `('empresa', 'pai', 'nome')` sozinha deixaria passar dois nomes iguais no
  menu principal.

### Na tela

- A lista de opções virou **árvore**, renderizada pelo include recursivo
  `_menu_opcoes.html`. A sub-lista mora **dentro** do `<li>` do pai, então arrastar o pai leva o
  galho junto — e o JS usa `:scope >` para uma lista não enxergar as linhas dos próprios submenus.
- **A ordem vale entre irmãos**: cada nível é uma lista com seu `data-pai-id`, e
  `POST /chatbot/servicos/ordem/` recebe `{pai, ordem}` e exige a lista completa **daquele
  nível**. Arrastar entre níveis é bloqueado — mudaria o pai da opção, que é outra operação.
- **Excluir um nó com sub-opções é recusado** (o `CASCADE` levaria o galho inteiro, e bastaria uma
  folha ter atendimento para o banco recusar no meio). O caminho é esvaziar antes, ou desativar.
- **A tela da opção ganhou prévia da conversa**, montada no navegador com os moldes reais de
  `bot.py` (`textos_do_bot`), expostos por `json_script`. Reescrevê-los em JavaScript faria a
  prévia mentir assim que um texto mudasse. Quando a opção ramifica, a prévia mostra o submenu em
  vez da coleta.

### O que ficou de fora

Não há opção "voltar" no submenu: com árvore funda, um cliente que erra o caminho só sai pela
palavra que chama atendente. Vale reavaliar depois do piloto.

Cobertura: `SubOpcoesDoMenuTests` (motor, incluindo três níveis e ciclo) e `TelaSubOpcoesTests`
(tela, ordem por nível e exclusão).

---

## 12. Anexos: figurinha não é documento

**Defeito encontrado em teste real.** O webhook classificava tudo num booleano `tem_midia`, e o bot
tratava qualquer mídia como o documento pedido. Uma **figurinha** — `image/webp`, portanto "mídia" —
dava o CPF por recebido, criava o `DocumentoRecebido` vazio e o bot seguia para o próximo documento.
O mesmo valia para áudio, vídeo, contato e localização.

`integracao/anexos.py` passa a classificar o que chegou:

| Categoria | Vale como documento? |
| --- | --- |
| `foto`, `documento` (PDF/DOC) | ✅ sim |
| `figurinha`, `audio`, `video`, `localizacao`, `contato`, `outro` | ❌ não |

O módulo mora fora de `waha_webhook` e de `bot` porque o webhook já importa o bot — pôr as
categorias em qualquer um dos dois fecharia um ciclo de importação.

**O que mudou no comportamento:**

- **Na coleta**, anexo do tipo errado não consome a vez do documento: o bot recusa dizendo o que
  recebeu ("Isso é uma figurinha, e eu preciso do documento") e repete a instrução. O documento da
  vez continua sendo o mesmo.
- **Na triagem**, anexo nunca conta como escolha de opção. Isso também fecha uma brecha menor: a
  legenda de uma foto ("1 - achei essa") poderia ser lida como a opção 1.
- **Áudio e vídeo admitem o limite** em vez de dizer "não entendi", que soa como se o bot tivesse
  ouvido e não compreendido. Continuam contando como tentativa inválida, então três seguidas levam
  a conversa a um atendente — que é a saída certa para quem está tentando falar por voz.
- **O histórico diz o que era.** Anexo sem legenda era gravado como `[arquivo enviado pelo cliente]`
  para qualquer coisa; agora é `[figurinha]`, `[foto]`, `[áudio]`… O atendente precisa distinguir
  um CPF de um joinha ao ler a conversa.
- `processar_mensagem(conversa, msg, tem_midia=True)` virou `anexo='foto'`.

Cobertura: `ClassificacaoDeAnexoTests` e `BotComAnexosTests`.
