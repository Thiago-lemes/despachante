import logging
import re

from integracao.models import WahaSessao
from integracao.services.conversas import (
    processar_webhook_idempotente,
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

    from_id = payload.get('from') or payload.get('author') or ''
    if from_id.endswith('@g.us'):
        return None

    texto = payload.get('body') or payload.get('text') or ''
    if not texto and payload.get('caption'):
        texto = payload['caption']

    msg_id = str(payload.get('id') or payload.get('messageId') or '')
    nome = ''
    if isinstance(payload.get('_data'), dict):
        nome = payload['_data'].get('notifyName') or ''

    wa_id = _normalizar_wa_id(from_id)
    if not wa_id:
        return None

    return {
        'wa_id': wa_id,
        'conteudo': str(texto),
        'wa_message_id': msg_id,
        'nome_contato': nome,
        'tipo_midia': payload.get('mimetype') or payload.get('type') or 'text',
        'media_url': payload.get('mediaUrl') or payload.get('media') or '',
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
    if not mensagem or not mensagem['conteudo']:
        registrar_evento(
            sessao.empresa, EventoAtendimento.Tipo.WEBHOOK_RECEBIDO,
            ator='waha', correlation_id=id_evento,
            payload={'sessao': sessao.nome_sessao, 'evento': corpo.get('event')},
        )
        return {'status': 'ignorado', 'motivo': 'sem mensagem de texto'}

    msg, criada = registrar_mensagem_entrada(
        sessao.empresa,
        wa_id=mensagem['wa_id'],
        conteudo=mensagem['conteudo'],
        wa_message_id=mensagem['wa_message_id'],
        nome_contato=mensagem['nome_contato'],
        ator='waha',
    )
    return {
        'status': 'ok',
        'mensagem_id': msg.id,
        'conversa_id': msg.conversa_id,
        'criada': criada,
    }
