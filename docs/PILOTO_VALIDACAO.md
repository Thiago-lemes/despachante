# Checklist — validação com empresa piloto (fase 7)

Use este roteiro antes de liberar o fluxo WhatsApp para outras empresas.

## Pré-requisitos

- [ ] Migrações aplicadas (`manage.py migrate`)
- [ ] `INTEGRACAO_API_TOKEN` configurado
- [ ] Empresa piloto criada no Admin
- [ ] `WahaSessao` criada (`nome_sessao=piloto`, empresa piloto)
- [ ] WAHA em homologação (`docker compose -f deploy/docker-compose.homolog.yml up -d`)
- [ ] Sessão WAHA autenticada (QR Code escaneado)
- [ ] Worker de conversas ativo (`processar_conversas`)

## Teste 1 — Webhook WAHA → Django

1. Envie mensagem de texto para o número da sessão piloto.
2. Confirme no Admin:
   - [ ] `WebhookRecebido` registrado (sem duplicata em reenvio)
   - [ ] `Contato` criado com `wa_id` correto
   - [ ] `Mensagem` de entrada salva
   - [ ] `EventoAtendimento` tipo `mensagem.recebida`

## Teste 2 — API interna (n8n ou curl)

```powershell
$headers = @{
  Authorization = "Bearer SEU_TOKEN"
  "X-Empresa-Id" = "ID_EMPRESA"
  "Content-Type" = "application/json"
}
Invoke-RestMethod -Method POST -Uri "http://127.0.0.1:8000/api/v1/integracao/mensagens/" `
  -Headers $headers -Body '{"wa_id":"5511999999999","conteudo":"teste api"}'
```

- [ ] Retorna `201` com `conversa_id`
- [ ] Segunda chamada com mesmo `wa_message_id` retorna `200` e `criada: false`

## Teste 3 — Triagem e resposta (n8n)

1. Importe `n8n/workflows/mensagem-recebida.json`
2. Configure variáveis de ambiente no n8n
3. Envie mensagem contendo "licenciamento"
4. Confirme:
   - [ ] Cliente recebe resposta automática no WhatsApp
   - [ ] Mensagem de saída registrada no Django
   - [ ] Tarefa criada (`EventoAtendimento` tipo `tarefa.criada`)

## Teste 4 — Kanban

1. Login com usuário da empresa piloto
2. Abra `/atendimento/kanban/`
3. Confirme:
   - [ ] Card da tarefa piloto visível
   - [ ] Mover card funciona
   - [ ] Usuário de outra empresa **não** vê o card

## Teste 5 — Documento e análise (fase 8)

1. Crie `Servico`, `DocumentoExigido` e conversa no Admin
2. Registre documento via API ou upload manual no `DocumentoRecebido`
3. Execute `manage.py processar_conversas --once` ou POST `/analisar/`
4. Confirme:
   - [ ] `resultado` JSON preenchido (placa, processo, etc.)
   - [ ] `analisado_em` preenchido
5. Revisão humana:

```json
PATCH /api/v1/integracao/documentos-recebidos/<id>/revisao/
{"aprovado": true}
```

- [ ] `status` = `aprovado`, `revisado_em` preenchido
- [ ] `EventoAtendimento` tipo `documento.revisado`

## Teste 6 — Isolamento entre empresas

- [ ] API com `X-Empresa-Id` errado não acessa conversas de outra empresa
- [ ] Webhook da sessão A não grava dados na empresa B

## Critério de go-live gradual

- [ ] Todos os testes acima passaram em homologação
- [ ] Backup do banco realizado
- [ ] `WAHA_WEBHOOK_VERIFICAR_ASSINATURA=1` em produção
- [ ] Monitoramento básico (logs WAHA + `EventoAtendimento`)
- [ ] Plano de rollback documentado

## Rollback

1. Desativar workflow n8n
2. Parar sessão WAHA piloto
3. Manter Django operando só com upload manual/Kanban existente
