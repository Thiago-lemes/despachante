from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect
from django.views.decorators.http import require_POST

from .models import EmpresaUsuario


@login_required
@require_POST
def selecionar_empresa(request):
    """Troca a empresa ativa apenas por uma empresa vinculada ao usuário."""
    empresa_id = request.POST.get('empresa_id')
    vinculo = EmpresaUsuario.objects.filter(
        usuario=request.user,
        empresa_id=empresa_id,
        ativo=True,
        empresa__ativa=True,
    ).first()
    if not vinculo:
        return HttpResponseForbidden('Empresa não disponível para este usuário.')
    request.session['empresa_atual_id'] = vinculo.empresa_id
    return redirect(request.POST.get('next') or 'busca')
