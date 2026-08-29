import logging
import os

import requests
from django.conf import settings

logger = logging.getLogger(__name__)


def _base_url():
    return (getattr(settings, 'WAHA_BASE_URL', '') or os.getenv('WAHA_BASE_URL', '')).rstrip('/')


def _api_key():
    return getattr(settings, 'WAHA_API_KEY', '') or os.getenv('WAHA_API_KEY', '')


def _headers():
    headers = {'Content-Type': 'application/json'}
    chave = _api_key()
    if chave:
        headers['X-Api-Key'] = chave
    return headers


def enviar_texto(sessao: str, chat_id: str, texto: str):
    """Envia mensagem de texto via WAHA."""
    base = _base_url()
    if not base:
        return {'success': False, 'error': 'WAHA_BASE_URL não configurada.'}

    numero = chat_id if '@' in chat_id else f'{chat_id}@c.us'
    url = f'{base}/api/sendText'
    payload = {
        'session': sessao,
        'chatId': numero,
        'text': texto,
    }
    try:
        resposta = requests.post(url, json=payload, headers=_headers(), timeout=30)
        resposta.raise_for_status()
        dados = resposta.json()
        logger.info('WAHA sendText %s → %s', sessao, numero)
        return {'success': True, 'data': dados}
    except requests.RequestException as erro:
        logger.error('Erro WAHA sendText: %s', erro)
        return {'success': False, 'error': str(erro)}


def status_sessao(sessao: str):
    """Consulta status da sessão WAHA."""
    base = _base_url()
    if not base:
        return {'success': False, 'error': 'WAHA_BASE_URL não configurada.'}
    url = f'{base}/api/sessions/{sessao}'
    try:
        resposta = requests.get(url, headers=_headers(), timeout=15)
        resposta.raise_for_status()
        return {'success': True, 'data': resposta.json()}
    except requests.RequestException as erro:
        return {'success': False, 'error': str(erro)}


def baixar_midia(sessao: str, media_url: str):
    """Baixa mídia do WAHA (URL relativa ou absoluta)."""
    base = _base_url()
    if not base:
        return {'success': False, 'error': 'WAHA_BASE_URL não configurada.'}
    url = media_url if media_url.startswith('http') else f'{base}{media_url}'
    try:
        resposta = requests.get(url, headers=_headers(), timeout=60)
        resposta.raise_for_status()
        return {
            'success': True,
            'content': resposta.content,
            'content_type': resposta.headers.get('Content-Type', 'application/octet-stream'),
        }
    except requests.RequestException as erro:
        return {'success': False, 'error': str(erro)}
