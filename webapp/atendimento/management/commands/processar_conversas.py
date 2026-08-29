from django.core.management.base import BaseCommand
from django.db import transaction
from atendimento.models import Conversa
from atendimento.services import processar_triagem, processar_coleta_documentos
from integracao.services.documentos import analisar_documento_recebido
import logging
import time

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Processa conversas em fila: triagem, coleta de docs, criação de tarefa'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Processa uma conversa e sai')

    def handle(self, *args, **options):
        if options['once']:
            self.processar_uma()
        else:
            self.processar_loop()

    def processar_uma(self):
        """Reivindica uma conversa e processa"""
        with transaction.atomic():
            # Select for update: garante que dois workers não peguem a mesma conversa
            conversas_pendentes = Conversa.objects.filter(
                modo='bot',
                estado__in=['triagem', 'coletando_documentos', 'aguardando_analise']
            ).select_for_update(skip_locked=True)[:1]

            if not conversas_pendentes:
                logger.info("Nenhuma conversa pendente")
                return

            conversa = conversas_pendentes[0]
            logger.info(f"Processando conversa {conversa.id}")

            # Orquestar handlers
            if conversa.estado == 'triagem':
                processar_triagem(conversa)
            elif conversa.estado == 'coletando_documentos':
                processar_coleta_documentos(conversa)
            elif conversa.estado == 'aguardando_analise':
                self.processar_analise(conversa)

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
            conversa.estado = 'coletando_documentos'
            conversa.save(update_fields=['estado', 'atualizada_em'])

    def processar_loop(self):
        """Loop infinito processando conversas"""
        self.stdout.write("Worker iniciado. Processando conversas...")
        while True:
            self.processar_uma()
            time.sleep(2)