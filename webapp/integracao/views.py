import base64
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from empresas.models import Empresa
from .models import WahaSessao
from .services.waha_service import WahaService

logger = logging.getLogger(__name__)


def _persistir_status(sessao_obj, status):
    """Mantém no banco o último status conhecido da sessão."""
    if not status or status == sessao_obj.status:
        return
    if status not in WahaSessao.Status.values:
        return
    sessao_obj.status = status
    sessao_obj.status_atualizado_em = timezone.now()
    sessao_obj.save(update_fields=['status', 'status_atualizado_em', 'atualizada_em'])


@require_GET
def gerar_qr_code_empresa(request, empresa_id):
    """
    Retorna o status da sessão WhatsApp da empresa e, quando necessário,
    (re)inicia a sessão no WAHA para gerar um novo QR Code.

    Contrato de resposta:
    - 200 {"status": "conectado"} — sessão já autenticada, nada a fazer.
    - 200 {"status": "qrcode", "sessao": ..., "qr_code": ...} — QR pronto para escanear.
    - 202 {"status": "aguardando"} — sessão iniciada, QR ainda não gerado pelo WAHA.
    - 500 {"status": "erro", "error": ...} — falha de comunicação com o WAHA.
    """
    try:
        empresa = Empresa.objects.filter(id=empresa_id, ativa=True).first()
        if not empresa:
            return JsonResponse({'error': f'Empresa com ID {empresa_id} não encontrada.'}, status=404)

        nome_sessao = f"empresa_{empresa.id}"
        url_webhook = f"{settings.SITE_URL}/api/v1/integracao/webhooks/waha/{nome_sessao}/"

        sessao_obj, _ = WahaSessao.objects.get_or_create(
            empresa=empresa,
            nome_sessao=nome_sessao,
            defaults={'ativa': True}
        )

        # Atalho: o WAHA avisa por webhook ('session.status') quando conecta,
        # então uma sessão já conectada é respondida direto do banco, sem
        # nenhuma ida ao WAHA a cada verificação da interface.
        if sessao_obj.status == WahaSessao.Status.CONECTADA:
            return JsonResponse({'status': 'conectado'})

        status_atual = WahaService.obter_status_sessao(nome_sessao)
        _persistir_status(sessao_obj, status_atual)

        if status_atual == 'WORKING':
            return JsonResponse({'status': 'conectado'})

        # Cria/inicia/reinicia conforme o estado atual. Não mexe na sessão
        # quando ela já está subindo, senão o polling do front-end reiniciaria
        # tudo a cada poucos segundos e ela nunca terminaria de subir.
        WahaService.garantir_sessao_ativa(nome_sessao, url_webhook, status_atual)

        # O QR só existe depois que a sessão chega em SCAN_QR_CODE. Em
        # 'STARTING' a chamada ficaria pendurada esperando — melhor devolver
        # 'aguardando' na hora e deixar o front-end perguntar de novo.
        png_bytes = None
        if status_atual == 'SCAN_QR_CODE':
            png_bytes = WahaService.obter_qr_code(nome_sessao)

        if not png_bytes:
            return JsonResponse({
                'status': 'aguardando',
                'mensagem': 'Sessão iniciada, aguardando geração do QR Code pelo WAHA.'
            }, status=202)

        qr_code_data_uri = 'data:image/png;base64,' + base64.b64encode(png_bytes).decode('ascii')

        return JsonResponse({
            'status': 'qrcode',
            'sessao': nome_sessao,
            'qr_code': qr_code_data_uri,
        })

    except Exception as e:
        logger.error(f"Erro ao gerar QR Code para empresa {empresa_id}: {str(e)}", exc_info=True)
        return JsonResponse({
            'status': 'erro',
            'error': 'Falha na comunicação com o servidor do WhatsApp (WAHA). Verifique se o serviço está ativo.',
            'detalhes': str(e)
        }, status=500)
