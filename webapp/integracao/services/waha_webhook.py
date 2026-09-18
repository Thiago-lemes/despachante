import logging
import re

from atendimento.models import Conversa
from atendimento.services.bot import processar_mensagem

from integracao import anexos
from integracao.models import WahaSessao
from integracao.services.conversas import (
    processar_webhook_idempotente,
    registrar_mensagem_do_celular,
    registrar_mensagem_entrada,
)
from integracao.services.auditoria import registrar_evento
from integracao.models import EventoAtendimento

logger = logging.getLogger(__name__)


def _normalizar_wa_id(valor: str) -> str:
    if not valor:
        return ''
    numero = re.sub(r'\D', '', valor.split('@')[0])
    return numero


def _e_telefone(identificador: str) -> bool:
    """
    Distingue telefone de LID. Contas novas do WhatsApp chegam como
    '<lid>@lid', que é um id interno e não um número discável.
    """
    return '@lid' not in (identificador or '')


def _extrair_nome(payload: dict) -> str:
    """
    O nome do contato muda de lugar conforme o engine do WAHA:
    NOWEB usa 'pushName', WEBJS usa '_data.notifyName'.
    """
    dados = payload.get('_data') if isinstance(payload.get('_data'), dict) else {}
    for origem, chave in (
        (payload, 'pushName'),
        (payload, 'notifyName'),
        (dados, 'pushName'),
        (dados, 'notifyName'),
    ):
        nome = (origem.get(chave) or '').strip()
        if nome:
            return nome
    return ''


def _extrair_telefone(payload: dict, from_id: str) -> str:
    """Número discável, quando o WAHA o informa junto do LID."""
    if _e_telefone(from_id):
        return _normalizar_wa_id(from_id)

    dados = payload.get('_data') if isinstance(payload.get('_data'), dict) else {}
    chave = dados.get('key') if isinstance(dados.get('key'), dict) else {}
    for origem, campo in (
        (payload, 'participant'),
        (chave, 'senderPn'),
        (chave, 'participantPn'),
        (chave, 'remoteJidAlt'),
        (dados, 'senderPn'),
    ):
        valor = origem.get(campo) or ''
        if valor and _e_telefone(valor):
            return _normalizar_wa_id(valor)
    return ''


def _e_do_proprio_sistema(payload: dict) -> bool:
    """
    Mensagem que o próprio número enviou. Sem esta verificação o bot responderia
    à própria resposta — e o WAHA reentrega o eco conforme a configuração do
    engine. É a primeira linha de defesa contra loop, e vale mesmo sem bot.
    """
    if payload.get('fromMe'):
        return True
    dados = payload.get('_data') if isinstance(payload.get('_data'), dict) else {}
    chave = dados.get('key') if isinstance(dados.get('key'), dict) else {}
    return bool(dados.get('fromMe') or chave.get('fromMe'))


def _extrair_mensagem_waha(corpo: dict):
    """Interpreta payloads comuns do WAHA (message / message.any)."""
    evento = corpo.get('event', '')
    payload = corpo.get('payload') or corpo.get('data') or corpo

    if evento and 'message' not in evento.lower() and evento not in ('', 'message'):
        return None

    if isinstance(payload, dict) and payload.get('event'):
        evento = payload.get('event', evento)
        payload = payload.get('payload') or payload

    if not isinstance(payload, dict):
        return None

    # Mensagem que saiu do próprio aparelho não some mais: ela é registrada como
    # saída do "celular da empresa" (sem acionar o bot), para o atendente não
    # responder em cima de uma resposta que já foi dada.
    do_proprio_sistema = _e_do_proprio_sistema(payload)

    # Nela, quem interessa é o destinatário — 'from' é o número da empresa.
    from_id = (payload.get('to') if do_proprio_sistema
               else (payload.get('from') or payload.get('author'))) or ''
    if from_id.endswith('@g.us'):
        return None

    texto = payload.get('body') or payload.get('text') or ''
    if not texto and payload.get('caption'):
        texto = payload['caption']

    msg_id = str(payload.get('id') or payload.get('messageId') or '')

    wa_id = _normalizar_wa_id(from_id)
    if not wa_id:
        return None

    return {
        'wa_id': wa_id,
        'chat_id': from_id,
        'do_proprio_sistema': do_proprio_sistema,
        'conteudo': str(texto),
        'wa_message_id': msg_id,
        'nome_contato': _extrair_nome(payload),
        'telefone': _extrair_telefone(payload, from_id),
        'tipo_midia': payload.get('mimetype') or payload.get('type') or 'text',
        'media_url': payload.get('mediaUrl') or payload.get('media') or '',
        'anexo': anexos.classificar(payload),
    }


def processar_webhook_waha(sessao: WahaSessao, corpo: dict, payload_bruto: bytes):
    id_evento = str(
        corpo.get('id') or corpo.get('eventId')
        or (corpo.get('payload') or {}).get('id') or ''
    )
    if not processar_webhook_idempotente(
            sessao.empresa, 'waha', id_evento or '', payload_bruto):
        logger.info('Webhook WAHA duplicado: %s', id_evento)
        return {'status': 'duplicado', 'id': id_evento}

    mensagem = _extrair_mensagem_waha(corpo)
    if not mensagem or not (mensagem['conteudo'] or mensagem['anexo']):
        registrar_evento(
            sessao.empresa, EventoAtendimento.Tipo.WEBHOOK_RECEBIDO,
            ator='waha', correlation_id=id_evento,
            payload={'sessao': sessao.nome_sessao, 'evento': corpo.get('event')},
        )
        return {'status': 'ignorado', 'motivo': 'sem mensagem de texto'}

    # Um anexo sem legenda não tem texto, mas é justamente como o cliente
    # responde ao pedido de documento — precisa virar mensagem mesmo assim. E o
    # histórico diz o que era: "[figurinha]" e "[foto]" contam histórias bem
    # diferentes para quem vai atender.
    descricao = anexos.descrever(mensagem['anexo'])
    conteudo = mensagem['conteudo'] or descricao

    if mensagem['do_proprio_sistema']:
        registrada, gravou = registrar_mensagem_do_celular(
            sessao.empresa,
            wa_id=mensagem['wa_id'],
            conteudo=mensagem['conteudo'] or descricao,
            wa_message_id=mensagem['wa_message_id'],
        )
        if not gravou:
            return {'status': 'ignorado',
                    'motivo': 'eco do próprio envio ou contato sem conversa'}
        return {'status': 'ok', 'mensagem_id': registrada.id,
                'conversa_id': registrada.conversa_id, 'do_celular': True}

    msg, criada = registrar_mensagem_entrada(
        sessao.empresa,
        wa_id=mensagem['wa_id'],
        conteudo=conteudo,
        wa_message_id=mensagem['wa_message_id'],
        nome_contato=mensagem['nome_contato'],
        telefone=mensagem['telefone'],
        chat_id=mensagem['chat_id'],
        ator='waha',
    )

    resultado = {
        'status': 'ok',
        'mensagem_id': msg.id,
        'conversa_id': msg.conversa_id,
        'conteudo': conteudo,
        'criada': criada,
    }

    # O bot roda por evento, aqui. 'criada' garante que a reentrega do mesmo
    # evento pelo WAHA não gere uma segunda resposta.
    conversa = msg.conversa
    if criada and conversa.modo == Conversa.Modo.BOT:
        try:
            resultado['bot_respondeu'] = processar_mensagem(
                conversa, msg, anexo=mensagem['anexo'])
        except Exception:
            # Falha do bot não pode devolver erro ao WAHA: ele reentregaria o
            # evento e a mensagem já está registrada.
            logger.exception('Falha do bot na conversa %s', conversa.id)
            resultado['bot_respondeu'] = False

    return resultado
