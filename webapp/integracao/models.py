import hashlib
import secrets

from django.conf import settings
from django.db import models


class WahaSessao(models.Model):
    """Mapeia uma sessão WAHA para uma empresa (tenant)."""

    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.CASCADE, related_name='sessoes_waha')
    nome_sessao = models.CharField(max_length=100, unique=True)
    ativa = models.BooleanField(default=True)
    webhook_secret = models.CharField(max_length=128, blank=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'sessão WAHA'
        verbose_name_plural = 'sessões WAHA'

    def __str__(self):
        return f'{self.nome_sessao} → {self.empresa.nome}'

    def save(self, *args, **kwargs):
        if not self.webhook_secret:
            self.webhook_secret = secrets.token_hex(32)
        super().save(*args, **kwargs)


class WebhookRecebido(models.Model):
    """Registro idempotente de webhooks processados."""

    class Origem(models.TextChoices):
        WAHA = 'waha', 'WAHA'
        META = 'meta', 'Meta'
        N8N = 'n8n', 'n8n'

    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.CASCADE, related_name='webhooks_recebidos')
    origem = models.CharField(max_length=20, choices=Origem.choices)
    id_externo = models.CharField(max_length=200)
    payload_hash = models.CharField(max_length=64, blank=True)
    processado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['origem', 'id_externo', 'empresa'],
                name='webhook_idempotente_por_empresa',
            ),
        ]
        indexes = [
            models.Index(fields=['origem', 'id_externo']),
        ]

    @staticmethod
    def hash_payload(payload: bytes) -> str:
        return hashlib.sha256(payload).hexdigest()


class EventoAtendimento(models.Model):
    """Trilha de auditoria append-only para integrações e operações."""

    class Tipo(models.TextChoices):
        MENSAGEM_RECEBIDA = 'mensagem.recebida', 'Mensagem recebida'
        MENSAGEM_ENVIADA = 'mensagem.enviada', 'Mensagem enviada'
        CONVERSA_ESTADO = 'conversa.estado_alterado', 'Estado da conversa alterado'
        DOCUMENTO_RECEBIDO = 'documento.recebido', 'Documento recebido'
        DOCUMENTO_ANALISADO = 'documento.analisado', 'Documento analisado'
        DOCUMENTO_REVISADO = 'documento.revisado', 'Documento revisado'
        TAREFA_CRIADA = 'tarefa.criada', 'Tarefa criada'
        WEBHOOK_RECEBIDO = 'webhook.recebido', 'Webhook recebido'
        ERRO = 'erro', 'Erro'

    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.CASCADE, related_name='eventos_atendimento')
    conversa = models.ForeignKey(
        'atendimento.Conversa', null=True, blank=True, on_delete=models.SET_NULL,
        related_name='eventos')
    tipo = models.CharField(max_length=40, choices=Tipo.choices)
    ator = models.CharField(max_length=50, default='sistema')
    correlation_id = models.CharField(max_length=100, blank=True, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-criado_em']
        indexes = [
            models.Index(fields=['empresa', '-criado_em']),
            models.Index(fields=['tipo', '-criado_em']),
        ]

    def __str__(self):
        return f'{self.tipo} @ {self.criado_em:%Y-%m-%d %H:%M}'
