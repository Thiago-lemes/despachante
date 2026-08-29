# Implementação multiempresa — etapas 1 a 3

Este documento registra as alterações concluídas para permitir que o sistema
atenda mais de uma empresa sem compartilhamento indevido de dados. Ele também
serve como roteiro de validação antes de avançar para WAHA/n8n.

## Objetivo

O projeto original isolava documentos por usuário e não possuía uma entidade de
empresa. Isso não era suficiente para uma operação com vários funcionários por
empresa nem para o atendimento WhatsApp, pois contatos, conversas e tarefas não
tinham qualquer escopo de organização.

A implementação adotou o modelo de *tenant compartilhado*: todas as empresas
usam o mesmo banco de dados, mas cada registro de negócio possui uma referência
obrigatória para `Empresa`. O backend sempre filtra os dados pela empresa ativa
do usuário autenticado.

## Etapa 1 — estabilização

### Problema corrigido

O campo de upload múltiplo usava `super()` sem argumentos dentro de uma list
comprehension. Nesse contexto do Python, `super()` perde o contexto de classe,
causando falha nos uploads individual e em lote.

### Alteração

Em `webapp/documentos/forms.py`, o método `super().clean` passou a ser obtido
antes da iteração e reutilizado para cada arquivo.

### Resultado

- Upload avulso e upload em lote voltaram a funcionar.
- Os testes existentes de documentos passaram de 4 erros para sucesso.

## Etapa 2 — fundação de empresas e usuários

Foi criado o app `webapp/empresas`.

### Modelos

| Modelo | Finalidade |
| --- | --- |
| `Empresa` | Organização cliente do sistema: nome, CNPJ, status e auditoria básica. |
| `EmpresaUsuario` | Vínculo entre um usuário Django e uma empresa, contendo papel e situação ativa. |

O CNPJ é único quando informado. O campo permite ficar vazio enquanto o cadastro
da empresa estiver incompleto.

### Papéis disponíveis

- `administrador`: gestão da empresa e de seus usuários.
- `atendente`: operação de atendimento/Kanban.
- `operador_documentos`: operação de documentos.

Os papéis foram criados para a evolução do controle de permissões. Nesta fase,
o isolamento de empresa é obrigatório; regras finas por papel podem ser
aprofundadas posteriormente.

### Migração de compatibilidade

As migrações `empresas.0001_initial` e `empresas.0002_empresa_padrao` criam a
**Empresa padrão** e associam todos os usuários já existentes a ela como
administradores. Com isso, os usuários que já usavam o sistema continuam tendo
uma empresa válida, sem exclusão ou alteração dos seus dados.

## Etapa 3 — isolamento efetivo dos dados

### Campos de empresa adicionados

Os seguintes modelos agora têm `empresa` obrigatório:

| Área | Modelos |
| --- | --- |
| Documentos | `Documento`, `Lote` |
| Atendimento | `Contato`, `Servico`, `Conversa`, `Mensagem`, `DocumentoExigido`, `DocumentoRecebido`, `Tarefa` |

As migrações `documentos.0005_empresa` e `atendimento.0002_empresa` seguem um
processo sem perda de dados:

1. adicionam os campos como opcionais;
2. associam os registros já existentes à Empresa padrão;
3. tornam os campos obrigatórios;
4. criam índices e restrições de unicidade necessários.

### Restrições relevantes

- Um contato é único por `(empresa, wa_id)`. Assim, o mesmo número WhatsApp
  pode ser um contato em empresas distintas.
- Um serviço é único por `(empresa, nome)`.
- Documentos são deduplicados apenas dentro da empresa ativa, pelo hash e pelo
  pipeline usado.
- Tarefas possuem índices iniciados pela empresa, adequados para consultas do
  Kanban por tenant.

### Empresa ativa

O middleware `empresas.middleware.EmpresaAtualMiddleware` é executado após a
autenticação. Ele:

1. localiza os vínculos ativos do usuário;
2. tenta restaurar a empresa escolhida anteriormente na sessão;
3. se não houver uma escolha válida, utiliza a primeira empresa ativa do
   usuário;
4. disponibiliza a empresa em `request.empresa`.

O endpoint `POST /empresas/selecionar/` permite trocar a empresa ativa apenas
para uma empresa à qual o usuário esteja vinculado. Parâmetros:

```text
empresa_id=<id da empresa>
next=<rota opcional para redirecionamento>
```

Como o endpoint usa a sessão Django, a requisição precisa estar autenticada e
incluir proteção CSRF quando chamada por um formulário do navegador.

### Isolamento nas telas e APIs

Os fluxos abaixo filtram registros por `request.empresa` no servidor, não
somente na interface:

- busca por placa;
- upload e deduplicação de documento;
- histórico, fila, detalhe, arquivo, reprocessamento e exclusão;
- listagem e detalhe de lotes;
- Kanban;
- atualização do status de uma tarefa.

Uma tarefa que pertence a outra empresa retorna `404` na API de atualização e
não sofre qualquer alteração.

### Admin Django

O mixin `EmpresaAdminMixin` restringe listagens no admin às empresas vinculadas
ao usuário administrativo. Ele também restringe os campos relacionais para que
um administrador de empresa não selecione acidentalmente contatos, tarefas,
usuários ou outros objetos de outro tenant. Superusuários preservam visão
global de plataforma.

### Workers e legado de atendimento

O worker de conversas continua podendo processar filas de todas as empresas,
pois é um processo confiável do servidor. Porém, todo registro que ele cria
(mensagem, documento recebido ou tarefa) recebe a empresa da conversa original.

O webhook legado da Meta permanece funcional e, até a integração WAHA ser
criada, registra seus eventos na Empresa padrão. A etapa de integração deverá
substituir essa decisão por mapeamento explícito de sessão WAHA para empresa.

### Novos cadastros

Um usuário criado após a migração recebe automaticamente uma empresa inicial
própria e um vínculo de administrador. Essa decisão impede que um cadastro novo
herde a Empresa padrão e veja dados antigos. Em produção, o próximo refinamento
recomendado é substituir o cadastro público por um fluxo de convite emitido
pelo administrador da empresa.

## Como testar

### Teste automatizado

```powershell
cd webapp
.\venv\Scripts\python.exe manage.py test --verbosity 1
.\venv\Scripts\python.exe manage.py check
```

Resultado esperado no estado atual:

```text
Ran 30 tests
OK
System check identified no issues
```

### Teste manual de isolamento de documentos

1. Crie dois usuários e duas empresas pelo Django Admin.
2. Vincule o primeiro usuário apenas à Empresa A e o segundo apenas à Empresa B.
3. Faça login como o primeiro usuário e envie um PDF.
4. Faça login como o segundo usuário.
5. Confirme que busca, histórico, lotes, URL de detalhe e URL de download não
   exibem o documento da Empresa A; as URLs devem retornar `404`.

### Teste manual de Kanban

1. Crie contato, serviço, conversa e tarefa para cada empresa pelo Admin.
2. Faça login com um usuário da Empresa A e abra `/atendimento/kanban/`.
3. Confirme que apenas os cards da Empresa A são exibidos.
4. Copie o UUID de uma tarefa da Empresa B e tente movê-la com a API autenticada
   da Empresa A.
5. O retorno esperado é `404`, e a tarefa da Empresa B deve manter o status
   original.

### Teste da troca de empresa

1. Vincule o mesmo usuário às Empresas A e B.
2. Faça login e envie um `POST` para `/empresas/selecionar/` com o ID da
   Empresa B.
3. Navegue pelo histórico e pelo Kanban.
4. Confirme que somente dados da Empresa B são mostrados.
5. Tente enviar o ID de uma empresa à qual o usuário não está vinculado.
   O retorno esperado é `403`.

## Checklist antes de produção

- [ ] Fazer backup do PostgreSQL.
- [ ] Executar `manage.py migrate` no ambiente de homologação.
- [ ] Conferir que não existem registros sem empresa.
- [ ] Criar pelo menos duas empresas e executar os testes manuais acima.
- [ ] Revisar usuários e vínculos atribuídos à Empresa padrão.
- [ ] Usar `DJANGO_DEBUG=0`, chave secreta forte e HTTPS.
- [ ] Configurar PostgreSQL; não operar múltiplos workers com SQLite.

## Próximas etapas

Implementado nas fases 4–8 (ver [`FASES_4_8_IMPLEMENTACAO.md`](FASES_4_8_IMPLEMENTACAO.md)):

1. API interna autenticada, idempotência, auditoria de eventos.
2. WAHA em homologação, webhooks e cliente de envio.
3. Workflow n8n de referência e checklist de piloto.
4. Análise documental por IA com revisão humana via API.

Refinamentos pendentes: ver [`REFINAMENTOS_PENDENTES.md`](REFINAMENTOS_PENDENTES.md).
