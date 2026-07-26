import time
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from documentos.models import Documento
from documentos.services import processar


class Command(BaseCommand):
    help = 'Processa a fila de documentos de forma sequencial.'

    def add_arguments(self, parser):
        parser.add_argument('--once', action='store_true', help='Processa a fila atual e encerra.')
        parser.add_argument('--sleep', type=float, default=2.0, help='Espera entre consultas a fila.')

    def handle(self, *args, **options):
        self._recuperar_abandonados()
        while True:
            documento = self._reivindicar()
            if documento:
                self.stdout.write(f'Processando documento {documento.pk}')
                processar(documento)
                continue
            if options['once']:
                break
            time.sleep(options['sleep'])

    def _recuperar_abandonados(self):
        limite = timezone.now() - timedelta(minutes=15)
        Documento.objects.filter(
            status='processando', processamento_iniciado_em__lt=limite,
        ).update(status='aguardando', processamento_iniciado_em=None)

    def _reivindicar(self):
        with transaction.atomic():
            candidato = (Documento.objects.filter(status='aguardando')
                          .order_by('enviado_em').first())
            if not candidato:
                return None
            atualizado = Documento.objects.filter(
                pk=candidato.pk, status='aguardando',
            ).update(
                status='processando',
                processamento_iniciado_em=timezone.now(),
                processamento_finalizado_em=None,
                tentativas=candidato.tentativas + 1,
                erro='',
            )
            if not atualizado:
                return None
        candidato.refresh_from_db()
        return candidato
