from django.conf import settings
from django.db import models


class Lote(models.Model):
    MODOS = [
        ('avulso', 'Envio avulso'),
        ('lote', 'Envio em lote'),
    ]

    modo = models.CharField(max_length=8, choices=MODOS)
    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.PROTECT, related_name='lotes_documentos')
    criado_em = models.DateTimeField(auto_now_add=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='lotes_documentos',
    )

    class Meta:
        ordering = ['-criado_em']

    def __str__(self):
        return f'Lote {self.pk} - {self.get_modo_display()}'

    def save(self, *args, **kwargs):
        if not self.empresa_id and self.enviado_por_id:
            from empresas.models import EmpresaUsuario
            self.empresa_id = EmpresaUsuario.objects.filter(
                usuario_id=self.enviado_por_id, ativo=True, empresa__ativa=True,
            ).order_by('empresa__nome').values_list('empresa_id', flat=True).first()
        super().save(*args, **kwargs)

    def resumo(self):
        contagens = {chave: 0 for chave, _ in Documento.STATUS}
        fallback = 0
        reutilizados = 0
        for item in self.itens.select_related('documento'):
            contagens[item.documento.status] += 1
            fallback += int(item.documento.usou_fallback)
            reutilizados += int(item.reutilizado)
        total = sum(contagens.values())
        finalizados = contagens['concluido'] + contagens['erro']
        return {
            **contagens,
            'total': total,
            'finalizados': finalizados,
            'fallback': fallback,
            'reutilizados': reutilizados,
            'finalizado': total > 0 and total == finalizados,
        }


class Documento(models.Model):
    STATUS = [
        ('aguardando', 'Na fila'),
        ('processando', 'Processando'),
        ('concluido', 'Concluido'),
        ('erro', 'Erro'),
    ]
    PIPELINES = [
        ('gemini', 'Gemini visual'),
        ('openai', 'OpenAI visual'),
    ]

    arquivo = models.FileField('PDF', upload_to='uploads/%Y/%m/')
    empresa = models.ForeignKey(
        'empresas.Empresa', on_delete=models.PROTECT, related_name='documentos')
    hash_sha256 = models.CharField(max_length=64, blank=True, db_index=True)
    enviado_em = models.DateTimeField('enviado em', auto_now_add=True)
    enviado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, verbose_name='enviado por', related_name='documentos',
    )
    pipeline = models.CharField(max_length=12, choices=PIPELINES, default='gemini')
    provedor_utilizado = models.CharField(max_length=20, blank=True)
    modelo_utilizado = models.CharField(max_length=80, blank=True)
    usou_fallback = models.BooleanField(default=False)
    motivo_fallback = models.TextField(blank=True)
    status = models.CharField(max_length=12, choices=STATUS, default='aguardando')
    tentativas = models.PositiveSmallIntegerField(default=0)
    processamento_iniciado_em = models.DateTimeField(null=True, blank=True)
    processamento_finalizado_em = models.DateTimeField(null=True, blank=True)
    erro = models.TextField(blank=True)
    resultado = models.JSONField(null=True, blank=True)

    # Campos denormalizados para busca e listagem.
    placa = models.CharField(max_length=7, blank=True, db_index=True)
    placa_valida = models.BooleanField('placa válida', default=False)
    processo = models.CharField(max_length=20, blank=True, db_index=True)
    renavam = models.CharField(max_length=14, blank=True)
    proprietario = models.CharField('proprietário', max_length=120, blank=True)

    class Meta:
        ordering = ['-enviado_em']
        verbose_name = 'documento'
        indexes = [models.Index(
            fields=['empresa', 'hash_sha256', 'pipeline'],
            name='documentos_empresa_hash_idx',
        )]

    def __str__(self):
        return f'{self.placa or "sem placa"} - {self.nome_arquivo}'

    def save(self, *args, **kwargs):
        if not self.empresa_id and self.enviado_por_id:
            from empresas.models import EmpresaUsuario
            self.empresa_id = EmpresaUsuario.objects.filter(
                usuario_id=self.enviado_por_id, ativo=True, empresa__ativa=True,
            ).order_by('empresa__nome').values_list('empresa_id', flat=True).first()
        super().save(*args, **kwargs)

    @property
    def nome_arquivo(self):
        return self.arquivo.name.rsplit('/', 1)[-1]


class ItemLote(models.Model):
    lote = models.ForeignKey(Lote, on_delete=models.CASCADE, related_name='itens')
    documento = models.ForeignKey(
        Documento, on_delete=models.CASCADE, related_name='itens_lote')
    nome_original = models.CharField(max_length=255)
    ordem = models.PositiveSmallIntegerField(default=0)
    reutilizado = models.BooleanField(default=False)

    class Meta:
        ordering = ['ordem', 'pk']
        constraints = [
            models.UniqueConstraint(fields=['lote', 'ordem'], name='item_lote_ordem_unica'),
        ]

    def __str__(self):
        return self.nome_original
