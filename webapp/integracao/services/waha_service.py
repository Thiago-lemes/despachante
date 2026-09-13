import requests
from django.conf import settings

WAHA_BASE_URL = getattr(settings, 'WAHA_BASE_URL', 'http://localhost:3000')


class WahaService:

    @staticmethod
    def criar_e_iniciar_sessao(nome_sessao: str, url_webhook: str):
        payload = {
            "name": nome_sessao,
            "config": {
                "webhooks": [
                    {
                        "url": url_webhook,
                        "events": ["message"]
                    }
                ]
            }
        }
        # Tenta criar e iniciar a sessão sem quebrar
        try:
            requests.post(f"{WAHA_BASE_URL}/api/sessions", json=payload, timeout=5)
            requests.post(f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}/start", timeout=5)
        except requests.RequestException as e:
            raise RuntimeError(f"Erro ao conectar com WAHA: {e}")

    @staticmethod
    def obter_qr_code(nome_sessao: str):
        try:
            response = requests.get(f"{WAHA_BASE_URL}/api/{nome_sessao}/auth/qr?format=raw", timeout=5)
            if response.status_code == 200:
                return response.json()
        except requests.RequestException:
            pass
        return None

    @staticmethod
    def obter_status_sessao(nome_sessao: str):
        """
        Retorna o status atual da sessão: 'STOPPED', 'SCAN_QR_CODE', 'WORKING'.
        """
        url = f"{WAHA_BASE_URL}/api/sessions/{nome_sessao}"
        response = requests.get(url, timeout=10)
        if response.status_code == 200:
            return response.json().get('status')
        return 'UNKNOWN'
