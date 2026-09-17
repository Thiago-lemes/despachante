import json
import logging

from django import template
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from empresas.models import Empresa
from .models import Conversa, Tarefa, Servico

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


logger = logging.getLogger(__name__)


def _empresa_do_usuario(request):
    """Empresa ativa da requisição: middleware, sessão ou primeiro vínculo."""
    empresa = getattr(request, 'empresa', None)
    if empresa:
        return empresa

    empresa_id = request.session.get('empresa_atual_id')
    if empresa_id:
        empresa = Empresa.objects.filter(id=empresa_id, ativa=True).first()
        if empresa:
            return empresa

    vinculos = getattr(request.user, 'empresas_vinculadas', None)
    vinculo = vinculos.first() if vinculos else None
    if vinculo:
        request.session['empresa_atual_id'] = vinculo.empresa_id
        return vinculo.empresa

    return None


@login_required
def kanban_tarefas(request):
    """Renderiza o kanban visual de tarefas"""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')

    tarefas_por_status = {}
    total_tarefas = 0
    for status, _label in Tarefa.Status.choices:
        tarefas = list(
            Tarefa.objects.filter(empresa=empresa, status=status)
            .select_related('contato', 'servico', 'atendente', 'conversa')
            .prefetch_related('conversa__documentos_recebidos')
            .order_by('-criada_em')
        )
        tarefas_por_status[status] = tarefas
        total_tarefas += len(tarefas)

    servicos = Servico.objects.filter(empresa=empresa, ativo=True)

    return render(request, 'atendimento/kanban.html', {
        'tarefas_por_status': tarefas_por_status,
        'status_choices': Tarefa.Status.choices,
        'servicos': servicos,
        'total_tarefas': total_tarefas,
    })


@login_required
def tarefas_novas_status(request):
    """Quantidade de tarefas ainda não atendidas, para o badge do menu."""
    empresa = _empresa_do_usuario(request)
    total = 0
    if empresa:
        total = Tarefa.objects.filter(
            empresa=empresa, status=Tarefa.Status.ABERTA).count()
    return JsonResponse({'total': total})


@require_POST
@login_required
def atualizar_status_tarefa(request):
    """Atualiza o status de uma tarefa (drag-and-drop do Kanban)."""
    try:
        dados = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'erro', 'erro': 'JSON inválido.'}, status=400)

    tarefa_id = dados.get('tarefa_id')
    novo_status = dados.get('novo_status')

    if not tarefa_id or not novo_status:
        return JsonResponse({'status': 'erro', 'erro': 'Parâmetros inválidos.'}, status=400)

    if novo_status not in Tarefa.Status.values:
        return JsonResponse({'status': 'erro', 'erro': 'Status inválido.'}, status=400)

    empresa = _empresa_do_usuario(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'erro': 'Nenhuma empresa ativa.'}, status=403)

    # Filtrar pela empresa impede mover tarefa de outro tenant sabendo o id.
    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)

    agora = timezone.now()
    campos = ['status']
    tarefa.status = novo_status

    if novo_status == Tarefa.Status.ABERTA:
        # Voltar para "Aberta" devolve a tarefa à fila, sem dono.
        tarefa.atendente = None
        tarefa.assumida_em = None
        campos += ['atendente', 'assumida_em']
    else:
        # Quem move a tarefa assume o atendimento.
        tarefa.atendente = request.user
        campos.append('atendente')
        if not tarefa.assumida_em:
            tarefa.assumida_em = agora
            campos.append('assumida_em')

    if novo_status in (Tarefa.Status.CONCLUIDA, Tarefa.Status.CANCELADA):
        tarefa.concluida_em = agora
        campos.append('concluida_em')
    elif tarefa.concluida_em:
        tarefa.concluida_em = None
        campos.append('concluida_em')

    tarefa.save(update_fields=campos)

    # Assumir o card cala o bot naquela conversa. Devolver para "Aberta" não o
    # religa: quem já foi atendido por uma pessoa não volta para a triagem
    # automática no meio do assunto.
    if novo_status != Tarefa.Status.ABERTA:
        conversa = tarefa.conversa
        if conversa.modo != Conversa.Modo.HUMANO:
            conversa.modo = Conversa.Modo.HUMANO
            conversa.save(update_fields=['modo', 'atualizada_em'])

    atendente = tarefa.atendente
    return JsonResponse({
        'status': 'ok',
        'novo_status': tarefa.status,
        'atendente': atendente.get_full_name() or atendente.username if atendente else '',
    })
