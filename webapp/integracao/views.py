# webapp/integracao/views.py
import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import get_object_or_404

from atendimento.models import Contato, Conversa, Mensagem
from .models import WahaSessao, WebhookRecebido, EventoAtendimento

logger = logging.getLogger(__name__)


@csrf_exempt
@require_POST
def webhook_waha(request, sessao):
    try:
        payload = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'error': 'JSON invalido'}, status=400)

    sessao_obj = get_object_or_404(WahaSessao, nome_sessao=sessao, ativa=True)
    empresa = sessao_obj.empresa

    wa_message_id = payload.get('data', {}).get('message', {}).get('id', '')
    if not wa_message_id:
        return JsonResponse({'error': 'message id nao encontrado'}, status=400)

    webhook, criado = WebhookRecebido.objects.get_or_create(
        origem=WebhookRecebido.Origem.WAHA,
        id_externo=wa_message_id,
        empresa=empresa,
        defaults={'payload_hash': WebhookRecebido.hash_payload(request.body)}
    )

    if not criado:
        return JsonResponse({'ok': True, 'duplicate': True})

    data = payload.get('data', {})
    message = data.get('message', {})
    from_data = data.get('from', '')

    wa_id = from_data.replace('@c.us', '').replace('@s.whatsapp.net', '')
    conteudo = message.get('body', '')

    contato, _ = Contato.objects.get_or_create(
        empresa=empresa,
        wa_id=wa_id,
        defaults={'nome': data.get('notifyName', '')}
    )

    conversa, _ = Conversa.objects.get_or_create(
        empresa=empresa,
        contato=contato,
        estado__in=['triagem', 'coletando_documentos', 'aguardando_analise'],
        defaults={
            'estado': Conversa.Estado.TRIAGEM,
            'modo': Conversa.Modo.BOT,
        }
    )

    Mensagem.objects.create(
        empresa=empresa,
        conversa=conversa,
        direcao=Mensagem.Direcao.ENTRADA,
        conteudo=conteudo,
        wa_message_id=wa_message_id,
    )

    EventoAtendimento.objects.create(
        empresa=empresa,
        conversa=conversa,
        tipo=EventoAtendimento.Tipo.MENSAGEM_RECEBIDA,
        payload={'wa_id': wa_id, 'conteudo': conteudo[:100]}
    )

    return JsonResponse({'ok': True})
