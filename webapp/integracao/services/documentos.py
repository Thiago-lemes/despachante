import logging

from django.core.files.base import ContentFile
from django.utils import timezone

from atendimento.models import Conversa, DocumentoExigido, DocumentoRecebido
from integracao.models import EventoAtendimento
from integracao.services.auditoria import registrar_evento
from integracao.services.conversas import obter_conversa

logger = logging.getLogger(__name__)


def registrar_documento_recebido(empresa, conversa_id, documento_exigido_id,
                                 *, arquivo_bytes=None, nome_arquivo='',
                                 content_type='application/pdf'):
    conversa = obter_conversa(empresa, conversa_id)
    if not conversa:
        raise ValueError('Conversa não encontrada.')
    doc_exigido = DocumentoExigido.objects.filter(
        id=documento_exigido_id, empresa=empresa).first()
    if not doc_exigido:
        raise ValueError('Documento exigido não encontrado.')

    doc = DocumentoRecebido.objects.create(
        empresa=empresa,
        conversa=conversa,
        documento_exigido=doc_exigido,
        status=DocumentoRecebido.Status.PENDENTE,
    )
    if arquivo_bytes:
        nome = nome_arquivo or f'doc_{doc.id}.pdf'
        doc.arquivo.save(nome, ContentFile(arquivo_bytes), save=True)

    conversa.estado = Conversa.Estado.AGUARDANDO_ANALISE
    conversa.save(update_fields=['estado', 'atualizada_em'])

    registrar_evento(
        empresa, EventoAtendimento.Tipo.DOCUMENTO_RECEBIDO,
        conversa=conversa, ator='n8n',
        payload={
            'documento_recebido_id': doc.id,
            'tipo': doc_exigido.tipo,
        },
    )
    return doc


def analisar_documento_recebido(documento_recebido, *, pipeline='gemini'):
    """Executa OCR/IA no arquivo do DocumentoRecebido (fase 8)."""
    from atendimento.services.analise_documento import extrair_dados_pdf

    if not documento_recebido.arquivo:
        documento_recebido.erro_analise = 'Arquivo não anexado.'
        documento_recebido.save(update_fields=['erro_analise'])
        return documento_recebido

    try:
        dados = extrair_dados_pdf(documento_recebido.arquivo.path, pipeline=pipeline)
        documento_recebido.resultado = dados
        documento_recebido.analisado_em = timezone.now()
        documento_recebido.erro_analise = ''
        documento_recebido.save(update_fields=['resultado', 'analisado_em', 'erro_analise'])
        registrar_evento(
            documento_recebido.empresa,
            EventoAtendimento.Tipo.DOCUMENTO_ANALISADO,
            conversa=documento_recebido.conversa,
            ator='sistema',
            payload={
                'documento_recebido_id': documento_recebido.id,
                'placa': dados.get('placa'),
            },
        )
    except Exception as erro:
        logger.exception('Falha na análise do documento %s', documento_recebido.id)
        documento_recebido.erro_analise = str(erro)[:1000]
        documento_recebido.save(update_fields=['erro_analise'])
    return documento_recebido


def revisar_documento(documento_recebido, *, aprovado, motivo='', revisor=None):
    status = (DocumentoRecebido.Status.APROVADO if aprovado
              else DocumentoRecebido.Status.REPROVADO)
    documento_recebido.status = status
    documento_recebido.motivo_reprovacao = '' if aprovado else motivo
    documento_recebido.revisado_em = timezone.now()
    documento_recebido.revisado_por = revisor
    documento_recebido.save(update_fields=[
        'status', 'motivo_reprovacao', 'revisado_em', 'revisado_por',
    ])
    registrar_evento(
        documento_recebido.empresa,
        EventoAtendimento.Tipo.DOCUMENTO_REVISADO,
        conversa=documento_recebido.conversa,
        ator=revisor.username if revisor else 'api',
        payload={
            'documento_recebido_id': documento_recebido.id,
            'status': status,
            'motivo': motivo[:300],
        },
    )
    return documento_recebido
