"""Motor do chatbot de atendimento no WhatsApp — menu numerado.

Roda **por evento**: é chamado pelo webhook do WAHA logo depois de registrar a
mensagem de entrada, nunca por varredura periódica. É isso que garante que cada
mensagem do cliente gere no máximo uma resposta.
"""
import logging
import re

from atendimento.models import (
    Conversa,
    DocumentoRecebido,
    Mensagem,
    Servico,
    Tarefa,
)
from integracao.models import EventoAtendimento, WahaSessao
from integracao.services.auditoria import registrar_evento
from integracao.services.conversas import criar_tarefa, registrar_mensagem_saida
from integracao.services.waha_client import enviar_texto

logger = logging.getLogger(__name__)

# Depois de três respostas que o menu não reconhece, insistir só irrita:
# o cliente vai para um atendente.
MAX_TENTATIVAS_INVALIDAS = 3

# Palavras que tiram o cliente do fluxo automático em qualquer etapa.
PEDIDO_DE_ATENDENTE = re.compile(r'\b(atendente|humano|pessoa)\b', re.IGNORECASE)


def _protocolo(tarefa):
    return str(tarefa.id)[:8].upper()


def _tarefa_em_aberto(conversa):
    return Tarefa.objects.filter(
        conversa=conversa,
        status__in=[Tarefa.Status.ABERTA, Tarefa.Status.EM_ATENDIMENTO],
    ).order_by('-criada_em').first()


def enviar_resposta_bot(conversa, texto):
    """Envia texto ao cliente pelo WAHA e registra a saída com auditoria."""
    sessao = WahaSessao.objects.filter(
        empresa=conversa.empresa, ativa=True).first()
    if not sessao:
        logger.error('Nenhuma sessão WAHA ativa para a empresa %s',
                     conversa.empresa_id)
        return False

    destino = conversa.contato.chat_id or conversa.contato.wa_id
    resultado = enviar_texto(
        sessao=sessao.nome_sessao, chat_id=destino, texto=texto)
    if not resultado['success']:
        logger.error('Falha ao enviar resposta do bot: %s',
                     resultado.get('error'))
        return False

    registrar_mensagem_saida(
        conversa.empresa, conversa, texto, ator='bot',
        wa_message_id=str((resultado.get('data') or {}).get('id', '')),
    )
    return True


def servicos_do_menu(empresa):
    return list(Servico.objects.filter(empresa=empresa, ativo=True).order_by('nome'))


def montar_menu(conversa, servicos, *, saudacao=True):
    linhas = []
    if saudacao:
        linhas.append(f'Olá! Sou o assistente virtual da {conversa.empresa.nome}.')
        linhas.append('')
    linhas.append('Digite o número do serviço:')
    linhas.extend(f'{i} - {servico.nome}' for i, servico in enumerate(servicos, 1))
    linhas.append(f'{len(servicos) + 1} - Falar com um atendente')
    return '\n'.join(linhas)


def _opcao_escolhida(texto):
    """
    Só um número isolado conta como escolha. Aceitar dígitos soltos no meio do
    texto faria 'quero a 2ª via do CRLV' virar a opção 2.
    """
    correspondencia = re.fullmatch(r'(\d{1,2})[\)\.\-º°]?', (texto or '').strip())
    return int(correspondencia.group(1)) if correspondencia else None


def processar_mensagem(conversa, mensagem, *, tem_midia=False):
    """
    Ponto de entrada do bot para uma mensagem recém-registrada.
    Devolve True quando alguma resposta foi enviada ao cliente.
    """
    if conversa.modo != Conversa.Modo.BOT:
        return False

    if PEDIDO_DE_ATENDENTE.search(mensagem.conteudo or ''):
        return _transferir_para_humano(conversa, motivo='pedido_do_cliente')

    if conversa.estado == Conversa.Estado.TRIAGEM:
        return _processar_triagem(conversa, mensagem)
    if conversa.estado == Conversa.Estado.COLETANDO_DOCUMENTOS:
        return _processar_coleta(conversa, mensagem, tem_midia)
    return False


def _processar_triagem(conversa, mensagem):
    servicos = servicos_do_menu(conversa.empresa)
    if not servicos:
        # Sem catálogo cadastrado não há menu a oferecer. Entregar a um humano
        # é melhor do que deixar o cliente sem resposta.
        return _transferir_para_humano(conversa, motivo='sem_servicos_cadastrados')

    ja_ofereceu_menu = conversa.mensagens.filter(
        direcao=Mensagem.Direcao.SAIDA).exists()
    if not ja_ofereceu_menu:
        return enviar_resposta_bot(conversa, montar_menu(conversa, servicos))

    opcao = _opcao_escolhida(mensagem.conteudo)
    if opcao == len(servicos) + 1:
        return _transferir_para_humano(conversa, motivo='pedido_do_cliente')
    if opcao and 1 <= opcao <= len(servicos):
        return _confirmar_servico(conversa, servicos[opcao - 1])
    return _nao_entendi(conversa, servicos)


def _nao_entendi(conversa, servicos):
    conversa.tentativas_invalidas += 1
    conversa.save(update_fields=['tentativas_invalidas', 'atualizada_em'])

    if conversa.tentativas_invalidas >= MAX_TENTATIVAS_INVALIDAS:
        return _transferir_para_humano(conversa, motivo='tentativas_esgotadas')

    return enviar_resposta_bot(
        conversa,
        'Não entendi. ' + montar_menu(conversa, servicos, saudacao=False),
    )


def _confirmar_servico(conversa, servico):
    """Escolher o número já é a confirmação: é aqui que o card nasce."""
    conversa.servico = servico
    conversa.tentativas_invalidas = 0
    conversa.save(update_fields=['servico', 'tentativas_invalidas', 'atualizada_em'])

    documentos = list(servico.documentos_exigidos.order_by('id'))

    tarefa = criar_tarefa(
        conversa.empresa, conversa.id,
        resumo_triagem=f'{servico.nome} — solicitado pelo menu do WhatsApp.',
        origem=Tarefa.Origem.FLUXO_COMPLETO,
        # Havendo documentos a pedir, o bot continua conduzindo a conversa.
        assumir_por_humano=not documentos,
    )
    conversa.refresh_from_db()

    if not documentos:
        texto = (
            f'Perfeito! Registrei seu pedido de *{servico.nome}*.\n\n'
            'Um atendente vai falar com você por aqui.'
        )
        if tarefa:
            texto += f'\nProtocolo: *{_protocolo(tarefa)}*'
        return enviar_resposta_bot(conversa, texto)

    conversa.estado = Conversa.Estado.COLETANDO_DOCUMENTOS
    conversa.save(update_fields=['estado', 'atualizada_em'])

    primeiro = documentos[0]
    return enviar_resposta_bot(conversa, (
        f'Perfeito! Para *{servico.nome}* vou precisar de alguns documentos.\n\n'
        f'Primeiro: *{primeiro.tipo}*\n{primeiro.instrucoes}\n\n'
        'Envie a foto ou o arquivo aqui mesmo.'
    ))


def _documentos_faltando(conversa):
    if not conversa.servico:
        return []
    exigidos = list(conversa.servico.documentos_exigidos.order_by('id'))
    recebidos = set(
        conversa.documentos_recebidos
        .exclude(status=DocumentoRecebido.Status.REPROVADO)
        .values_list('documento_exigido_id', flat=True)
    )
    return [doc for doc in exigidos if doc.id not in recebidos]


def _processar_coleta(conversa, mensagem, tem_midia):
    faltando = _documentos_faltando(conversa)
    if not faltando:
        return _concluir_coleta(conversa)

    atual = faltando[0]
    if not tem_midia:
        # Texto durante a coleta é quase sempre dúvida: repete a instrução em
        # vez de dar o documento por recebido.
        return enviar_resposta_bot(conversa, (
            f'Ainda preciso de *{atual.tipo}*.\n{atual.instrucoes}\n\n'
            'Envie a foto ou o arquivo aqui. '
            'Se preferir, responda ATENDENTE para falar com uma pessoa.'
        ))

    DocumentoRecebido.objects.create(
        empresa=conversa.empresa,
        conversa=conversa,
        documento_exigido=atual,
        status=DocumentoRecebido.Status.PENDENTE,
    )
    registrar_evento(
        conversa.empresa, EventoAtendimento.Tipo.DOCUMENTO_RECEBIDO,
        conversa=conversa, ator='bot',
        payload={'tipo': atual.tipo, 'wa_message_id': mensagem.wa_message_id},
    )
    _atualizar_andamento_no_card(conversa)

    restantes = faltando[1:]
    if not restantes:
        return _concluir_coleta(conversa)

    proximo = restantes[0]
    return enviar_resposta_bot(conversa, (
        f'*{atual.tipo}* recebido!\n\n'
        f'Agora preciso de: *{proximo.tipo}*\n{proximo.instrucoes}'
    ))


def _concluir_coleta(conversa):
    tarefa = _tarefa_em_aberto(conversa)
    _atualizar_andamento_no_card(conversa)

    conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
    conversa.modo = Conversa.Modo.HUMANO
    conversa.save(update_fields=['estado', 'modo', 'atualizada_em'])

    texto = ('Recebi todos os documentos!\n\n'
             'Um atendente vai analisar e falar com você por aqui.')
    if tarefa:
        texto += f'\nProtocolo: *{_protocolo(tarefa)}*'
    return enviar_resposta_bot(conversa, texto)


def _atualizar_andamento_no_card(conversa):
    """Mantém no card do Kanban em que ponto da coleta o cliente está."""
    tarefa = _tarefa_em_aberto(conversa)
    if not tarefa or not conversa.servico:
        return
    total = conversa.servico.documentos_exigidos.count()
    recebidos = conversa.documentos_recebidos.exclude(
        status=DocumentoRecebido.Status.REPROVADO).count()
    # A primeira linha é o pedido; o andamento vive sozinho na segunda.
    pedido = tarefa.resumo_triagem.split('\n')[0]
    tarefa.resumo_triagem = f'{pedido}\nDocumentos: {recebidos} de {total}.'
    tarefa.save(update_fields=['resumo_triagem'])


def _transferir_para_humano(conversa, *, motivo):
    tarefa = _tarefa_em_aberto(conversa)
    if not tarefa:
        tarefa = criar_tarefa(
            conversa.empresa, conversa.id,
            origem=Tarefa.Origem.FLUXO_COMPLETO,
        )
        conversa.refresh_from_db()

    if conversa.modo != Conversa.Modo.HUMANO:
        conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
        conversa.modo = Conversa.Modo.HUMANO
        conversa.save(update_fields=['estado', 'modo', 'atualizada_em'])

    registrar_evento(
        conversa.empresa, EventoAtendimento.Tipo.CONVERSA_ESTADO,
        conversa=conversa, ator='bot',
        payload={'transferido_para_humano': motivo},
    )

    texto = 'Vou chamar um atendente para falar com você por aqui. Só um momento.'
    if tarefa:
        texto += f'\nProtocolo: *{_protocolo(tarefa)}*'
    return enviar_resposta_bot(conversa, texto)
