from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Empresa, EmpresaUsuario


@receiver(post_save, sender=get_user_model())
def criar_empresa_inicial_para_novo_usuario(sender, instance, created, **kwargs):
    """Evita que um cadastro novo herde dados de outra empresa."""
    if not created:
        return
    empresa = Empresa.objects.create(nome=f'Conta de {instance.username} #{instance.pk}')
    EmpresaUsuario.objects.create(
        empresa=empresa,
        usuario=instance,
        papel=EmpresaUsuario.Papel.ADMINISTRADOR,
    )
