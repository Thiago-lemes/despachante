from integracao.models import EventoAtendimento


def registrar_evento(empresa, tipo, *, conversa=None, ator='sistema',
                     correlation_id='', payload=None):
    return EventoAtendimento.objects.create(
        empresa=empresa,
        conversa=conversa,
        tipo=tipo,
        ator=ator,
        correlation_id=correlation_id or '',
        payload=payload or {},
    )
