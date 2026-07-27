from django.db.models.signals import pre_delete
from django.dispatch import receiver

from .models import Documento


@receiver(pre_delete, sender=Documento)
def remover_arquivo_fisico(sender, instance, **kwargs):
    if instance.arquivo:
        instance.arquivo.delete(save=False)
