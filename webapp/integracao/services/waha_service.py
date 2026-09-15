import logging

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

WAHA_BASE_URL = getattr(settings, 'WAHA_BASE_URL', 'http://localhost:3000')

# O endpoint de QR do WAHA fica bloqueado até o QR existir; 5s abortava cedo demais.
TIMEOUT_QR = 15
TIMEOUT_PADRAO = 15


def _headers():
    chave = getattr(settings, 'WAHA_API_KEY', '')
    return {'X-Api-Key': chave} if chave else {}


class WahaService:

    @staticmethod
    def garantir_sessao_ativa(nome_sessao: str, url_webhook: str, status_atual: str):
        """
        Leva a sessão até um estado em que o QR Code possa ser gerado, de acordo
        com o estado atual dela no WAHA:

        - UNKNOWN (não existe) → cria a sessão (já sobe iniciada).
        - FAILED               → 'restart' (start não recupera: responde
                                 "Session is already running" e trava).
        - STOPPED              → 'start'.
        - STARTING/SCAN_QR_CODE/WORKING → não faz nada, já está a caminho.
        """
        try:
            if status_atual in ('STARTING', 'SCAN_QR_CODE', 'WORKING'):
                return

            if status_atual == 'FAILED':
                logger.info('Sessão WAHA %s em FAILED, reiniciando.', nome_sessao)
                requests.post(
                    f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}/restart",
                    headers=_headers(), timeout=TIMEOUT_PADRAO,
                )
                return

            if status_atual == 'STOPPED':
                logger.info('Sessão WAHA %s parada, iniciando.', nome_sessao)
                requests.post(
                    f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}/start",
                    headers=_headers(), timeout=TIMEOUT_PADRAO,
                )
                return

            logger.info('Criando sessão WAHA %s.', nome_sessao)
            payload = {
                'name': nome_sessao,
                'start': True,
                'config': {
                    'webhooks': [
                        # 'session.status' faz o WAHA avisar quando a sessão
                        # conecta/cai, em vez de perguntarmos de tempos em tempos.
                        {'url': url_webhook, 'events': ['message', 'session.status']}
                    ]
                },
            }
            resposta = requests.post(
                f"{WAHA_BASE_URL}/api/sessions", json=payload,
                headers=_headers(), timeout=TIMEOUT_PADRAO,
            )
            # 422 = sessão já existia (corrida entre duas checagens); nesse caso
            # um restart resolve, porque 'start' não recupera sessão travada.
            if resposta.status_code == 422:
                requests.post(
                    f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}/restart",
                    headers=_headers(), timeout=TIMEOUT_PADRAO,
                )
        except requests.RequestException as e:
            raise RuntimeError(f"Erro ao conectar com WAHA: {e}")

    @staticmethod
    def obter_qr_code(nome_sessao: str):
        """
        Retorna os bytes do PNG do QR Code, ou None se ainda não estiver pronto.
        """
        try:
            response = requests.get(
                f"{WAHA_BASE_URL}/api/{nome_sessao}/auth/qr?format=image",
                headers=_headers(),
                timeout=TIMEOUT_QR,
            )
            if response.status_code == 200 and response.content:
                return response.content
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def obter_status_sessao(nome_sessao: str):
        """
        Status da sessão no WAHA: 'STOPPED', 'STARTING', 'SCAN_QR_CODE',
        'WORKING', 'FAILED', ou 'UNKNOWN' quando a sessão ainda não existe.
        """
        url = f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}"
        response = requests.get(url, headers=_headers(), timeout=TIMEOUT_PADRAO)
        if response.status_code == 200:
            return response.json().get('status')
        return 'UNKNOWN'
