import uuid
from django.db import models
from django.conf import settings


class Contato(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='contatos')
    wa_id = models.CharField(max_length=20)
    nome = models.CharField(max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'wa_id'], name='contato_empresa_wa_id_unico'),
        ]

    def __str__(self):
        return f"{self.nome or 'Sem nome'} ({self.wa_id})"


class Servico(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='servicos')
    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'nome'], name='servico_empresa_nome_unico'),
        ]

    def __str__(self):
        return self.nome


class Conversa(models.Model):
    class Estado(models.TextChoices):
        TRIAGEM = 'triagem', 'Triagem'
        COLETANDO_DOCUMENTOS = 'coletando_documentos', 'Coletando documentos'
        AGUARDANDO_ANALISE = 'aguardando_analise', 'Aguardando análise'
        AGUARDANDO_HUMANO = 'aguardando_humano', 'Aguardando humano'
        ENCERRADA = 'encerrada', 'Encerrada'

    class Modo(models.TextChoices):
        BOT = 'bot', 'Bot'
        HUMANO = 'humano', 'Humano'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='conversas')
    contato = models.ForeignKey(Contato, on_delete=models.PROTECT)
    servico = models.ForeignKey(Servico, null=True, blank=True, on_delete=models.SET_NULL)
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.TRIAGEM)
    modo = models.CharField(max_length=10, choices=Modo.choices, default=Modo.BOT)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversa {self.id} — {self.contato} — {self.get_estado_display()}"


class Mensagem(models.Model):
    class Direcao(models.TextChoices):
        ENTRADA = 'entrada', 'Entrada'
        SAIDA = 'saida', 'Saída'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='mensagens')
    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    direcao = models.CharField(max_length=10, choices=Direcao.choices)
    conteudo = models.TextField()
    wa_message_id = models.CharField(max_length=100, blank=True, db_index=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_direcao_display()}: {self.conteudo[:50]}"


class DocumentoExigido(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='documentos_exigidos')
    servico = models.ForeignKey(Servico, on_delete=models.CASCADE, related_name='documentos_exigidos')
    tipo = models.CharField(max_length=100)
    obrigatorio = models.BooleanField(default=True)
    instrucoes = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} ({self.servico.nome})"


class DocumentoRecebido(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        APROVADO = 'aprovado', 'Aprovado'
        REPROVADO = 'reprovado', 'Reprovado'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='documentos_recebidos')
    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='documentos_recebidos')
    documento_exigido = models.ForeignKey(DocumentoExigido, on_delete=models.PROTECT)
    arquivo = models.FileField(upload_to='atendimento/documentos/', blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    motivo_reprovacao = models.TextField(blank=True)
    resultado = models.JSONField(default=dict, blank=True)
    analisado_em = models.DateTimeField(null=True, blank=True)
    erro_analise = models.TextField(blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='documentos_revisados')
    revisado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.documento_exigido.tipo} — {self.get_status_display()}"


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA = 'aberta', 'Aberta'
        EM_ATENDIMENTO = 'em_atendimento', 'Em atendimento'
        CONCLUIDA = 'concluida', 'Concluída'
        CANCELADA = 'cancelada', 'Cancelada'

    class Origem(models.TextChoices):
        FLUXO_COMPLETO = 'fluxo_completo', 'Fluxo completo'
        PEDIDO_ATENDENTE = 'pedido_atendente', 'Pedido de atendente'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='tarefas')
    conversa = models.ForeignKey(Conversa, on_delete=models.PROTECT)
    contato = models.ForeignKey(Contato, on_delete=models.PROTECT)
    servico = models.ForeignKey(Servico, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTA)
    origem = models.CharField(max_length=20, choices=Origem.choices)
    resumo_triagem = models.TextField()
    atendente = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criada_em = models.DateTimeField(auto_now_add=True)
    assumida_em = models.DateTimeField(null=True, blank=True)
    concluida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['empresa', 'status', '-criada_em'], name='atend_empresa_status_idx'),
            models.Index(fields=['empresa', 'contato'], name='atend_empresa_contato_idx'),
        ]

    def __str__(self):
        return f"Tarefa {str(self.id)[:8]} — {self.contato} — {self.get_status_display()}"
