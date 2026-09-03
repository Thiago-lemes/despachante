# webapp/atendimento/services.py
import logging
import os
import requests
from django.conf import settings
from .models import Conversa, Mensagem, DocumentoRecebido, Tarefa, Servico
from integracao.services.waha_client import enviar_texto

logger = logging.getLogger(__name__)


def enviar_mensagem_whatsapp(numero_wa, texto):
    """Envia mensagem via Cloud API do Meta (legado)"""
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


def enviar_resposta_bot(conversa, texto):
    """Envia mensagem de volta para o cliente via WAHA e salva no Django."""
    from integracao.models import WahaSessao
    sessao = WahaSessao.objects.filter(empresa=conversa.empresa, ativa=True).first()

    if not sessao:
        logger.error(f"Nenhuma sessao WAHA ativa para empresa {conversa.empresa}")
        return False

    resultado = enviar_texto(
        sessao=sessao.nome_sessao,
        chat_id=conversa.contato.wa_id,
        texto=texto
    )

    if resultado['success']:
        Mensagem.objects.create(
            empresa=conversa.empresa,
            conversa=conversa,
            direcao=Mensagem.Direcao.SAIDA,
            conteudo=texto
        )
        return True
    else:
        logger.error(f"Falha ao enviar mensagem: {resultado.get('error')}")
        return False


def chamar_ia_triagem(conversa):
    """Identifica servico baseado na mensagem do cliente."""
    ultima_msg = conversa.mensagens.filter(direcao='entrada').order_by('-criada_em').first()

    if not ultima_msg:
        return None, "Desculpe, não consegui entender. Pode tentar novamente?"

    conteudo = ultima_msg.conteudo.lower()

    # Se ja identificamos servico antes e o cliente ta confirmando
    if conversa.servico and conversa.estado == Conversa.Estado.TRIAGEM:
        if 'sim' in conteudo or 'yes' in conteudo or 'confirmo' in conteudo:
            return conversa.servico, "CONFIRMACAO_RECEBIDA"
        elif 'nao' in conteudo or 'não' in conteudo:
            return None, "Tudo bem! Qual servico voce precisa?"

    # Busca servicos ativos da empresa
    servicos = Servico.objects.filter(empresa=conversa.empresa, ativo=True)

    for servico in servicos:
        if servico.nome.lower() in conteudo:
            return servico, f"Otimo! Identifiquei que voce quer: *{servico.nome}*. E isso mesmo? Responda SIM para confirmar."

    # Fallback por keyword
    if 'transfer' in conteudo or 'propriedade' in conteudo:
        try:
            servico = Servico.objects.get(empresa=conversa.empresa, nome__icontains='Transferencia', ativo=True)
            return servico, f"Voce quer fazer *{servico.nome}*. Correto? Responda SIM para confirmar."
        except Servico.DoesNotExist:
            pass

    if 'licen' in conteudo:
        try:
            servico = Servico.objects.get(empresa=conversa.empresa, nome__icontains='Licenciamento', ativo=True)
            return servico, f"Voce quer fazer *{servico.nome}*. Correto? Responda SIM para confirmar."
        except Servico.DoesNotExist:
            pass

    lista_servicos = "\n".join([f"• {s.nome}" for s in servicos[:5]])
    return None, f"Ola! Sou o assistente virtual da {conversa.empresa.nome}.\n\nQual servico voce precisa?\n{lista_servicos}\n\nDigite o nome do servico."


def processar_triagem(conversa):
    """Handler de triagem — identifica servico e envia resposta REAL."""

    # Se ja temos servico identificado e estamos aguardando confirmacao
    if conversa.servico and conversa.estado == Conversa.Estado.TRIAGEM:
        ultima_entrada = conversa.mensagens.filter(direcao='entrada').order_by('-criada_em').first()

        if ultima_entrada and (
                'sim' in ultima_entrada.conteudo.lower() or 'confirmo' in ultima_entrada.conteudo.lower()):
            # Confirmacao! Passa para coleta de documentos
            conversa.estado = Conversa.Estado.COLETANDO_DOCUMENTOS
            conversa.save()

            docs_exigidos = conversa.servico.documentos_exigidos.all()
            if docs_exigidos.exists():
                primeiro = docs_exigidos.first()
                msg_docs = f"Perfeito! Vou precisar de alguns documentos.\n\nPrimeiro: *{primeiro.tipo}*\n{primeiro.instrucoes}\n\nEnvie o documento quando estiver pronto."
                enviar_resposta_bot(conversa, msg_docs)
            else:
                criar_tarefa(conversa, 'fluxo_completo')
            return
        else:
            # Nao confirmou, pergunta de novo
            enviar_resposta_bot(conversa, "Nao entendi. Responda SIM para confirmar o servico ou digite outro servico.")
            return

    # Primeira interacao — tenta identificar o servico
    servico, resposta = chamar_ia_triagem(conversa)

    # Se retornou CONFIRMACAO_RECEBIDA, ja processamos acima
    if resposta == "CONFIRMACAO_RECEBIDA":
        return

    enviado = enviar_resposta_bot(conversa, resposta)

    if not enviado:
        logger.warning(f"Nao foi possivel enviar resposta para conversa {conversa.id}")
        return

    if servico:
        conversa.servico = servico
        conversa.save()


def processar_coleta_documentos(conversa):
    """Handler de coleta — pede documentos e cria tarefa quando completo."""
    ultima_msg = conversa.mensagens.filter(direcao='entrada').order_by('-criada_em').first()
    if not ultima_msg:
        return

    docs_exigidos = conversa.servico.documentos_exigidos.all() if conversa.servico else []
    docs_recebidos = conversa.documentos_recebidos.filter(status__in=['pendente', 'aprovado'])
    docs_recebidos_ids = set(docs_recebidos.values_list('documento_exigido_id', flat=True))
    docs_faltando = [d for d in docs_exigidos if d.id not in docs_recebidos_ids]

    if not docs_faltando:
        tarefa = criar_tarefa(conversa, 'fluxo_completo')
        resposta = f"Perfeito! Recebi todos os documentos.\n\nUm atendente em breve entrara em contato.\nSeu protocolo: *{str(tarefa.id)[:8]}*"
        enviar_resposta_bot(conversa, resposta)
        return

    proximo_doc = docs_faltando[0]
    ja_registrado = conversa.documentos_recebidos.filter(
        documento_exigido=proximo_doc
    ).exists()

    if not ja_registrado:
        DocumentoRecebido.objects.create(
            empresa=conversa.empresa,
            conversa=conversa,
            documento_exigido=proximo_doc,
            status='pendente'
        )

        docs_faltando = docs_faltando[1:]

        if docs_faltando:
            proximo = docs_faltando[0]
            resposta = f"*{proximo_doc.tipo}* recebido!\n\nAgora preciso de: *{proximo.tipo}*\n{proximo.instrucoes}"
        else:
            tarefa = criar_tarefa(conversa, 'fluxo_completo')
            resposta = f"Perfeito! Recebi todos os documentos.\n\nUm atendente em breve entrara em contato.\nSeu protocolo: *{str(tarefa.id)[:8]}*"

        enviar_resposta_bot(conversa, resposta)


def criar_tarefa(conversa, origem):
    """Cria tarefa quando triagem termina."""
    tarefa = Tarefa.objects.create(
        empresa=conversa.empresa,
        conversa=conversa,
        contato=conversa.contato,
        servico=conversa.servico,
        origem=origem,
        resumo_triagem=f"Cliente {conversa.contato.nome or 'sem nome'} ({conversa.contato.wa_id}) solicitou {conversa.servico.nome if conversa.servico else 'servico indeterminado'} via WhatsApp.",
        status='aberta'
    )

    conversa.estado = Conversa.Estado.AGUARDANDO_HUMANO
    conversa.modo = Conversa.Modo.HUMANO
    conversa.save()

    logger.info(f"Tarefa criada: {tarefa.id} para {conversa.contato.wa_id}")
    return tarefa
