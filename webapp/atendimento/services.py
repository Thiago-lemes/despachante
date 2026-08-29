import logging
import os
import requests
from .models import Conversa, Mensagem, DocumentoRecebido, Tarefa
from django.utils import timezone

logger = logging.getLogger(__name__)


def enviar_mensagem_whatsapp(numero_wa, texto):
    """Envia mensagem via Cloud API do Meta"""
    access_token = os.getenv('WHATSAPP_ACCESS_TOKEN')
    phone_number_id = os.getenv('WHATSAPP_PHONE_NUMBER_ID')

    if not access_token or not phone_number_id:
        logger.error("WhatsApp credentials not configured")
        return {'success': False, 'error': 'Credentials not configured'}

    url = f'https://graph.facebook.com/v18.0/{phone_number_id}/messages'

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    payload = {
        'messaging_product': 'whatsapp',
        'to': numero_wa,
        'type': 'text',
        'text': {'body': texto}
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        result = response.json()
        logger.info(f"Mensagem enviada pra {numero_wa}: {result}")
        return {'success': True, 'data': result}
    except requests.exceptions.RequestException as e:
        logger.error(f"Erro ao enviar mensagem pra {numero_wa}: {e}")
        return {'success': False, 'error': str(e)}


def chamar_ia_triagem(conversa):
    """Chama IA pra identificar serviço (mockado por enquanto)"""
    ultima_msg = conversa.mensagens.filter(direcao='entrada').order_by('-criada_em').first()

    if not ultima_msg:
        return None, "Desculpe, não consegui entender. Pode tentar novamente?"

    # Mockado pra teste — depois integra com Gemini/OpenAI real
    conteudo = ultima_msg.conteudo.lower()

    if 'transfer' in conteudo or 'propriedade' in conteudo:
        return 'Transferência de propriedade', "Ótimo! Identifiquei que você quer uma transferência de propriedade. É isso mesmo?"

    if 'licen' in conteudo:
        return 'Licenciamento', "Você quer fazer licenciamento do veículo. Correto?"

    return None, f"Recebi sua mensagem. Pode ser mais específico sobre o que você precisa?"


def processar_triagem(conversa):
    """Handler de triagem — identifica serviço"""
    servico_nome, resposta = chamar_ia_triagem(conversa)

    # Enviar resposta (mockado por enquanto — não tá enviando pro WhatsApp de verdade ainda)
    logger.info(f"Bot responderia: {resposta}")

    # Salvar resposta como mensagem de saída
    Mensagem.objects.create(
        empresa=conversa.empresa,
        conversa=conversa,
        direcao='saida',
        conteudo=resposta
    )

    # Se identificou serviço, mover pro próximo estado
    if servico_nome:
        from .models import Servico
        try:
            servico = Servico.objects.get(
                empresa=conversa.empresa,
                nome__icontains=servico_nome[:10],
                ativo=True,
            )
            conversa.servico = servico
            conversa.estado = 'coletando_documentos'
            conversa.save()
            logger.info(f"Conversa {conversa.id}: identificado serviço {servico.nome}")
        except Servico.DoesNotExist:
            logger.warning(f"Serviço '{servico_nome}' não encontrado no BD")


def processar_coleta_documentos(conversa):
    """Handler de coleta — pede documentos"""
    ultima_msg = conversa.mensagens.filter(direcao='entrada').order_by('-criada_em').first()

    if not ultima_msg:
        return

    # Verificar qual documento falta
    docs_exigidos = conversa.servico.documentos_exigidos.all() if conversa.servico else []
    docs_já_recebidos = conversa.documentos_recebidos.values_list('documento_exigido_id', flat=True)

    docs_faltando = docs_exigidos.exclude(id__in=docs_já_recebidos)

    if not docs_faltando.exists():
        # Todos os documentos foram coletados!
        tarefa = criar_tarefa(conversa, 'fluxo_completo')
        resposta = f"Perfeito! Recebi todos os documentos. Um atendente em breve entrará em contato. Seu protocolo é: {str(tarefa.id)[:8]}"
    else:
        # Criar registro de documento recebido e pedir o próximo
        proximo_doc = docs_faltando.first()
        DocumentoRecebido.objects.create(
            empresa=conversa.empresa,
            conversa=conversa,
            documento_exigido=proximo_doc,
            status='pendente'
        )
        resposta = f"Documento recebido! Agora preciso de: {proximo_doc.instrucoes}"

    # Salvar como mensagem de saída
    Mensagem.objects.create(
        empresa=conversa.empresa,
        conversa=conversa,
        direcao='saida',
        conteudo=resposta
    )
    logger.info(f"Bot responderia: {resposta}")


def criar_tarefa(conversa, origem):
    """Cria tarefa quando triagem termina"""
    tarefa = Tarefa.objects.create(
        empresa=conversa.empresa,
        conversa=conversa,
        contato=conversa.contato,
        servico=conversa.servico,
        origem=origem,
        resumo_triagem=f"Cliente {conversa.contato.nome or 'sem nome'} quer {conversa.servico.nome if conversa.servico else 'indeterminado'}.",
        status='aberta'
    )

    # Mover conversa pro estado final e desativar bot
    conversa.estado = 'aguardando_humano'
    conversa.modo = 'humano'
    conversa.save()

    logger.info(f"Tarefa criada: {tarefa.id} para {conversa.contato.wa_id}")

    return tarefa
