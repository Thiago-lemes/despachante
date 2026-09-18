"""Quem atende quem: assumir, atribuir e responder.

O WhatsApp entrega tudo num balaio só — um número, uma conta, nenhum conceito
de atendente. A separação entre as pessoas da empresa é construída aqui.
"""
from django.db import transaction
from django.utils import timezone

from atendimento.models import Conversa, Tarefa
from atendimento.services.mensageria import anunciar_atendente, enviar_do_atendente
from integracao.models import EventoAtendimento
from integracao.services.auditoria import registrar_evento


def tarefa_aberta_da_conversa(conversa):
    """O card vivo daquela conversa — é ele que diz quem pode responder."""
    return Tarefa.objects.filter(
        conversa=conversa,
        status__in=[Tarefa.Status.ABERTA, Tarefa.Status.EM_ATENDIMENTO],
    ).order_by('-criada_em').first()


def pode_responder(conversa, usuario):
    tarefa = tarefa_aberta_da_conversa(conversa)
    return bool(
        tarefa
        and tarefa.status == Tarefa.Status.EM_ATENDIMENTO
        and tarefa.atendente_id == usuario.id
    )


def assumir_tarefa(tarefa, usuario, *, anunciar=True):
    """Tira o card da fila para um atendente. Devolve None se perdeu a corrida.

    O `UPDATE` condicional é a trava. Conferir e depois gravar são duas etapas,
    e entre elas cabe o clique do outro: dois atendentes passariam pela
    conferência antes de qualquer um gravar. Aqui quem chega depois não encontra
    a linha no estado esperado e altera zero linhas.
    """
    alteradas = Tarefa.objects.filter(
        pk=tarefa.pk,
        status=Tarefa.Status.ABERTA,
        atendente__isnull=True,
    ).update(
        status=Tarefa.Status.EM_ATENDIMENTO,
        atendente=usuario,
        assumida_em=timezone.now(),
    )
    if not alteradas:
        return None

    tarefa.refresh_from_db()
    _calar_bot(tarefa.conversa)
    registrar_evento(
        tarefa.empresa, EventoAtendimento.Tipo.TAREFA_ATRIBUIDA,
        conversa=tarefa.conversa, ator=usuario.username,
        payload={'tarefa_id': str(tarefa.id), 'assumida_por': usuario.username},
    )
    if anunciar:
        anunciar_atendente(tarefa.conversa, usuario)
    return tarefa


@transaction.atomic
def atribuir_tarefa(tarefa, destino, *, por, anunciar=True):
    """Passa um atendimento para outra pessoa, com rastro.

    Vale tanto para puxar para si o card de um colega quanto para entregá-lo a
    alguém — inclusive quando o dono anterior saiu da empresa. Transferência sem
    registro é a mesma coisa que sobrescrever.
    """
    anterior = tarefa.atendente
    if anterior and anterior.id == destino.id:
        return tarefa

    tarefa.atendente = destino
    tarefa.status = Tarefa.Status.EM_ATENDIMENTO
    if not tarefa.assumida_em:
        tarefa.assumida_em = timezone.now()
    tarefa.concluida_em = None
    tarefa.save(update_fields=[
        'atendente', 'status', 'assumida_em', 'concluida_em'])

    _calar_bot(tarefa.conversa)
    registrar_evento(
        tarefa.empresa, EventoAtendimento.Tipo.TAREFA_ATRIBUIDA,
        conversa=tarefa.conversa, ator=por.username,
        payload={
            'tarefa_id': str(tarefa.id),
            'de': anterior.username if anterior else None,
            'para': destino.username,
        },
    )
    if anunciar:
        anunciar_atendente(tarefa.conversa, destino, transferencia=True)
    return tarefa


def responder(conversa, usuario, texto):
    """Resposta do atendente ao cliente. Só o dono do card fala."""
    if not pode_responder(conversa, usuario):
        return False
    return enviar_do_atendente(conversa, usuario, texto)


def _calar_bot(conversa):
    """Conversa nas mãos de uma pessoa não recebe mais resposta automática."""
    if conversa.modo != Conversa.Modo.HUMANO:
        conversa.modo = Conversa.Modo.HUMANO
        conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
        conversa.save(update_fields=['modo', 'estado', 'atualizada_em'])
