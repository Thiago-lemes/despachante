from django.core.management.base import BaseCommand
from django.db import transaction
from atendimento.models import Conversa
from integracao.services.documentos import analisar_documento_recebido
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Worker de análise de documentos.

    Triagem e coleta não passam mais por aqui: o bot roda por evento, dentro do
    webhook do WAHA. Varrer conversas para conversar com o cliente respondia a
    mesma mensagem a cada ciclo, porque nada registrava o que já fora
    respondido. A análise de documento continua no worker por ser cara (OCR/IA)
    e por poder repetir sem efeito visível para o cliente.
    """

    help = 'Analisa documentos das conversas em "aguardando_analise"'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true',
                            help='Processa uma conversa e sai')

    def handle(self, *args, **options):
        if options['once']:
            self.processar_uma()
        else:
            self.processar_loop()

    def processar_uma(self):
        with transaction.atomic():
            # select_for_update: dois workers não pegam a mesma conversa.
            conversas_pendentes = Conversa.objects.filter(
                estado=Conversa.Estado.AGUARDANDO_ANALISE
            ).select_for_update(skip_locked=True)[:1]

            if not conversas_pendentes:
                logger.info('Nenhuma conversa aguardando análise')
                return

            self.processar_analise(conversas_pendentes[0])

    def processar_analise(self, conversa):
        doc = conversa.documentos_recebidos.filter(
            analisado_em__isnull=True,
        ).exclude(arquivo='').first()
        if not doc:
            logger.info('Conversa %s: nenhum documento pendente de análise', conversa.id)
            return
        analisar_documento_recebido(doc)
        pendentes = conversa.documentos_recebidos.filter(analisado_em__isnull=True).exists()
        if not pendentes:
            conversa.estado = Conversa.Estado.COLETANDO_DOCUMENTOS
            conversa.save(update_fields=['estado', 'atualizada_em'])

    def processar_loop(self):
        self.stdout.write('Worker de análise iniciado.')
        while True:
            self.processar_uma()
            time.sleep(2)
