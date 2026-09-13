import json
import logging

from atendimento.models import Contato, Conversa, Mensagem, Tarefa, Servico
from atendimento.models import DocumentoRecebido
from django.contrib.auth.decorators import login_not_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from empresas.models import Empresa
from integracao.auth import api_empresa_required
from integracao.models import WahaSessao
from integracao.services.conversas import (
    criar_tarefa,
    obter_conversa,
    atualizar_conversa,
    registrar_mensagem_entrada,
    registrar_mensagem_saida,
    serializar_conversa,
)
from integracao.services.documentos import (
    analisar_documento_recebido,
    registrar_documento_recebido,
    revisar_documento,
)
from integracao.services.waha_client import enviar_texto, status_sessao

logger = logging.getLogger(__name__)


def _json_body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


def _erro(mensagem, status=400):
    return JsonResponse({'erro': mensagem}, status=status)


@login_not_required
@csrf_exempt
@require_http_methods(['GET'])
def health(request):
    return JsonResponse({'status': 'ok', 'servico': 'integracao'})


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['GET'])
def sessao_health(request, nome_sessao):
    sessao = WahaSessao.objects.filter(
        nome_sessao=nome_sessao, empresa=request.empresa_integracao, ativa=True).first()
    if not sessao:
        return _erro('Sessão não encontrada.', 404)
    status = status_sessao(nome_sessao)
    return JsonResponse({'sessao': nome_sessao, 'waha': status})


@login_not_required
@csrf_exempt
@require_http_methods(['POST'])
def mensagens_ingest(request):
    dados = _json_body(request)
    if dados is None:
        return _erro('JSON inválido.')
    wa_id = dados.get('wa_id', '').strip()
    conteudo = dados.get('conteudo', '').strip()
    if not wa_id or not conteudo:
        return _erro('Informe wa_id e conteudo.')
    try:
        mensagem, criada = registrar_mensagem_entrada(
            request.empresa_integracao,
            wa_id=wa_id,
            conteudo=conteudo,
            wa_message_id=dados.get('wa_message_id', ''),
            nome_contato=dados.get('nome_contato', ''),
            conversa_id=dados.get('conversa_id'),
            ator='n8n',
        )
    except ValueError as erro:
        return _erro(str(erro))
    return JsonResponse({
        'status': 'ok',
        'criada': criada,
        'mensagem_id': mensagem.id,
        'conversa_id': mensagem.conversa_id,
    }, status=201 if criada else 200)


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['POST'])
def mensagens_enviar(request):
    dados = _json_body(request)
    if dados is None:
        return _erro('JSON inválido.')
    conversa_id = dados.get('conversa_id')
    texto = dados.get('texto', '').strip()
    sessao = dados.get('sessao', '')
    if not conversa_id or not texto:
        return _erro('Informe conversa_id e texto.')

    conversa = obter_conversa(request.empresa_integracao, conversa_id)
    if not conversa:
        return _erro('Conversa não encontrada.', 404)

    mensagem = registrar_mensagem_saida(
        request.empresa_integracao, conversa, texto, ator='n8n')

    envio = {'success': False, 'skipped': True}
    if sessao and dados.get('enviar_waha', True):
        envio = enviar_texto(sessao, conversa.contato.wa_id, texto)
        if envio.get('success') and envio.get('data'):
            msg_id = str(envio['data'].get('id', ''))
            if msg_id:
                mensagem.wa_message_id = msg_id
                mensagem.save(update_fields=['wa_message_id'])

    return JsonResponse({
        'status': 'ok',
        'mensagem_id': mensagem.id,
        'waha': envio,
    })


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['GET', 'PATCH'])
def conversa_detalhe(request, conversa_id):
    conversa = obter_conversa(request.empresa_integracao, conversa_id)
    if not conversa:
        return _erro('Conversa não encontrada.', 404)
    if request.method == 'GET':
        return JsonResponse(serializar_conversa(conversa))
    dados = _json_body(request)
    if dados is None:
        return _erro('JSON inválido.')
    conversa = atualizar_conversa(
        request.empresa_integracao, conversa_id,
        estado=dados.get('estado'),
        modo=dados.get('modo'),
        servico_id=dados.get('servico_id'),
    )
    return JsonResponse(serializar_conversa(conversa))


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['POST'])
def conversa_criar_tarefa(request, conversa_id):
    dados = _json_body(request) or {}
    tarefa = criar_tarefa(
        request.empresa_integracao, conversa_id,
        resumo_triagem=dados.get('resumo_triagem', ''),
        origem=dados.get('origem', 'fluxo_completo'),
    )
    if not tarefa:
        return _erro('Conversa não encontrada.', 404)
    return JsonResponse({
        'status': 'ok',
        'tarefa_id': str(tarefa.id),
        'status_tarefa': tarefa.status,
    }, status=201)


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['POST'])
def documentos_receber(request):
    dados = _json_body(request)
    if dados is None:
        return _erro('JSON inválido.')
    try:
        doc = registrar_documento_recebido(
            request.empresa_integracao,
            dados.get('conversa_id'),
            dados.get('documento_exigido_id'),
        )
    except ValueError as erro:
        return _erro(str(erro))
    return JsonResponse({
        'status': 'ok',
        'documento_recebido_id': doc.id,
    }, status=201)


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['POST'])
def documento_analisar(request, documento_id):
    doc = DocumentoRecebido.objects.filter(
        id=documento_id, empresa=request.empresa_integracao).first()
    if not doc:
        return _erro('Documento não encontrado.', 404)
    dados = _json_body(request) or {}
    doc = analisar_documento_recebido(doc, pipeline=dados.get('pipeline', 'gemini'))
    return JsonResponse({
        'status': 'ok' if not doc.erro_analise else 'erro',
        'documento_recebido_id': doc.id,
        'resultado': doc.resultado,
        'erro_analise': doc.erro_analise,
        'analisado_em': doc.analisado_em.isoformat() if doc.analisado_em else None,
    })


@login_not_required
@api_empresa_required
@csrf_exempt
@require_http_methods(['PATCH'])
def documento_revisar(request, documento_id):
    doc = DocumentoRecebido.objects.filter(
        id=documento_id, empresa=request.empresa_integracao).first()
    if not doc:
        return _erro('Documento não encontrado.', 404)
    dados = _json_body(request)
    if dados is None:
        return _erro('JSON inválido.')
    if 'aprovado' not in dados:
        return _erro('Informe aprovado (true/false).')
    doc = revisar_documento(
        doc,
        aprovado=bool(dados['aprovado']),
        motivo=dados.get('motivo', ''),
    )
    return JsonResponse({
        'status': 'ok',
        'documento_recebido_id': doc.id,
        'status_documento': doc.status,
        'revisado_em': doc.revisado_em.isoformat() if doc.revisado_em else None,
    })


# @login_not_required
# @csrf_exempt
# @require_http_methods(['POST'])
# def webhook_waha(request, nome_sessao):
#     from django.conf import settings
#     from integracao.services.waha_webhook import processar_webhook_waha
#
#     sessao = WahaSessao.objects.filter(nome_sessao=nome_sessao, ativa=True).select_related(
#         'empresa').first()
#     if not sessao:
#         return _erro('Sessão não encontrada.', 404)
#
#     assinatura = request.headers.get('X-Webhook-Signature', '')
#     segredo = sessao.webhook_secret or getattr(settings, 'WAHA_WEBHOOK_SECRET', '')
#     if segredo and not verificar_assinatura_webhook(request.body, assinatura, segredo):
#         if getattr(settings, 'WAHA_WEBHOOK_VERIFICAR_ASSINATURA', True):
#             return _erro('Assinatura inválida.', 403)
#
#     dados = _json_body(request)
#     if dados is None:
#         return _erro('JSON inválido.')
#
#     try:
#         resultado = processar_webhook_waha(sessao, dados, request.body)
#     except Exception:
#         logger.exception('Erro ao processar webhook WAHA')
#         return _erro('Erro interno.', 500)
#     return JsonResponse(resultado)

# integracao/views.py

import json
import logging
import traceback
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.contrib.auth.decorators import login_not_required

from empresas.models import Empresa
from atendimento.models import Contato, Conversa, Mensagem, Tarefa, Servico

logger = logging.getLogger(__name__)


@login_not_required
@csrf_exempt
@require_http_methods(["POST"])
def webhook_waha(request, sessao=None):
    """
    Endpoint de recepção do webhook WAHA.
    URL: /api/v1/integracao/webhooks/waha/piloto/
    """
    try:
        body = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'invalid json'}, status=400)

    print("\n📩 [WEBHOOK WAHA RECEBIDO]")

    payload = body.get('payload', {})
    raw_from = payload.get('from', '')
    wa_id = raw_from.split('@')[0] if '@' in raw_from else raw_from
    msg_id = payload.get('id')
    text_body = payload.get('body', '')
    cliente_nome = payload.get('_data', {}).get('notifyName', f'Cliente {wa_id[-4:]}')

    if not wa_id or not text_body:
        return JsonResponse({'status': 'dados incompletos'}, status=400)

    try:
        # Busca a Empresa ID 3 (Despachante do arrozDoce)
        empresa = Empresa.objects.filter(id=3, ativa=True).first()
        if not empresa:
            print("❌ Erro: Empresa ID 3 não encontrada.")
            return JsonResponse({'error': 'Empresa não encontrada'}, status=404)

        # 1. Contato
        contato, _ = Contato.objects.get_or_create(
            empresa=empresa,
            wa_id=wa_id,
            defaults={'nome': cliente_nome}
        )

        # 2. Conversa
        conversa, _ = Conversa.objects.get_or_create(
            empresa=empresa,
            contato=contato,
            defaults={'estado': 'triagem'}
        )

        # 3. Mensagem
        Mensagem.objects.create(
            empresa=empresa,
            conversa=conversa,
            direcao='entrada',
            conteudo=text_body,
            wa_message_id=msg_id
        )

        # 4. Serviço
        servico, _ = Servico.objects.get_or_create(
            empresa=empresa,
            nome="Atendimento Despachante",
            defaults={'ativo': True}
        )

        # 5. Tarefa no Kanban
        # Tenta obter o status inicial com fallback seguro
        status_inicial = getattr(Tarefa, 'Status', None)
        status_valor = 'aberta'
        if status_inicial and hasattr(status_inicial, 'choices'):
            status_valor = status_inicial.choices[0][0]

        tarefa = Tarefa.objects.filter(empresa=empresa, conversa=conversa).first()
        criada = False

        if not tarefa:
            tarefa = Tarefa.objects.create(
                empresa=empresa,
                contato=contato,
                conversa=conversa,
                servico=servico,
                status=status_valor,
                origem='fluxo_completo',
            )
            criada = True

        print(f"🚀 [KANBAN SUCESSO] Tarefa #{tarefa.id} processada com sucesso!")

        return JsonResponse({
            'status': 'sucesso',
            'empresa': empresa.nome,
            'tarefa_id': tarefa.id,
            'criada': criada
        })

    except Exception as e:
        print("\n❌ [ERRO NO WEBHOOK WAHA]:")
        traceback.print_exc()
        return JsonResponse({'status': 'erro interno', 'detalhe': str(e)}, status=500)
