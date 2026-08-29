import functools
import hmac
import hashlib

from django.conf import settings
from django.http import JsonResponse

from empresas.models import Empresa


def _token_valido(request):
    auth = request.headers.get('Authorization', '')
    if not auth.startswith('Bearer '):
        return False
    token = auth[7:].strip()
    esperado = getattr(settings, 'INTEGRACAO_API_TOKEN', '') or ''
    if not esperado or not token:
        return False
    return hmac.compare_digest(token, esperado)


def empresa_da_requisicao(request):
    """Resolve empresa pelo header X-Empresa-Id ou corpo JSON."""
    empresa_id = request.headers.get('X-Empresa-Id')
    if not empresa_id and hasattr(request, '_integracao_body'):
        empresa_id = request._integracao_body.get('empresa_id')
    if not empresa_id:
        return None
    return Empresa.objects.filter(id=empresa_id, ativa=True).first()


def api_token_required(view_func):
    @functools.wraps(view_func)
    def wrapper(request, *args, **kwargs):
        if not _token_valido(request):
            return JsonResponse({'erro': 'Não autorizado.'}, status=401)
        return view_func(request, *args, **kwargs)
    return wrapper


def api_empresa_required(view_func):
    """Exige token válido e empresa ativa via X-Empresa-Id."""
    @functools.wraps(view_func)
    @api_token_required
    def wrapper(request, *args, **kwargs):
        empresa = empresa_da_requisicao(request)
        if not empresa:
            return JsonResponse(
                {'erro': 'Informe X-Empresa-Id com o ID da empresa.'}, status=400)
        request.empresa_integracao = empresa
        return view_func(request, *args, **kwargs)
    return wrapper


def verificar_assinatura_webhook(payload: bytes, assinatura: str, segredo: str) -> bool:
    if not assinatura or not segredo:
        return False
    esperado = hmac.new(
        segredo.encode(), payload, hashlib.sha256).hexdigest()
    recebido = assinatura.removeprefix('sha256=').strip()
    return hmac.compare_digest(esperado, recebido)
