import json
import logging
import os

from django import template
from django.contrib.auth.decorators import login_required, login_not_required
from django.http import HttpResponse, HttpResponseForbidden, JsonResponse
from django.shortcuts import render, get_object_or_404
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST
from empresas.models import Empresa
from integracao.models import WahaSessao
from .models import Contato, Conversa, Mensagem, Tarefa, Servico

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


logger = logging.getLogger(__name__)


@login_not_required
@csrf_exempt
@require_http_methods(["GET"])
def webhook_verify(request):
    """Verificação legado do webhook."""
    mode = request.GET.get('hub.mode')
    token = request.GET.get('hub.verify_token')
    challenge = request.GET.get('hub.challenge')

    verify_token = os.getenv('WHATSAPP_VERIFY_TOKEN', 'webhook_token_aleatorio')

    if mode == 'subscribe' and token == verify_token:
        return HttpResponse(challenge)

    return HttpResponse('Forbidden', status=403)


@login_not_required
@csrf_exempt
@require_http_methods(["POST"])
def webhook_receive(request, sessao=None):
    """
    Recebe o webhook do WAHA e vincula dinamicamente à empresa
    dona da sessão passada no parâmetro de URL.
    """
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'status': 'invalid json'}, status=400)

    # 1. Recupera a sessão ativa para identificar a empresa dinamicamente
    waha_sessao = WahaSessao.objects.filter(
        nome_sessao=sessao,
        ativa=True
    ).select_related('empresa').first()

    if not waha_sessao:
        logger.warning(f"⚠️ Sessão '{sessao}' não encontrada ou inativa.")
        return JsonResponse({'error': 'Sessao nao encontrada ou inativa'}, status=404)

    empresa = waha_sessao.empresa

    # 2. Extrai os dados do payload
    payload = body.get('payload', {})
    raw_from = payload.get('from', '')
    wa_id = raw_from.split('@')[0] if '@' in raw_from else raw_from
    msg_id = payload.get('id')
    text_body = payload.get('body', '')
    cliente_nome = payload.get('_data', {}).get('notifyName', f'Cliente {wa_id[-4:]}')

    if not wa_id or not text_body:
        return JsonResponse({'status': 'dados incompletos'}, status=400)

    # 3. Cria ou busca o Contato isolado para a empresa identificada
    contato, _ = Contato.objects.get_or_create(
        empresa=empresa,
        wa_id=wa_id,
        defaults={'nome': cliente_nome}
    )

    # 4. Cria ou busca a Conversa
    conversa, _ = Conversa.objects.get_or_create(
        empresa=empresa,
        contato=contato,
        estado__in=['triagem', 'coletando_documentos', 'aguardando_analise'],
        defaults={'estado': 'triagem'}
    )

    # 5. Salva a mensagem recebida
    Mensagem.objects.create(
        empresa=empresa,
        conversa=conversa,
        direcao='entrada',
        conteudo=text_body,
        wa_message_id=msg_id
    )

    # 6. Garante o Serviço ativo associado à empresa
    servico, _ = Servico.objects.get_or_create(
        empresa=empresa,
        nome="Atendimento Despachante",
        defaults={'ativo': True}
    )

    # 7. Cria a Tarefa no Kanban
    status_inicial = Tarefa.Status.choices[0][0]
    tarefa, criada = Tarefa.objects.get_or_create(
        empresa=empresa,
        contato=contato,
        conversa=conversa,
        defaults={
            'servico': servico,
            'status': status_inicial
        }
    )

    logger.info(f"✅ Tarefa #{tarefa.id} gerada com sucesso para {empresa.nome} (Sessão: {sessao})!")

    return JsonResponse({
        'status': 'sucesso',
        'empresa': empresa.nome,
        'sessao': sessao,
        'tarefa_id': tarefa.id,
        'criada': criada
    })


@login_required
def kanban_tarefas(request):
    """Renderiza o kanban visual de tarefas"""
    empresa = getattr(request, 'empresa', None)

    if not empresa:
        empresa_id = request.session.get('empresa_atual_id')
        if empresa_id:
            empresa = Empresa.objects.filter(id=empresa_id, ativa=True).first()

    if not empresa:
        vinculos = getattr(request.user, 'empresas_vinculadas', None)
        if vinculos:
            vinculo = vinculos.first()
            if vinculo:
                empresa = vinculo.empresa
                request.session['empresa_atual_id'] = empresa.id

    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')

    tarefas_por_status = {}
    for status, label in Tarefa.Status.choices:
        query = (
            Tarefa.objects.filter(empresa=empresa, status=status)
            .select_related('contato', 'servico', 'atendente', 'conversa')
            .prefetch_related('conversa__documentos_recebidos')
            .order_by('-criada_em')
        )
        tarefas_por_status[status] = query

    servicos = Servico.objects.filter(empresa=empresa, ativo=True)

    return render(request, 'atendimento/kanban.html', {
        'tarefas_por_status': tarefas_por_status,
        'status_choices': Tarefa.Status.choices,
        'servicos': servicos,
    })


@require_POST
@login_required
def atualizar_status_tarefa(request):
    """API endpoint para atualizar o status de uma tarefa via AJAX/Fetch"""
    tarefa_id = request.POST.get('tarefa_id')
    novo_status = request.POST.get('status')

    if not tarefa_id or not novo_status:
        return JsonResponse({'sucesso': False, 'erro': 'Parâmetros inválidos.'}, status=400)

    tarefa = get_object_or_404(Tarefa, id=tarefa_id)
    tarefa.status = novo_status
    tarefa.save()

    return JsonResponse({'sucesso': True, 'novo_status': tarefa.status})
