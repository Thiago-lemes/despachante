import shutil
import tempfile
from unittest.mock import patch

import requests
from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import UploadForm
from .models import Documento, Lote
from .services import processar

TEST_MEDIA_ROOT = tempfile.mkdtemp(prefix='despachante-tests-')
TEST_STORAGES = {
    'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'},
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def tearDownModule():
    shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)


def pdf(nome='documento.pdf', marcador=b'conteudo'):
    return SimpleUploadedFile(
        nome, b'%PDF-1.4\n' + marcador + b'\n%%EOF', content_type='application/pdf')


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STORAGES=TEST_STORAGES)
class UploadEPermissoesTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user('ana', 'ana@example.com', 'senha-segura')
        self.outro = User.objects.create_user('bia', 'bia@example.com', 'senha-segura')
        self.client.force_login(self.usuario)

    def test_upload_avulso_entra_na_fila_gemini(self):
        resposta = self.client.post(reverse('enviar'), {
            'modo': 'avulso', 'arquivos': pdf(),
        })
        documento = Documento.objects.get()
        self.assertRedirects(resposta, reverse('detalhe', args=[documento.pk]))
        self.assertEqual(documento.pipeline, 'gemini')
        self.assertEqual(documento.status, 'aguardando')
        self.assertEqual(Lote.objects.get().modo, 'avulso')

    def test_lote_usa_openai_e_aceita_multiplos(self):
        resposta = self.client.post(reverse('enviar'), {
            'modo': 'lote',
            'arquivos': [pdf('a.pdf', b'a'), pdf('b.pdf', b'b')],
        })
        lote = Lote.objects.get()
        self.assertRedirects(resposta, reverse('lote_detalhe', args=[lote.pk]))
        self.assertEqual(lote.itens.count(), 2)
        self.assertEqual(set(Documento.objects.values_list('pipeline', flat=True)), {'openai'})

    def test_duplicado_reutiliza_apenas_no_mesmo_pipeline(self):
        for _ in range(2):
            self.client.post(reverse('enviar'), {
                'modo': 'avulso', 'arquivos': pdf(marcador=b'igual'),
            })
        self.assertEqual(Documento.objects.count(), 1)
        self.assertEqual(Lote.objects.count(), 2)
        self.assertTrue(Lote.objects.first().itens.get().reutilizado)

        self.client.post(reverse('enviar'), {
            'modo': 'lote', 'arquivos': pdf(marcador=b'igual'),
        })
        self.assertEqual(Documento.objects.count(), 2)

    def test_usuario_nao_acessa_documento_de_terceiro(self):
        documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=self.outro, status='concluido')
        for nome in ('detalhe', 'arquivo'):
            resposta = self.client.get(reverse(nome, args=[documento.pk]))
            self.assertEqual(resposta.status_code, 404)

    def test_arquivo_do_proprietario_abre_inline(self):
        documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=self.usuario, status='concluido')
        resposta = self.client.get(reverse('arquivo', args=[documento.pk]))
        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta['Content-Type'], 'application/pdf')
        self.assertIn('inline', resposta['Content-Disposition'])

    def test_busca_nao_mostra_resultado_de_terceiro(self):
        Documento.objects.create(
            arquivo=pdf(), enviado_por=self.outro, status='concluido', placa='ABC1D23')
        resposta = self.client.get(reverse('busca'), {'placa': 'ABC1D23'})
        self.assertContains(resposta, 'não encontrada')
        self.assertNotContains(resposta, 'Ver arquivo')

    def test_dono_exclui_documento_e_arquivo_some_do_disco(self):
        documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=self.usuario, status='concluido')
        storage = documento.arquivo.storage
        nome_arquivo = documento.arquivo.name
        self.assertTrue(storage.exists(nome_arquivo))
        resposta = self.client.post(reverse('excluir', args=[documento.pk]))
        self.assertRedirects(resposta, reverse('historico'))
        self.assertFalse(Documento.objects.filter(pk=documento.pk).exists())
        self.assertFalse(storage.exists(nome_arquivo))

    def test_usuario_nao_exclui_documento_de_terceiro(self):
        documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=self.outro, status='concluido')
        resposta = self.client.post(reverse('excluir', args=[documento.pk]))
        self.assertEqual(resposta.status_code, 404)
        self.assertTrue(Documento.objects.filter(pk=documento.pk).exists())

    def test_get_em_excluir_nao_apaga_documento(self):
        documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=self.usuario, status='concluido')
        resposta = self.client.get(reverse('excluir', args=[documento.pk]))
        self.assertRedirects(resposta, reverse('detalhe', args=[documento.pk]))
        self.assertTrue(Documento.objects.filter(pk=documento.pk).exists())

    def test_formulario_rejeita_falso_pdf(self):
        falso = SimpleUploadedFile('arquivo.pdf', b'nao e pdf')
        formulario = UploadForm(data={'modo': 'avulso'}, files={'arquivos': falso})
        self.assertFalse(formulario.is_valid())
        self.assertIn('PDF válido', formulario.errors['arquivos'][0])


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STORAGES=TEST_STORAGES)
class ListagensTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user('carlos', 'carlos@example.com', 'senha-segura')
        self.outro = User.objects.create_user('debora', 'debora@example.com', 'senha-segura')
        self.client.force_login(self.usuario)

    def test_historico_mostra_apenas_concluido_e_erro(self):
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='concluido')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='erro')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='aguardando')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='processando')
        resposta = self.client.get(reverse('historico'))
        self.assertEqual(len(resposta.context['documentos']), 2)
        for documento in resposta.context['documentos']:
            self.assertIn(documento.status, ('concluido', 'erro'))

    def test_em_processamento_mostra_apenas_fila_e_processando(self):
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='concluido')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='aguardando')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='processando')
        Documento.objects.create(arquivo=pdf(), enviado_por=self.outro, status='aguardando')
        resposta = self.client.get(reverse('em_processamento'))
        self.assertEqual(len(resposta.context['documentos']), 2)
        self.assertEqual(resposta.context['resumo']['total'], 2)

    def test_em_processamento_vazio_mostra_cards_zerados(self):
        resposta = self.client.get(reverse('em_processamento'))
        self.assertEqual(resposta.context['resumo'], {'aguardando': 0, 'processando': 0, 'total': 0})
        self.assertContains(resposta, 'Não há itens em processamento')

    def test_em_processamento_status_json(self):
        Documento.objects.create(arquivo=pdf(), enviado_por=self.usuario, status='aguardando')
        resposta = self.client.get(reverse('em_processamento_status'))
        self.assertEqual(resposta.json()['resumo']['aguardando'], 1)


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, STORAGES=TEST_STORAGES)
class PipelineTests(TestCase):
    def setUp(self):
        usuario = get_user_model().objects.create_user('operador')
        self.documento = Documento.objects.create(
            arquivo=pdf(), enviado_por=usuario, pipeline='openai', status='processando')

    @patch('documentos.services._renderizar', return_value=['pagina.png'])
    @patch('documentos.services._openai_extrair', return_value={
        'placa': 'ABC1D23', 'renavam': '123', 'proprietario': 'Maria'})
    def test_lote_conclui_com_openai(self, openai, renderizar):
        processar(self.documento)
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.status, 'concluido')
        self.assertEqual(self.documento.provedor_utilizado, 'OpenAI')
        self.assertFalse(self.documento.usou_fallback)
        self.assertEqual(self.documento.placa, 'ABC1D23')

    @patch('documentos.services._renderizar', return_value=['pagina.png'])
    @patch('documentos.services._openai_extrair',
           side_effect=requests.RequestException('erro openai'))
    @patch('documentos.services._gemini_extrair', return_value={
        'placa': 'DEF2E34', 'renavam': '456', 'proprietario': 'Joao'})
    def test_openai_falha_usa_gemini(self, gemini, openai, renderizar):
        processar(self.documento)
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.status, 'concluido')
        self.assertEqual(self.documento.provedor_utilizado, 'Gemini')
        self.assertTrue(self.documento.usou_fallback)
        self.assertIn('erro openai', self.documento.motivo_fallback)

    @patch('documentos.management.commands.processar_documentos.processar')
    def test_worker_reivindica_documento(self, processar_mock):
        self.documento.status = 'aguardando'
        self.documento.save(update_fields=['status'])

        def concluir(documento):
            documento.status = 'concluido'
            documento.save(update_fields=['status'])
        processar_mock.side_effect = concluir
        call_command('processar_documentos', '--once')
        self.documento.refresh_from_db()
        self.assertEqual(self.documento.status, 'concluido')
        self.assertEqual(self.documento.tentativas, 1)


class CadastroTests(TestCase):
    def test_cria_conta_e_loga_automaticamente(self):
        resposta = self.client.post(reverse('cadastro'), {
            'username': 'diego', 'email': 'diego@example.com',
            'password1': 'uma-senha-bem-forte-123', 'password2': 'uma-senha-bem-forte-123',
        })
        self.assertRedirects(resposta, reverse('busca'))
        usuario = get_user_model().objects.get(username='diego')
        self.assertEqual(usuario.email, 'diego@example.com')
        resposta = self.client.get(reverse('historico'))
        self.assertEqual(resposta.status_code, 200)

    def test_email_duplicado_e_rejeitado(self):
        get_user_model().objects.create_user('existente', 'usado@example.com', 'senha-antiga')
        resposta = self.client.post(reverse('cadastro'), {
            'username': 'novo', 'email': 'usado@example.com',
            'password1': 'uma-senha-bem-forte-123', 'password2': 'uma-senha-bem-forte-123',
        })
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(get_user_model().objects.filter(username='novo').exists())

    def test_pagina_de_cadastro_acessivel_sem_login(self):
        resposta = self.client.get(reverse('cadastro'))
        self.assertEqual(resposta.status_code, 200)


class ContaTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            'carla', 'carla@example.com', 'senha-antiga')
        self.client.force_login(self.usuario)

    def test_atualiza_nome_e_email(self):
        resposta = self.client.post(reverse('conta'), {
            'first_name': 'Carla', 'last_name': 'Souza', 'email': 'nova@example.com',
        })
        self.assertRedirects(resposta, reverse('conta'))
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.first_name, 'Carla')
        self.assertEqual(self.usuario.email, 'nova@example.com')

    def test_email_invalido_nao_salva(self):
        resposta = self.client.post(reverse('conta'), {
            'first_name': '', 'last_name': '', 'email': 'nao-e-um-email',
        })
        self.assertEqual(resposta.status_code, 200)
        self.usuario.refresh_from_db()
        self.assertEqual(self.usuario.email, 'carla@example.com')

    def test_pagina_de_troca_de_senha_carrega(self):
        resposta = self.client.get(reverse('password_change'))
        self.assertEqual(resposta.status_code, 200)


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
class RecuperacaoSenhaTests(TestCase):
    def setUp(self):
        get_user_model().objects.create_user(
            'usuario', 'usuario@example.com', 'senha-antiga')

    def test_envia_link_para_email_cadastrado(self):
        resposta = self.client.post(
            reverse('password_reset'), {'email': 'usuario@example.com'})
        self.assertRedirects(resposta, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('/accounts/reset/', mail.outbox[0].body)

    def test_email_desconhecido_mantem_resposta_generica(self):
        resposta = self.client.post(
            reverse('password_reset'), {'email': 'desconhecido@example.com'})
        self.assertRedirects(resposta, reverse('password_reset_done'))
        self.assertEqual(len(mail.outbox), 0)
