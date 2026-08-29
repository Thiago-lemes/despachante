from integracao.models import WebhookRecebido


class WebhookDuplicado(Exception):
    def __init__(self, registro):
        self.registro = registro
        super().__init__('Webhook já processado.')


def registrar_webhook(empresa, origem, id_externo, payload: bytes):
    """Registra webhook; levanta WebhookDuplicado se id_externo já existir."""
    if not id_externo:
        id_externo = WebhookRecebido.hash_payload(payload)
    registro, criado = WebhookRecebido.objects.get_or_create(
        empresa=empresa,
        origem=origem,
        id_externo=id_externo,
        defaults={'payload_hash': WebhookRecebido.hash_payload(payload)},
    )
    if not criado:
        raise WebhookDuplicado(registro)
    return registro
