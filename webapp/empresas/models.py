from django.conf import settings
from django.db import models


class Empresa(models.Model):
    """Organização que possui usuários, dados e canais de atendimento."""

    nome = models.CharField(max_length=150, unique=True)
    cnpj = models.CharField(max_length=14, unique=True, null=True, blank=True)
    ativa = models.BooleanField(default=True)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['nome']
        verbose_name = 'empresa'
        verbose_name_plural = 'empresas'

    def __str__(self):
        return self.nome


class EmpresaUsuario(models.Model):
    """Vínculo de um usuário com uma empresa e seu nível de acesso."""

    class Papel(models.TextChoices):
        ADMINISTRADOR = 'administrador', 'Administrador'
        ATENDENTE = 'atendente', 'Atendente'
        OPERADOR_DOCUMENTOS = 'operador_documentos', 'Operador de documentos'

    empresa = models.ForeignKey(
        Empresa, on_delete=models.CASCADE, related_name='usuario')
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name='empresas_vinculadas')
    papel = models.CharField(
        max_length=24, choices=Papel.choices, default=Papel.ATENDENTE)
    ativo = models.BooleanField(default=True)
    criado_em = models.DateTimeField(auto_now_add=True)
    atualizado_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'usuário da empresa'
        verbose_name_plural = 'usuários da empresa'
        constraints = [
            models.UniqueConstraint(
                fields=['empresa', 'usuario'],
                name='empresa_usuario_unico',
            ),
        ]
        indexes = [
            models.Index(fields=['usuario', 'ativo']),
            models.Index(fields=['empresa', 'ativo']),
        ]

    def __str__(self):
        return f'{self.usuario} — {self.empresa} ({self.get_papel_display()})'

    def pode_administrar(self):
        return self.ativo and self.papel == self.Papel.ADMINISTRADOR
