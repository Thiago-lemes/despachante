"""Motor do chatbot de atendimento no WhatsApp — menu numerado.

Roda **por evento**: é chamado pelo webhook do WAHA logo depois de registrar a
mensagem de entrada, nunca por varredura periódica. É isso que garante que cada
mensagem do cliente gere no máximo uma resposta.
"""
import logging
import re

from atendimento.models import (
    ConfiguracaoBot,
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

# Depois de três respostas que o menu não reconhece, insistir só irrita: o
# cliente vai para um atendente. É o padrão — cada empresa ajusta o número em
# ConfiguracaoBot, na tela do chatbot.
MAX_TENTATIVAS_INVALIDAS = 3

# Palavras que tiram o cliente do fluxo automático em qualquer etapa. Também é
# padrão: a lista efetiva vem de ConfiguracaoBot.regex_atendente().
PEDIDO_DE_ATENDENTE = re.compile(r'\b(atendente|humano|pessoa)\b', re.IGNORECASE)

# Os textos da coleta ficam aqui, e não embutidos nas funções, porque a tela do
# chatbot monta a prévia da conversa com estes mesmos moldes (`textos_do_bot`).
# Duplicá-los em JavaScript faria a prévia mentir assim que um deles mudasse.
TEXTO_PEDIDO_SEM_DOCUMENTOS = (
    'Perfeito! Registrei seu pedido de *{servico}*.\n\n'
    'Um atendente vai falar com você por aqui.'
)
TEXTO_PRIMEIRO_DOCUMENTO = (
    'Perfeito! Para *{servico}* vou precisar de alguns documentos.\n\n'
    'Primeiro: *{tipo}*\n{instrucoes}\n\n'
    'Envie a foto ou o arquivo aqui mesmo.'
)
TEXTO_PROXIMO_DOCUMENTO = (
    '*{recebido}* recebido!\n\n'
    'Agora preciso de: *{tipo}*\n{instrucoes}'
)
TEXTO_DOCUMENTO_PENDENTE = (
    'Ainda preciso de *{tipo}*.\n{instrucoes}\n\n'
    'Envie a foto ou o arquivo aqui.{saida_humana}'
)
TEXTO_SAIDA_HUMANA = ' Se preferir, responda {palavra} para falar com uma pessoa.'
TEXTO_PROTOCOLO = '\nProtocolo: *{protocolo}*'


def textos_do_bot(config):
    """Moldes de mensagem que a prévia da tela usa, com os textos da empresa."""
    palavras = config.lista_palavras_atendente()
    return {
        'pedido_sem_documentos': TEXTO_PEDIDO_SEM_DOCUMENTOS,
        'primeiro_documento': TEXTO_PRIMEIRO_DOCUMENTO,
        'proximo_documento': TEXTO_PROXIMO_DOCUMENTO,
        'documento_pendente': TEXTO_DOCUMENTO_PENDENTE,
        'saida_humana': (
            TEXTO_SAIDA_HUMANA.format(palavra=palavras[0].upper()) if palavras else ''),
        'protocolo': TEXTO_PROTOCOLO,
        'conclusao': config.mensagem_conclusao,
    }


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
    """Opções do menu principal: as que não são sub-opção de ninguém."""
    return list(Servico.objects.filter(
        empresa=empresa, ativo=True, pai__isnull=True).order_by('ordem', 'nome'))


def opcoes_visiveis(conversa):
    """Opções que a conversa está vendo agora.

    Enquanto o cliente não escolhe nada, é o menu principal. Depois de escolher
    uma opção com sub-opções, `conversa.servico` guarda onde ele está na árvore
    e o menu passa a ser o dos filhos dela.
    """
    if conversa.servico_id and not conversa.servico.e_folha():
        return conversa.servico.subopcoes_do_menu()
    return servicos_do_menu(conversa.empresa)


def montar_menu(conversa, servicos, *, saudacao=True, config=None, pergunta=None):
    config = config or ConfiguracaoBot.para(conversa.empresa)
    linhas = []
    if saudacao:
        linhas.append(config.saudacao_formatada())
        linhas.append('')
    linhas.append(pergunta or 'Digite o número do serviço:')
    linhas.extend(f'{i} - {servico.nome}' for i, servico in enumerate(servicos, 1))
    linhas.append(f'{len(servicos) + 1} - {config.rotulo_atendente}')
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

    config = ConfiguracaoBot.para(conversa.empresa)

    if not config.ativo:
        # Bot desligado não é silêncio: o cliente escreveu e precisa de resposta.
        # Entregar a um atendente também faz nascer o card no Kanban.
        return _transferir_para_humano(conversa, motivo='bot_desligado', config=config)

    pedido_de_atendente = config.regex_atendente()
    if pedido_de_atendente and pedido_de_atendente.search(mensagem.conteudo or ''):
        return _transferir_para_humano(
            conversa, motivo='pedido_do_cliente', config=config)

    if conversa.estado == Conversa.Estado.TRIAGEM:
        return _processar_triagem(conversa, mensagem, config)
    if conversa.estado == Conversa.Estado.COLETANDO_DOCUMENTOS:
        return _processar_coleta(conversa, mensagem, tem_midia, config)
    return False


def _processar_triagem(conversa, mensagem, config):
    # As opções visíveis dependem de onde a conversa está na árvore: menu
    # principal no começo, submenu depois que o cliente escolheu uma ramificação.
    servicos = opcoes_visiveis(conversa)
    if not servicos:
        # Sem catálogo cadastrado não há menu a oferecer. Entregar a um humano
        # é melhor do que deixar o cliente sem resposta.
        return _transferir_para_humano(
            conversa, motivo='sem_servicos_cadastrados', config=config)

    ja_ofereceu_menu = conversa.mensagens.filter(
        direcao=Mensagem.Direcao.SAIDA).exists()
    if not ja_ofereceu_menu:
        return enviar_resposta_bot(
            conversa, montar_menu(conversa, servicos, config=config))

    opcao = _opcao_escolhida(mensagem.conteudo)
    if opcao == len(servicos) + 1:
        return _transferir_para_humano(
            conversa, motivo='pedido_do_cliente', config=config)
    if opcao and 1 <= opcao <= len(servicos):
        return _confirmar_servico(conversa, servicos[opcao - 1], config)
    return _nao_entendi(conversa, servicos, config)


def _nao_entendi(conversa, servicos, config):
    conversa.tentativas_invalidas += 1
    conversa.save(update_fields=['tentativas_invalidas', 'atualizada_em'])

    if conversa.tentativas_invalidas >= config.max_tentativas_invalidas:
        return _transferir_para_humano(
            conversa, motivo='tentativas_esgotadas', config=config)

    # Repetir o menu certo: se o cliente está num submenu, é o submenu que volta,
    # e sem a saudação, que só abre a conversa.
    dentro_de_submenu = bool(conversa.servico_id) and not conversa.servico.e_folha()
    return enviar_resposta_bot(
        conversa,
        f'{config.mensagem_nao_entendi} '
        + montar_menu(
            conversa, servicos, saudacao=False, config=config,
            pergunta=conversa.servico.pergunta_do_submenu() if dentro_de_submenu else None),
    )


def _confirmar_servico(conversa, servico, config):
    conversa.servico = servico
    conversa.tentativas_invalidas = 0
    conversa.save(update_fields=['servico', 'tentativas_invalidas', 'atualizada_em'])

    subopcoes = servico.subopcoes_do_menu()
    if subopcoes:
        # Ramificação: o pedido ainda não está caracterizado, então não nasce
        # card aqui. A conversa fica na triagem, um nível abaixo.
        return enviar_resposta_bot(conversa, montar_menu(
            conversa, subopcoes, saudacao=False, config=config,
            pergunta=servico.pergunta_do_submenu()))

    return _concluir_escolha(conversa, servico, config)


def _concluir_escolha(conversa, servico, config):
    """Opção-folha: o pedido está caracterizado e o card nasce aqui."""
    documentos = list(servico.documentos_exigidos.order_by('id'))

    tarefa = criar_tarefa(
        conversa.empresa, conversa.id,
        # O caminho inteiro ("Transferência › Moto") diz ao atendente o que foi
        # pedido; só o nome da folha ("Moto") não diria.
        resumo_triagem=f'{servico.caminho()} — solicitado pelo menu do WhatsApp.',
        origem=Tarefa.Origem.FLUXO_COMPLETO,
        # Havendo documentos a pedir, o bot continua conduzindo a conversa.
        assumir_por_humano=not documentos,
    )
    conversa.refresh_from_db()

    # O recado da opção ("separe os documentos") abre a mensagem seguinte.
    recado = servico.mensagem_apos_escolha.strip()
    abertura = f'{recado}\n\n' if recado else ''

    if not documentos:
        texto = abertura + TEXTO_PEDIDO_SEM_DOCUMENTOS.format(servico=servico.nome)
        if tarefa:
            texto += TEXTO_PROTOCOLO.format(protocolo=_protocolo(tarefa))
        return enviar_resposta_bot(conversa, texto)

    conversa.estado = Conversa.Estado.COLETANDO_DOCUMENTOS
    conversa.save(update_fields=['estado', 'atualizada_em'])

    primeiro = documentos[0]
    return enviar_resposta_bot(conversa, abertura + TEXTO_PRIMEIRO_DOCUMENTO.format(
        servico=servico.nome, tipo=primeiro.tipo, instrucoes=primeiro.instrucoes))


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


def _processar_coleta(conversa, mensagem, tem_midia, config):
    faltando = _documentos_faltando(conversa)
    if not faltando:
        return _concluir_coleta(conversa, config)

    atual = faltando[0]
    if not tem_midia:
        # Texto durante a coleta é quase sempre dúvida: repete a instrução em
        # vez de dar o documento por recebido.
        palavras = config.lista_palavras_atendente()
        saida_humana = (
            TEXTO_SAIDA_HUMANA.format(palavra=palavras[0].upper()) if palavras else '')
        return enviar_resposta_bot(conversa, TEXTO_DOCUMENTO_PENDENTE.format(
            tipo=atual.tipo, instrucoes=atual.instrucoes, saida_humana=saida_humana))

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
        return _concluir_coleta(conversa, config)

    proximo = restantes[0]
    return enviar_resposta_bot(conversa, TEXTO_PROXIMO_DOCUMENTO.format(
        recebido=atual.tipo, tipo=proximo.tipo, instrucoes=proximo.instrucoes))


def _concluir_coleta(conversa, config):
    tarefa = _tarefa_em_aberto(conversa)
    _atualizar_andamento_no_card(conversa)

    conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
    conversa.modo = Conversa.Modo.HUMANO
    conversa.save(update_fields=['estado', 'modo', 'atualizada_em'])

    texto = config.mensagem_conclusao
    if tarefa:
        texto += TEXTO_PROTOCOLO.format(protocolo=_protocolo(tarefa))
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


def _transferir_para_humano(conversa, *, motivo, config=None):
    config = config or ConfiguracaoBot.para(conversa.empresa)
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

    texto = config.mensagem_transferencia
    if tarefa:
        texto += TEXTO_PROTOCOLO.format(protocolo=_protocolo(tarefa))
    return enviar_resposta_bot(conversa, texto)


def religar(conversa):
    """Devolve ao bot uma conversa que estava em atendimento humano.

    Reabrir a triagem sem reenviar o menu deixaria o cliente adivinhando: a
    próxima mensagem dele seria lida como escolha de uma opção que ele não está
    mais vendo. Por isso a conversa volta a `triagem` e o menu vai junto.
    """
    config = ConfiguracaoBot.para(conversa.empresa)
    servicos = servicos_do_menu(conversa.empresa)
    if not servicos:
        return False

    conversa.modo = Conversa.Modo.BOT
    conversa.estado = Conversa.Estado.TRIAGEM
    conversa.tentativas_invalidas = 0
    # Zerar a opção é o que devolve o cliente ao menu principal; mantê-la o
    # deixaria preso no submenu de uma ramificação antiga.
    conversa.servico = None
    conversa.save(update_fields=[
        'modo', 'estado', 'servico', 'tentativas_invalidas', 'atualizada_em'])

    registrar_evento(
        conversa.empresa, EventoAtendimento.Tipo.CONVERSA_ESTADO,
        conversa=conversa, ator='atendente',
        payload={'devolvida_ao_bot': True},
    )
    return enviar_resposta_bot(
        conversa, montar_menu(conversa, servicos, config=config))
