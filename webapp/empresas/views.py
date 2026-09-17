from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
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


@login_required
def acesso_pendente(request):
    """Página de espera de quem se cadastrou como funcionário e não foi aprovado."""
    if request.empresa is not None:
        return redirect('busca')
    vinculo = EmpresaUsuario.objects.filter(
        usuario=request.user).select_related('empresa').first()
    return render(request, 'empresas/acesso_pendente.html', {'vinculo': vinculo})


@login_required
def equipe(request):
    """Lista a equipe da empresa ativa e os pedidos de acesso pendentes."""
    if not _pode_administrar(request):
        return HttpResponseForbidden('Apenas administradores da empresa acessam esta página.')

    vinculos = EmpresaUsuario.objects.filter(
        empresa=request.empresa).select_related('usuario').order_by('usuario__username')
    return render(request, 'empresas/equipe.html', {
        'pendentes': [v for v in vinculos if not v.ativo],
        'membros': [v for v in vinculos if v.ativo],
        'papeis': EmpresaUsuario.Papel.choices,
    })


@login_required
@require_POST
def aprovar_vinculo(request, vinculo_id):
    """Libera o acesso de um funcionário à empresa ativa."""
    if not _pode_administrar(request):
        return HttpResponseForbidden('Apenas administradores da empresa aprovam acessos.')

    vinculo = get_object_or_404(
        EmpresaUsuario, pk=vinculo_id, empresa=request.empresa, ativo=False)

    papel = request.POST.get('papel')
    if papel in EmpresaUsuario.Papel.values:
        vinculo.papel = papel
    vinculo.ativo = True
    vinculo.save(update_fields=['papel', 'ativo', 'atualizado_em'])

    messages.success(request, f'{vinculo.usuario.username} agora tem acesso à empresa.')
    return redirect('equipe')


@login_required
@require_POST
def recusar_vinculo(request, vinculo_id):
    """Remove um pedido de acesso pendente. A conta do usuário é preservada."""
    if not _pode_administrar(request):
        return HttpResponseForbidden('Apenas administradores da empresa recusam acessos.')

    vinculo = get_object_or_404(
        EmpresaUsuario, pk=vinculo_id, empresa=request.empresa, ativo=False)
    username = vinculo.usuario.username
    vinculo.delete()

    messages.info(request, f'Pedido de acesso de {username} foi recusado.')
    return redirect('equipe')


def _pode_administrar(request):
    return request.empresa is not None and (
        request.empresa_vinculo is not None and request.empresa_vinculo.pode_administrar())
