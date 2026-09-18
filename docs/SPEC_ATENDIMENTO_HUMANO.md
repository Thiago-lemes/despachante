# Spec — Atendimento humano pelo WhatsApp

**Projeto:** Despachante
**Data:** setembro/2026
**Contexto:** continua a [`SPEC_CHATBOT_WHATSAPP.md`](SPEC_CHATBOT_WHATSAPP.md). O bot já conduz a
triagem e a coleta; falta a outra metade — a pessoa que assume o atendimento conversar com o
cliente pelo sistema.

**Status:** ✅ implementada. Decisões fechadas em §3 e §6; onde o código ficou, em §10.

---

## Resumo em uma frase

Vários atendentes dividindo **um único número de WhatsApp**, cada um falando só com os clientes
cujo card ele puxou — e a separação entre eles não existe no WhatsApp, tem que ser construída aqui.

---

## 1. O que o WhatsApp permite (e o que não permite)

Isto não é decisão de projeto, é limite da plataforma, e define o resto da spec.

| Fato | Consequência |
| --- | --- |
| Um número = uma conta. O WhatsApp não tem conceito de atendente | Quem "assinou" a resposta só existe no nosso banco |
| O WAHA é um dispositivo vinculado, como o WhatsApp Web | Uma sessão por empresa já basta; não é uma por atendente |
| O cliente vê todas as respostas vindas do número da empresa | Se quisermos que ele saiba com quem fala, tem que ir no texto |
| O celular da empresa continua na mesma conta | Resposta dada por lá não passa pelo sistema |

**A separação por atendente é 100% responsabilidade do Django.** O WhatsApp entrega tudo num balaio
só; quem decide quem pode falar com quem somos nós.

---

## 2. O que já existe

| Peça | Onde | Estado |
| --- | --- | --- |
| Uma sessão WAHA por empresa | `integracao/views.py:44` (`empresa_{id}`) | ✅ funciona |
| Conversas isoladas por contato | `Contato` + `Conversa` + `chat_id` | ✅ funciona |
| Dono do card | `Tarefa.atendente`, preenchido ao mover no Kanban | ✅ existe |
| Histórico da conversa | `Mensagem` (entrada/saída) | ⚠️ existe, **sem autor** |
| Envio de texto ao cliente | `integracao/services/waha_client.py:enviar_texto` | ✅ funciona |
| Rota de envio | `POST /api/v1/integracao/mensagens/enviar/` | ⚠️ é do n8n, ver §4-C |
| Tela para o atendente responder | — | ❌ **não existe** |
| Bot se cala ao assumir o card | `atendimento/views.py:atualizar_status_tarefa` | ✅ funciona |

---

## 3. Decisões fechadas

- **D-ATD-1 — O atendente só conversa com quem ele puxou.** Enviar mensagem numa conversa exige ser
  o dono do card daquela conversa. Card na coluna inicial, sem dono, ninguém responde.
- **D-ATD-2 — O card não volta para a coluna inicial.** Uma vez assumido, ele pertence a alguém até
  ser concluído ou cancelado. É isso que faz D-ATD-1 parar de pé.
- **D-ATD-3 — Transferência pelo próprio card, por qualquer atendente.** Um menu no card com
  "assumir atendimento" e "atribuir para", **sem exigir papel de administrador**. Todo atendente da
  empresa pode puxar para si ou passar adiante; o que não pode é ficar sem rastro (§5, R4).
- **D-ATD-4 — Tempo de inatividade configurável, e a conversa volta ao bot.** O prazo de expiração
  sai da constante `HORAS_ATE_EXPIRAR = 48` e vira campo em `ConfiguracaoBot`, editável na tela do
  chatbot. Passado o prazo sem interação, a conversa volta para `modo=bot` **mesmo que esteja em
  modo humano** — mas **só enquanto o card estiver na coluna inicial**. Card já assumido por alguém
  não é tirado dele por silêncio do cliente.
- **D-ATD-5 — Engano se resolve entre atendentes.** Como D-ATD-3 deixa qualquer atendente assumir
  ou atribuir, quem pegou o card errado pede para o colega assumir. Não é preciso reabrir a volta
  para a fila que D-ATD-2 fechou.
- **D-ATD-6 — Resposta dada pelo celular entra no histórico**, como saída sem autor, desduplicada
  pelo `wa_message_id`, sem acionar o bot.
- **D-ATD-7 — Atualização por polling**, no padrão do badge do Kanban. Até ~20s de atraso é
  aceitável; não entra WebSocket nem ASGI.
- **D-ATD-8 — O cliente sempre sabe com quem fala.** Mensagem de atendente vai identificada, e a
  troca de mãos é anunciada ao cliente (§5, R2).

---

## 4. Os quatro buracos

### A. O cliente que volta depois do card fechado cai no vazio

Existe **hoje**, escondido pela falta da tela.

`_expirou` só encerra conversa que está com o bot ([`conversas.py:25`](../webapp/integracao/services/conversas.py#L25)) —
conversa em `modo=humano` **nunca expira**. E o webhook só chama o bot quando `modo == BOT`
([`waha_webhook.py:184`](../webapp/integracao/services/waha_webhook.py#L184)). Resultado:

```
Cliente escreve  →  mensagem registrada na conversa antiga (ainda modo=humano)
                 →  bot mudo
                 →  nenhum card novo
                 →  ninguém é avisado
```

**D-ATD-4 fecha metade disto:** o card que ninguém puxou deixa de segurar a conversa para sempre.

**A outra metade continua aberta** e precisa de regra própria: quando o card é **concluído ou
cancelado**, ele não está na coluna inicial, então D-ATD-4 não se aplica — e a conversa fica viva,
em modo humano, sem dono. O cliente que escreve "obrigado, e mais uma coisa…" três dias depois cai
exatamente no vazio descrito acima. Ver a pendência **P-1** em §6.

### B. As respostas dadas pelo celular somem do histórico — **resolvido por D-ATD-6**

O webhook descarta `fromMe`, e faz certo: sem isso o bot responderia à própria resposta. Mas quando
o histórico vira a mesa de trabalho do atendente, o buraco é pior que o risco — ele lê a conversa
sem saber que alguém já respondeu pelo celular e responde de novo.

Registrar como `SAIDA` **sem chamar `processar_mensagem`** mantém a defesa e fecha o buraco. A
desduplicação contra o que o próprio sistema enviou é possível porque `registrar_mensagem_saida`
já guarda o `wa_message_id`.

### C. A rota de envio que existe não serve para o atendente

Em português claro: **hoje existe um jeito de mandar mensagem pelo sistema, mas ele foi feito para
robô, não para gente.**

`POST /api/v1/integracao/mensagens/enviar/` ([`api/views.py:98`](../webapp/integracao/api/views.py#L98))
foi construída para o n8n chamar de fora. Três consequências:

1. **Ela não sabe quem é a pessoa.** Autentica por uma chave da empresa, não por usuário logado
   (`login_not_required`). Se a tela do atendente usasse essa rota, qualquer um com a chave
   responderia qualquer conversa — a regra D-ATD-1 não teria onde se apoiar.
2. **Ela não registra quem respondeu.** Grava `ator='n8n'` fixo, e `Mensagem` nem tem campo de
   autor. Toda mensagem ficaria anônima no histórico.
3. **Ela tem um bug de endereço.** Usa `conversa.contato.wa_id` em vez de `chat_id`
   ([`api/views.py:118`](../webapp/integracao/api/views.py#L118)). É o **defeito B** da spec do bot,
   já corrigido no motor e ainda vivo aqui: para contato novo do WhatsApp, cujo identificador é um
   LID, a mensagem vai para um endereço que não existe e some.

**O que fazer:** a tela do atendente ganha **rota própria**, autenticada por sessão, que confere o
dono do card antes de enviar. A rota do n8n continua existindo para o que ela serve, mas o item 3
é bug e precisa ser corrigido nela de qualquer forma.

### D. Dois atendentes podem puxar o mesmo card

`atualizar_status_tarefa` grava direto ([`atendimento/views.py:140`](../webapp/atendimento/views.py#L140)),
sem conferir se alguém já assumiu. Dois cliques quase simultâneos: o último sobrescreve, sem aviso
para nenhum dos dois.

**Como resolver — e por que não basta "checar antes de gravar":** conferir e depois gravar em duas
etapas deixa uma fresta entre a conferência e a gravação; com dois cliques no mesmo instante, os
dois passam pela conferência antes de qualquer um gravar. A trava tem que ser **uma operação só, no
banco**, que só altera a linha se ela ainda estiver livre:

```python
# Só passa a tarefa para EM_ATENDIMENTO se ela ainda estiver na coluna inicial
# e sem dono. O próprio UPDATE é a trava: quem chegar depois altera 0 linhas.
alteradas = Tarefa.objects.filter(
    pk=tarefa_id, empresa=empresa,
    status=Tarefa.Status.ABERTA, atendente__isnull=True,
).update(status=Tarefa.Status.EM_ATENDIMENTO, atendente=usuario, assumida_em=agora)

if not alteradas:
    # Perdeu a corrida: devolver quem assumiu, em vez de sobrescrever.
```

O banco garante que só um `UPDATE` encontra a linha no estado esperado. Quem perde recebe o nome de
quem assumiu e a tela se atualiza — ninguém perde um cliente em silêncio. Assumir card **de outra
pessoa** (D-ATD-3) é outro caminho, deliberado e com registro, não a mesma corrida.

---

## 5. Requisitos

### R1 — Tela de conversa

- **Botão no card que só aparece fora da coluna inicial**, levando direto para a conversa. Card que
  ninguém puxou não tem conversa para abrir.
- Histórico completo em ordem, distinguindo cliente, bot, atendente (com nome) e o que saiu pelo
  celular da empresa.
- Documentos recebidos aparecem na linha do tempo, não numa lista à parte.
- Campo de resposta **visível só para o dono do card**. Para os demais, o histórico é leitura.

### R2 — Envio pelo atendente

- Rota nova, autenticada por sessão, validando: conversa da empresa ativa **e** tarefa em
  `EM_ATENDIMENTO` naquela conversa cujo `atendente` é o usuário.
- Envia por `chat_id` (nunca `wa_id`), pela sessão WAHA ativa da empresa.
- Registra com autor. **Campo novo:** `Mensagem.autor`.
- Falha de envio não grava a mensagem como enviada — o atendente precisa ver que não saiu.
- **D-ATD-8:** a mensagem sai identificada com o nome do atendente, e assumir ou receber um card
  por transferência dispara um aviso ao cliente dizendo quem passou a atendê-lo. Formato a
  confirmar na implementação (ver P-2).

### R3 — Assumir card com trava

- Assumir é o `UPDATE` condicional de §4-D. Perdeu a corrida, a tela diz quem assumiu.
- Sem volta para `ABERTA` (**D-ATD-2**): remover o ramo em
  [`atendimento/views.py:120`](../webapp/atendimento/views.py#L120) e bloquear o destino no arrasto
  do Kanban. O teste `test_devolver_para_aberta_nao_religa_o_bot` passa a ser "não é possível
  devolver".

### R4 — Transferir atendimento

- Menu no card: **assumir atendimento** (puxar para si um card de outra pessoa) e **atribuir
  para** (escolher um colega). Disponível a **qualquer atendente** da empresa (**D-ATD-3**).
- O destinatário precisa ter vínculo **ativo** na empresa.
- Grava `EventoAtendimento` com quem transferiu, de quem para quem e quando. Sem rastro,
  transferência é a mesma coisa que sobrescrever.
- O cliente é avisado da troca (**D-ATD-8**).

### R5 — Saída da empresa

- Ao desativar ou recusar um vínculo na tela de Equipe, avisar quantos atendimentos abertos aquela
  pessoa tem e oferecer a atribuição na hora.
- A tela de Equipe mostra, por membro, quantos cards abertos ele carrega.

### R6 — Expiração configurável

- `ConfiguracaoBot` ganha o prazo de inatividade (hoje a constante `HORAS_ATE_EXPIRAR = 48`),
  editável na tela do chatbot, na seção "Comportamento".
- `_expirou` passa a valer também para `modo=humano`, **desde que o card esteja na coluna
  inicial** (**D-ATD-4**).
- Card assumido nunca expira por silêncio do cliente.

### R7 — Atualização da tela

- Polling na conversa aberta e na contagem do card, no padrão de `tarefas_novas_status`.
- Intervalo alvo: até 20s (**D-ATD-7**).

---

## 6. Pendências — fechadas

### P-1 — O cliente que volta depois do card concluído ✅

**Concluir ou cancelar o card encerra a conversa.** A próxima mensagem não acha conversa ativa,
`obter_ou_criar_conversa` abre uma nova em modo bot, o bot faz a triagem e nasce card novo. Usa a
máquina que já existe, sem peça nova.

### P-2 — Como o cliente é informado de quem fala com ele ✅

**Pelo nome do atendente que puxou o card**, das duas formas: aviso quando ele assume ou recebe o
atendimento, e prefixo em cada mensagem que ele manda. O nome usado é o primeiro nome, caindo para
o nome completo e, na falta dos dois, para o usuário.

### P-3 — O card órfão quando a conversa volta ao bot ✅

**Cancelar o card órfão ao expirar.** O Kanban não fica com dois cards do mesmo contato, e o que
aconteceu fica registrado em `EventoAtendimento`. Reaproveitar a conversa foi descartado por causa
da armadilha do `ja_ofereceu_menu`: o bot decide se já mostrou o menu perguntando se existe
qualquer mensagem de saída na conversa, e reusá-la o faria pular o menu e ler a próxima frase do
cliente como se fosse o número de uma opção.

---

## 7. Mudanças de modelo previstas

| Modelo | Campo | Para quê |
| --- | --- | --- |
| `Mensagem` | `autor` (FK usuário, nulo) | Saber quem respondeu — hoje não há como |
| `Mensagem` | origem (`cliente` / `bot` / `atendente` / `celular`) | Distinguir na linha do tempo |
| `ConfiguracaoBot` | `horas_ate_expirar` (default 48) | **D-ATD-4** |
| `Tarefa` | — | Nenhuma. `atendente` já existe e basta |

Nenhuma migration de dado pesada: `autor` nasce nulo para todo o histórico existente.

---

## 8. Ordem sugerida

```
1. P-1 + R6 (expiração e fim de conversa)  — sem isso, cliente que volta some
2. Bug do chat_id na rota do n8n (§4-C.3)  — envio quebrado é envio quebrado
3. R3 (trava ao assumir + sem volta)       — alicerce de D-ATD-1
4. Mensagem.autor + R1 (histórico e botão) — leitura antes de escrita
5. R2 (enviar)                             — o ponto do trabalho
6. R4 e R5 (transferência e saída)
7. R7 (polling)
```

---

## 9. Como validar

- Dois atendentes, dois cards: cada um só vê campo de resposta no seu; o do outro é leitura.
- Dois atendentes clicando no mesmo card ao mesmo tempo: um assume, o outro recebe o nome de quem
  assumiu — e nenhum dos dois perde o atendimento em silêncio.
- Card assumido não volta para a coluna inicial, nem arrastando.
- Um atendente assume o card de outro pelo menu; o antigo perde o campo de resposta, o cliente é
  avisado e o evento fica registrado.
- Funcionário desativado na Equipe: os cards dele aparecem para atribuição.
- Card parado na coluna inicial além do prazo: a conversa volta ao bot e o Kanban não fica com dois
  cards do mesmo contato.
- Card assumido e cliente calado além do prazo: **não** expira.
- Concluir o card e o cliente escrever de novo: nasce um atendimento novo, com card novo.
- Resposta dada pelo celular da empresa aparece no histórico, e o bot não reage a ela.
- Envio com o WAHA fora do ar: o atendente vê a falha e a mensagem não entra como enviada.
- Contato com LID (`...@lid`): a resposta do atendente chega.

---

## 10. Onde o código ficou

| Peça | Onde |
| --- | --- |
| Envio ao cliente (bot e atendente) | `atendimento/services/mensageria.py` |
| Assumir, atribuir, responder | `atendimento/services/atendimento.py` |
| Tela da conversa | `atendimento/templates/atendimento/conversa.html` + `views.conversa` |
| Trava e fim de conversa no Kanban | `atendimento/views.py:atualizar_status_tarefa` |
| Expiração e encerramento | `integracao/services/conversas.py` |
| Resposta pelo celular | `integracao/services/conversas.py:registrar_mensagem_do_celular` |
| Cards de quem saiu da empresa | `empresas/views.py:equipe` |

**Mudanças de contrato:**

- **O envio saiu do bot.** `enviar_resposta_bot` agora delega a `mensageria.enviar_mensagem`, que é
  o único lugar que escolhe a sessão WAHA, resolve o `chat_id` e registra a saída. Manter duas
  cópias disso foi o defeito D da spec anterior. Testes que trocavam o WAHA por mock passam a
  apontar para `atendimento.services.mensageria.enviar_texto`.
- **`Mensagem` ganhou `origem` e `autor`.** A migration `0008` marca todo o histórico de saída
  como `bot`, que era a verdade antes desta spec — o default do campo é `cliente` e deixaria o
  passado errado.
- **`Mensagem` ordena por `('criada_em', 'id')`.** Só pela data, o aviso de quem assumiu e a
  primeira resposta — gravados no mesmo instante — sairiam em ordem imprevisível.
- **Conversa em modo humano passa a expirar**, desde que o card não esteja assumido. A regra
  antiga ("modo humano nunca expira") virou "atendimento assumido nunca expira", que é o que
  realmente se queria proteger.
- **`atualizar_status_tarefa` recusa três coisas** que antes aceitava: voltar para a fila (409),
  mover card de outra pessoa (403) e assumir um card que alguém pegou primeiro (409, com o nome de
  quem assumiu).
- **O card na fila não abre conversa.** O botão "Abrir conversa" só aparece fora da coluna inicial,
  porque sem dono ninguém fala com o cliente.

**Pendência conhecida:** o polling recarrega a página inteira quando chega mensagem nova. Isso
preserva o que o atendente está digitando (só recarrega quando o total muda), mas perde a posição
de rolagem em conversa longa. Trocar por atualização parcial é melhoria, não defeito.

Cobertura em `atendimento/tests.py`: `AtendimentoHumanoTests` (22 casos — trava, permissão,
assinatura, transferência, fim de conversa), `RespostaPeloCelularTests` e
`ExpiracaoDeConversaTests`.

---

## 11. Minhas conversas

Item próprio no menu lateral, visível a qualquer pessoa da empresa: a lista dos atendimentos **do
usuário logado**. O Kanban continua mostrando a fila da equipe inteira; esta tela responde a outra
pergunta — "o que está comigo agora".

- Lista as tarefas `EM_ATENDIMENTO` cujo `atendente` é o usuário, mais recentes primeiro pela
  última mensagem.
- **"Aguardando você"** marca a conversa cuja última mensagem é de entrada: o cliente falou e
  ninguém respondeu. É a mesma conta do badge no menu.
- A última mensagem de cada conversa vem por subconsulta (`Subquery` sobre `Mensagem`), não por uma
  ida ao banco por linha.
- O badge segue o padrão dos outros do menu, em `app.js`, com intervalo de 20s — aqui a resposta é
  humana, e 5s só geraria consulta à toa.

Cobertura: `MinhasConversasTests`.
