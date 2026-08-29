import json
import logging
import os

from django import template
from django.contrib.auth.decorators import login_required
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse, HttpResponse, HttpResponseForbidden
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from empresas.models import Empresa
from .models import Contato, Conversa, Mensagem
from .models import Tarefa

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


logger = logging.getLogger(__name__)


def _empresa_webhook_padrao():
    """Mantém a compatibilidade do webhook Meta até a integração WAHA existir."""
    return Empresa.objects.get(nome='Empresa padrão', ativa=True)


@login_not_required
@csrf_exempt
@require_http_methods(["GET"])
def webhook_verify(request):
    """Verificação do webhook pelo Meta"""
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
def webhook_receive(request):
    """Recebe mensagens do WhatsApp"""
    try:
        body = json.loads(request.body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON received")
        return JsonResponse({'status': 'ok'})

    if body.get('object') != 'whatsapp_business_account':
        return JsonResponse({'status': 'ok'})

    # Extrair mensagens
    for entry in body.get('entry', []):
        for change in entry.get('changes', []):
            value = change.get('value', {})
            messages = value.get('messages', [])

            for msg in messages:
                wa_id = msg.get('from')
                msg_id = msg.get('id')
                text_body = msg.get('text', {}).get('body', '')

                if not wa_id or not text_body:
                    continue

                # Criar contato se não existir
                empresa = _empresa_webhook_padrao()
                contato, _ = Contato.objects.get_or_create(empresa=empresa, wa_id=wa_id)

                # Criar ou recuperar conversa ativa
                conversa, _ = Conversa.objects.get_or_create(
                    empresa=empresa,
                    contato=contato,
                    estado__in=['triagem', 'coletando_documentos', 'aguardando_analise'],
                    defaults={'estado': 'triagem'}
                )

                # Salvar mensagem
                Mensagem.objects.create(
                    empresa=empresa,
                    conversa=conversa,
                    direcao='entrada',
                    conteudo=text_body,
                    wa_message_id=msg_id
                )

                logger.info(f"Mensagem salva: {msg_id} de {wa_id}")

    return JsonResponse({'status': 'ok'})


@login_required
def kanban_tarefas(request):
    """Renderiza o kanban visual de tarefas"""
    tarefas_por_status = {}
    if not request.empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')
    for status, label in Tarefa.Status.choices:
        # Adicionar select_related pra garantir dados frescos
        tarefas_por_status[status] = Tarefa.objects.filter(
            empresa=request.empresa,
            status=status
        ).select_related('contato', 'servico', 'atendente').order_by('-criada_em')

    return render(request, 'atendimento/kanban.html', {
        'tarefas_por_status': tarefas_por_status,
        'status_choices': Tarefa.Status.choices
    })


@csrf_exempt
@login_required
@require_http_methods(["POST"])
def atualizar_status_tarefa(request):
    """API: move uma tarefa pra outro status e vincula atendente"""
    from django.utils import timezone

    try:
        data = json.loads(request.body)
        tarefa_id = data.get('tarefa_id')
        novo_status = data.get('novo_status')

        if not request.empresa:
            return JsonResponse({'status': 'error', 'message': 'Empresa ativa ausente.'}, status=403)
        if novo_status not in Tarefa.Status.values:
            return JsonResponse({'status': 'error', 'message': 'Status inválido.'}, status=400)

        tarefa = Tarefa.objects.filter(id=tarefa_id, empresa=request.empresa).first()
        if not tarefa:
            return JsonResponse({'status': 'error', 'message': 'Tarefa não encontrada.'}, status=404)
        tarefa.status = novo_status

        # Se mudar pra em_atendimento, seta atendente
        if novo_status == 'em_atendimento':
            if request.user and not request.user.is_anonymous:
                tarefa.atendente = request.user
                tarefa.assumida_em = timezone.now()

        # Se marcar concluída
        if novo_status == 'concluida':
            tarefa.concluida_em = timezone.now()

        tarefa.save()
        return JsonResponse({'status': 'ok'})
    except Exception as e:
        logger.exception('Não foi possível atualizar a tarefa.')
        return JsonResponse({'status': 'error', 'message': str(e)}, status=400)
