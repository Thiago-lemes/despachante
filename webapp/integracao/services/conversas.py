from datetime import timedelta

from django.utils import timezone

from atendimento.models import Contato, Conversa, Mensagem, Servico, Tarefa

from integracao.models import EventoAtendimento
from integracao.services.auditoria import registrar_evento
from integracao.services.deduplicacao import WebhookDuplicado, registrar_webhook


# Uma conversa segue ativa até ser encerrada. 'aguardando_humano' precisa entrar
# aqui: é o estado em que a tarefa do Kanban coloca a conversa, e sem ele cada
# nova mensagem do mesmo cliente abriria outra conversa e outro card.
ESTADOS_ATIVOS = [
    estado for estado in Conversa.Estado.values
    if estado != Conversa.Estado.ENCERRADA
]

# Conversa parada por dois dias é assunto encerrado: a próxima mensagem começa
# um atendimento novo, em vez de retomar um menu de anteontem.
HORAS_ATE_EXPIRAR = 48


def _expirou(conversa):
    """
    Só expira conversa que ainda está com o bot. Atendimento já nas mãos de uma
    pessoa não pode ser encerrado por silêncio do cliente.
    """
    if conversa.modo != Conversa.Modo.BOT:
        return False
    limite = timezone.now() - timedelta(hours=HORAS_ATE_EXPIRAR)
    return conversa.atualizada_em < limite


def obter_ou_criar_conversa(empresa, contato, servico=None):
    conversa = Conversa.objects.filter(
        empresa=empresa,
        contato=contato,
        estado__in=ESTADOS_ATIVOS,
    ).order_by('-atualizada_em').first()
    if conversa and _expirou(conversa):
        conversa.estado = Conversa.Estado.ENCERRADA
        conversa.save(update_fields=['estado', 'atualizada_em'])
        conversa = None
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
                               nome_contato='', telefone='', chat_id='',
                               conversa_id=None, ator='waha'):
    if wa_message_id:
        existente = Mensagem.objects.filter(
            empresa=empresa, wa_message_id=wa_message_id).first()
        if existente:
            return existente, False

    contato, _ = Contato.objects.get_or_create(
        empresa=empresa, wa_id=wa_id,
        defaults={
            'nome': nome_contato or '',
            'telefone': telefone or '',
            'chat_id': chat_id or '',
        },
    )
    # Nome, telefone e chat_id podem chegar só em mensagens posteriores.
    campos = []
    if nome_contato and contato.nome != nome_contato:
        contato.nome = nome_contato
        campos.append('nome')
    if telefone and not contato.telefone:
        contato.telefone = telefone
        campos.append('telefone')
    if chat_id and contato.chat_id != chat_id:
        contato.chat_id = chat_id
        campos.append('chat_id')
    if campos:
        contato.save(update_fields=campos)

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


def criar_tarefa(empresa, conversa_id, *, resumo_triagem='', origem='fluxo_completo',
                 assumir_por_humano=True):
    conversa = obter_conversa(empresa, conversa_id)
    if not conversa:
        return None
    if origem not in Tarefa.Origem.values:
        origem = Tarefa.Origem.FLUXO_COMPLETO
    # Sem resumo explícito, a primeira mensagem do cliente descreve melhor o
    # pedido do que qualquer texto genérico montado a partir do cadastro.
    if not resumo_triagem:
        primeira = Mensagem.objects.filter(
            conversa=conversa, direcao=Mensagem.Direcao.ENTRADA
        ).order_by('criada_em').values_list('conteudo', flat=True).first()
        resumo_triagem = (primeira or '').strip()

    resumo = resumo_triagem or 'Aguardando detalhes do cliente.'
    tarefa = Tarefa.objects.create(
        empresa=empresa,
        conversa=conversa,
        contato=conversa.contato,
        servico=conversa.servico,
        origem=origem,
        resumo_triagem=resumo,
        status=Tarefa.Status.ABERTA,
    )
    # O bot cria o card assim que o serviço é escolhido e segue conduzindo a
    # coleta de documentos — nesse caso a conversa ainda não passa para humano.
    if assumir_por_humano:
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
