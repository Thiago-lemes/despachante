from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from .models import EmpresaUsuario
from .permissoes import somente_administrador


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


@somente_administrador()
def equipe(request):
    """Lista a equipe da empresa ativa e os pedidos de acesso pendentes."""
    vinculos = EmpresaUsuario.objects.filter(
        empresa=request.empresa).select_related('usuario').order_by('usuario__username')

    # Atendimento em aberto é o que impede tirar alguém da equipe sem pensar:
    # sem repassar os cards, o cliente fica falando com quem não entra mais.
    abertos = _atendimentos_abertos_por_usuario(request.empresa)
    for vinculo in vinculos:
        vinculo.atendimentos_abertos = abertos.get(vinculo.usuario_id, 0)

    return render(request, 'empresas/equipe.html', {
        'pendentes': [v for v in vinculos if not v.ativo],
        'membros': [v for v in vinculos if v.ativo],
        'papeis': EmpresaUsuario.Papel.choices,
        'orfaos': _atendimentos_sem_dono_ativo(request.empresa),
    })


def _atendimentos_abertos_por_usuario(empresa):
    from atendimento.models import Tarefa
    contagem = (
        Tarefa.objects.filter(empresa=empresa, status=Tarefa.Status.EM_ATENDIMENTO)
        .values('atendente_id').annotate(total=Count('id'))
    )
    return {linha['atendente_id']: linha['total'] for linha in contagem}


def _atendimentos_sem_dono_ativo(empresa):
    """Cards presos com quem perdeu o acesso — o caso que motivou a transferência."""
    from atendimento.models import Tarefa
    ativos = EmpresaUsuario.objects.filter(
        empresa=empresa, ativo=True).values_list('usuario_id', flat=True)
    return list(
        Tarefa.objects.filter(
            empresa=empresa, status=Tarefa.Status.EM_ATENDIMENTO,
            atendente__isnull=False)
        .exclude(atendente_id__in=ativos)
        .select_related('contato', 'atendente', 'servico')
        .order_by('-criada_em')
    )


@require_POST
@somente_administrador('Apenas administradores da empresa aprovam acessos.')
def aprovar_vinculo(request, vinculo_id):
    """Libera o acesso de um funcionário à empresa ativa."""
    vinculo = get_object_or_404(
        EmpresaUsuario, pk=vinculo_id, empresa=request.empresa, ativo=False)

    papel = request.POST.get('papel')
    if papel in EmpresaUsuario.Papel.values:
        vinculo.papel = papel
    vinculo.ativo = True
    vinculo.save(update_fields=['papel', 'ativo', 'atualizado_em'])

    messages.success(request, f'{vinculo.usuario.username} agora tem acesso à empresa.')
    return redirect('equipe')


@require_POST
@somente_administrador('Apenas administradores da empresa recusam acessos.')
def recusar_vinculo(request, vinculo_id):
    """Remove um pedido de acesso pendente. A conta do usuário é preservada."""
    vinculo = get_object_or_404(
        EmpresaUsuario, pk=vinculo_id, empresa=request.empresa, ativo=False)
    username = vinculo.usuario.username
    vinculo.delete()

    messages.info(request, f'Pedido de acesso de {username} foi recusado.')
    return redirect('equipe')
