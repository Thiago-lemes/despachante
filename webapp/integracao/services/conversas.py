from atendimento.models import Contato, Conversa, Mensagem, Servico, Tarefa
from django.utils import timezone

from integracao.models import EventoAtendimento
from integracao.services.auditoria import registrar_evento
from integracao.services.deduplicacao import WebhookDuplicado, registrar_webhook


ESTADOS_ATIVOS = [
    Conversa.Estado.TRIAGEM,
    Conversa.Estado.COLETANDO_DOCUMENTOS,
    Conversa.Estado.AGUARDANDO_ANALISE,
]


def obter_ou_criar_conversa(empresa, contato, servico=None):
    conversa = Conversa.objects.filter(
        empresa=empresa,
        contato=contato,
        estado__in=ESTADOS_ATIVOS,
    ).order_by('-atualizada_em').first()
    if conversa:
        return conversa, False
    conversa = Conversa.objects.create(
        empresa=empresa,
        contato=contato,
        servico=servico,
        estado=Conversa.Estado.TRIAGEM,
        modo=Conversa.Modo.BOT,
    )
    return conversa, True


def registrar_mensagem_entrada(empresa, *, wa_id, conteudo, wa_message_id='',
                               nome_contato='', conversa_id=None, ator='waha'):
    if wa_message_id:
        existente = Mensagem.objects.filter(
            empresa=empresa, wa_message_id=wa_message_id).first()
        if existente:
            return existente, False

    contato, _ = Contato.objects.get_or_create(
        empresa=empresa, wa_id=wa_id,
        defaults={'nome': nome_contato or ''},
    )
    if nome_contato and not contato.nome:
        contato.nome = nome_contato
        contato.save(update_fields=['nome'])

    if conversa_id:
        conversa = Conversa.objects.filter(id=conversa_id, empresa=empresa).first()
        if not conversa:
            raise ValueError('Conversa não encontrada para esta empresa.')
    else:
        conversa, _ = obter_ou_criar_conversa(empresa, contato)

    mensagem = Mensagem.objects.create(
        empresa=empresa,
        conversa=conversa,
        direcao=Mensagem.Direcao.ENTRADA,
        conteudo=conteudo,
        wa_message_id=wa_message_id or '',
    )
    registrar_evento(
        empresa, EventoAtendimento.Tipo.MENSAGEM_RECEBIDA,
        conversa=conversa, ator=ator,
        correlation_id=wa_message_id,
        payload={'wa_id': wa_id, 'conteudo': conteudo[:500]},
    )
    return mensagem, True


def registrar_mensagem_saida(empresa, conversa, conteudo, *, ator='n8n',
                             wa_message_id=''):
    mensagem = Mensagem.objects.create(
        empresa=empresa,
        conversa=conversa,
        direcao=Mensagem.Direcao.SAIDA,
        conteudo=conteudo,
        wa_message_id=wa_message_id or '',
    )
    registrar_evento(
        empresa, EventoAtendimento.Tipo.MENSAGEM_ENVIADA,
        conversa=conversa, ator=ator,
        payload={'conteudo': conteudo[:500]},
    )
    return mensagem


def obter_conversa(empresa, conversa_id):
    return Conversa.objects.filter(id=conversa_id, empresa=empresa).select_related(
        'contato', 'servico').first()


def atualizar_conversa(empresa, conversa_id, *, estado=None, modo=None, servico_id=None):
    conversa = obter_conversa(empresa, conversa_id)
    if not conversa:
        return None
    alteracoes = {}
    if estado and estado in Conversa.Estado.values:
        alteracoes['estado'] = estado
    if modo and modo in Conversa.Modo.values:
        alteracoes['modo'] = modo
    if servico_id is not None:
        servico = Servico.objects.filter(id=servico_id, empresa=empresa).first()
        if servico:
            alteracoes['servico'] = servico
    if not alteracoes:
        return conversa
    for campo, valor in alteracoes.items():
        setattr(conversa, campo, valor)
    conversa.save()
    registrar_evento(
        empresa, EventoAtendimento.Tipo.CONVERSA_ESTADO,
        conversa=conversa, ator='n8n',
        payload=alteracoes,
    )
    return conversa


def criar_tarefa(empresa, conversa_id, *, resumo_triagem='', origem='fluxo_completo'):
    conversa = obter_conversa(empresa, conversa_id)
    if not conversa:
        return None
    if origem not in Tarefa.Origem.values:
        origem = Tarefa.Origem.FLUXO_COMPLETO
    resumo = resumo_triagem or (
        f'Cliente {conversa.contato.nome or conversa.contato.wa_id} — '
        f'{conversa.servico.nome if conversa.servico else "serviço indefinido"}'
    )
    tarefa = Tarefa.objects.create(
        empresa=empresa,
        conversa=conversa,
        contato=conversa.contato,
        servico=conversa.servico,
        origem=origem,
        resumo_triagem=resumo,
        status=Tarefa.Status.ABERTA,
    )
    conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
    conversa.modo = Conversa.Modo.HUMANO
    conversa.save(update_fields=['estado', 'modo', 'atualizada_em'])
    registrar_evento(
        empresa, EventoAtendimento.Tipo.TAREFA_CRIADA,
        conversa=conversa, ator='n8n',
        payload={'tarefa_id': str(tarefa.id), 'resumo': resumo[:300]},
    )
    return tarefa


def serializar_conversa(conversa):
    return {
        'id': conversa.id,
        'estado': conversa.estado,
        'modo': conversa.modo,
        'contato': {
            'id': conversa.contato_id,
            'wa_id': conversa.contato.wa_id,
            'nome': conversa.contato.nome,
        },
        'servico': {
            'id': conversa.servico_id,
            'nome': conversa.servico.nome,
        } if conversa.servico else None,
        'criada_em': conversa.criada_em.isoformat(),
        'atualizada_em': conversa.atualizada_em.isoformat(),
    }


def processar_webhook_idempotente(empresa, origem, id_externo, payload: bytes):
    try:
        return registrar_webhook(empresa, origem, id_externo, payload)
    except WebhookDuplicado:
        return None
