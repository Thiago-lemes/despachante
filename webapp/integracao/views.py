import json
import logging
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST, require_GET
from django.shortcuts import get_object_or_404
from django.contrib.auth.decorators import login_not_required

# Imports das Models
from empresas.models import Empresa  # <-- Importação adicionada aqui
from atendimento.models import Contato, Conversa, Mensagem
from .models import WahaSessao, WebhookRecebido, EventoAtendimento
from .services.waha_service import WahaService

logger = logging.getLogger(__name__)


@login_not_required
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


@require_GET
def gerar_qr_code_empresa(request, empresa_id):
    """
    Inicia a sessão no WAHA para a empresa informada e devolve o QR Code.
    """
    try:
        empresa = Empresa.objects.filter(id=empresa_id, ativa=True).first()
        if not empresa:
            return JsonResponse({'error': f'Empresa com ID {empresa_id} não encontrada.'}, status=404)

        nome_sessao = f"empresa_{empresa.id}"
        url_webhook = f"https://despachante.kingdomtech.com.br/api/v1/integracao/webhooks/waha/{nome_sessao}/"

        # Garantir registro de WahaSessao no banco
        WahaSessao.objects.get_or_create(
            empresa=empresa,
            nome_sessao=nome_sessao,
            defaults={'ativa': True}
        )

        print("###########Chama a API do WAHA################")
        WahaService.criar_e_iniciar_sessao(nome_sessao, url_webhook)
        dados_qr = WahaService.obter_qr_code(nome_sessao)

        if not dados_qr:
            return JsonResponse({
                'status': 'aguardando',
                'mensagem': 'Sessão iniciada, aguardando geração do QR Code pelo WAHA.'
            }, status=202)

        return JsonResponse({
            "sessao": nome_sessao,
            "qr_code": dados_qr
        })

    except Exception as e:
        logger.error(f"Erro ao gerar QR Code para empresa {empresa_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'error': 'Falha na comunicação com o servidor do WhatsApp (WAHA). Verifique se o serviço está ativo.',
            'detalhes': str(e)
        }, status=500)
