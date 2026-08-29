# Proposta de fluxo SaaS — onboarding de despachantes e equipes

**Projeto:** Despachante  
**Versão:** 1.0  
**Data:** agosto/2026  
**Status:** proposta para validação

---

## 1. Contexto

O sistema já possui **isolamento de dados por empresa** (multiempresa): documentos, lotes, contatos, conversas e tarefas ficam separados por organização. Essa base técnica está pronta.

O que ainda **não está definido como produto** é como uma nova despachante entra no sistema e como os funcionários passam a usar a plataforma. Hoje isso gera confusão operacional e não reflete um modelo SaaS claro.

Este documento descreve o **fluxo recomendado** para transformar o cadastro em um onboarding B2B adequado ao negócio.

---

## 2. Situação atual (resumo)

| Aspecto | Como funciona hoje |
| --- | --- |
| Isolamento por empresa | Funcionando |
| Cadastro público (`/cadastro/`) | Qualquer pessoa cria conta e recebe automaticamente uma empresa pessoal (ex.: "Conta de joao #5") |
| Entrada em empresa existente | Depende de vínculo manual no Admin |
| Papéis (admin, atendente, operador) | Existem no modelo, mas sem fluxo de gestão na interface |
| Gestão da plataforma (operador do SaaS) | Apenas via superusuário Django |

**Problema:** o cadastro atual não distingue **"quero abrir minha despachante"** de **"quero entrar na empresa onde trabalho"**. Para SaaS, essas são jornadas diferentes e precisam de fluxos separados.

---

## 3. Modelo recomendado

Adotar arquitetura em **três camadas de atores**:

```text
Plataforma (operador do SaaS)
    └── Empresa / Despachante (tenant — cada cliente)
            └── Usuários (administrador, atendentes, operadores)
```

### 3.1 Operador da plataforma

Responsável por:

- provisionar ou liberar novos clientes (no início);
- visualizar e gerenciar todas as empresas;
- desativar empresas inadimplentes ou encerradas;
- (futuro) planos, limites, integrações globais.

### 3.2 Administrador da despachante

Primeiro usuário da empresa. Responsável por:

- criar e configurar a despachante no sistema;
- convidar ou aprovar funcionários;
- gerenciar papéis e acessos da equipe.

### 3.3 Funcionários

Usuários que **entram em uma empresa já existente**, sem criar tenant novo.

---

## 4. Fluxos propostos

### 4.1 Criar uma nova despachante (nascimento do tenant)

**Quem usa:** dono, sócio ou responsável pela operação.

**Fluxo:**

1. Acessa a opção **"Criar minha despachante"** (não um cadastro genérico).
2. Informa dados da empresa:
   - Nome fantasia / razão social
   - CNPJ
   - Dados de contato (e-mail, telefone — conforme necessidade)
3. Cria a conta do administrador (nome, e-mail, senha).
4. O sistema cria:
   - registro da **Empresa**;
   - vínculo do usuário como **administrador** ativo.
5. O usuário entra direto no sistema, já na empresa correta.

**Regras de negócio:**

- CNPJ único por empresa (não permitir duplicata).
- Se o CNPJ já existir, orientar o usuário a **solicitar acesso** à empresa existente, em vez de criar outra.
- Empresa nova pode iniciar ativa imediatamente (self-service) ou aguardar aprovação da plataforma (modo assistido — ver seção 6).

---

### 4.2 Entrar em uma despachante existente (funcionários)

Dois caminhos complementares:

#### Opção A — Convite (recomendado como principal)

1. Administrador gera convite (link ou código, com validade).
2. Funcionário acessa o link, cria conta (ou faz login se já tiver).
3. Sistema vincula automaticamente à empresa correta, com papel definido no convite.
4. Acesso liberado imediatamente.

**Vantagens:** mais seguro, simples, sem depender de CNPJ público.

#### Opção B — Solicitação por CNPJ + aprovação

1. Funcionário se cadastra e informa o CNPJ da empresa.
2. Sistema localiza a empresa e registra **pedido de acesso pendente**.
3. Administrador da empresa aprova ou recusa.
4. Após aprovação, o vínculo é criado e o acesso é liberado.

**Enquanto pendente:** usuário vê apenas tela de "aguardando aprovação", **sem acesso a dados** da empresa.

**Vantagens:** escala melhor quando a equipe cresce sem convites individuais.

---

### 4.3 Tela de cadastro unificada (proposta de UX)

```text
/cadastro/
  ├── Criar nova despachante
  │     → dados da empresa + conta do administrador
  │
  └── Entrar em uma despachante existente
        → convite (link/código)
        → ou solicitar acesso informando CNPJ
```

O cadastro atual genérico seria **substituído** por essa escolha explícita de intenção.

---

## 5. O que deixa de existir

| Comportamento atual | Mudança proposta |
| --- | --- |
| Todo cadastro cria empresa automática ("Conta de usuário #N") | Removido para cadastros de funcionário |
| Funcionário depende de vínculo manual no Admin | Substituído por convite ou aprovação |
| Cadastro público sem distinção de papel | Separado em "criar empresa" vs "entrar em empresa" |

Usuários e dados legados na **Empresa padrão** (migração) permanecem; o novo fluxo vale para cadastros e empresas novas.

---

## 6. Estratégia de implantação (recomendação híbrida)

### Fase 1 — MVP (primeiros clientes)

- Provisionamento manual pela plataforma (Admin) quando necessário.
- Fluxo **"Criar minha despachante"** self-service.
- Fluxo de **convite** para funcionários.
- Desativação do cadastro que cria empresa fantasma.

**Objetivo:** operação clara com poucos clientes, sem depender só do Admin interno.

### Fase 2 — Autonomia da empresa

- Solicitação de acesso por CNPJ com fila de aprovação.
- Tela de gestão de usuários para o administrador da despachante (sem Django Admin).
- Seleção de empresa na interface (quem pertence a mais de uma).

### Fase 3 — Plataforma SaaS completa

- Planos, trial, cobrança e suspensão automática.
- Painel do operador da plataforma (além do Django Admin).
- Integração WhatsApp (WAHA) por empresa, com sessão e webhooks por tenant.

---

## 7. Regras e decisões a validar

Antes da implementação, confirmar:

| # | Decisão | Opções |
| --- | --- | --- |
| 1 | Nova despachante é liberada na hora ou precisa de aprovação da plataforma? | Self-service imediato / Aprovação manual (início) |
| 2 | CNPJ é obrigatório na criação da empresa? | Sim (recomendado) / Não |
| 3 | Funcionário entra principalmente por convite ou por CNPJ? | Convite primeiro; CNPJ na Fase 2 |
| 4 | Quem pode convidar e aprovar? | Apenas administrador |
| 5 | Papel padrão do funcionário convidado | Atendente (ajustável por convite) |
| 6 | Cadastro público permanece aberto? | Sim, com as duas opções / Fechado (só convite) |

---

## 8. Benefícios esperados

- **Clareza:** cada usuário sabe se está abrindo empresa ou entrando em uma.
- **Segurança:** ninguém acessa dados de outra empresa sem vínculo aprovado.
- **Escalabilidade:** self-service para novas despachantes; convites e aprovações para equipes.
- **Alinhamento com SaaS:** base pronta para planos, billing e gestão centralizada depois.

---

## 9. Fora do escopo desta entrega

Itens já previstos em roadmap técnico, mas não cobertos por este fluxo de onboarding:

- API interna, auditoria de eventos e armazenamento seguro de mídia.
- WAHA, sessão por empresa e webhooks assinados.
- Workflows n8n (triagem, documentos, tarefas).
- Análise documental por IA com revisão humana.

Para detalhes do que já foi implementado em multiempresa, ver [`IMPLEMENTACAO_MULTIEMPRESA.md`](IMPLEMENTACAO_MULTIEMPRESA.md).

---

## 10. Próximo passo

1. Validar este fluxo e as decisões da seção 7.
2. Implementar a **Fase 1** (criar despachante + convite + remoção do cadastro automático).
3. Testar com duas empresas de homologação antes de produção.
