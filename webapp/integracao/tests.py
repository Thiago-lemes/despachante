import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from django.contrib.auth import get_user_model

from empresas.models import Empresa, EmpresaUsuario
from atendimento.models import Contato, Conversa, Servico, Tarefa
from integracao.models import EventoAtendimento, WahaSessao, WebhookRecebido
from integracao.services.waha_service import WahaService


API_TOKEN = 'token-teste-integracao'


@override_settings(INTEGRACAO_API_TOKEN=API_TOKEN, WAHA_WEBHOOK_VERIFICAR_ASSINATURA=False)
class IntegracaoApiTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Piloto')
        self.headers = {
            'HTTP_AUTHORIZATION': f'Bearer {API_TOKEN}',
            'HTTP_X_EMPRESA_ID': str(self.empresa.id),
            'content_type': 'application/json',
        }
        self.sessao = WahaSessao.objects.create(
            empresa=self.empresa, nome_sessao='piloto')

    def test_health_publico(self):
        resposta = self.client.get(reverse('integracao_health'))
        self.assertEqual(resposta.status_code, 200)

    def test_mensagem_sem_token_retorna_401(self):
        resposta = self.client.post(
            reverse('integracao_mensagens_ingest'),
            data=json.dumps({'wa_id': '5511999999999', 'conteudo': 'oi'}),
            content_type='application/json',
        )
        self.assertEqual(resposta.status_code, 401)

    def test_ingest_mensagem_cria_conversa(self):
        resposta = self.client.post(
            reverse('integracao_mensagens_ingest'),
            data=json.dumps({'wa_id': '5511999999999', 'conteudo': 'Preciso licenciar'}),
            **self.headers,
        )
        self.assertEqual(resposta.status_code, 201)
        dados = resposta.json()
        self.assertTrue(Conversa.objects.filter(id=dados['conversa_id']).exists())
        self.assertEqual(EventoAtendimento.objects.count(), 1)

    def test_mensagem_idempotente(self):
        payload = {
            'wa_id': '5511888888888',
            'conteudo': 'teste',
            'wa_message_id': 'MSG-001',
        }
        self.client.post(reverse('integracao_mensagens_ingest'), data=json.dumps(payload), **self.headers)
        resposta = self.client.post(
            reverse('integracao_mensagens_ingest'), data=json.dumps(payload), **self.headers)
        self.assertEqual(resposta.status_code, 200)
        self.assertFalse(resposta.json()['criada'])

    def test_criar_tarefa_via_api(self):
        contato = Contato.objects.create(empresa=self.empresa, wa_id='5511777777777')
        servico = Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        conversa = Conversa.objects.create(
            empresa=self.empresa, contato=contato, servico=servico)
        resposta = self.client.post(
            reverse('integracao_conversa_criar_tarefa', args=[conversa.id]),
            data=json.dumps({'resumo_triagem': 'Cliente quer licenciamento'}),
            **self.headers,
        )
        self.assertEqual(resposta.status_code, 201)
        self.assertEqual(Tarefa.objects.count(), 1)

    def test_webhook_waha_deduplica(self):
        corpo = {
            'event': 'message',
            'payload': {
                'id': 'waha-evt-1',
                'from': '5511999999999@c.us',
                'body': 'Olá',
            },
        }
        url = reverse('integracao_webhook_waha', args=['piloto'])
        resposta1 = self.client.post(url, data=json.dumps(corpo), content_type='application/json')
        resposta2 = self.client.post(url, data=json.dumps(corpo), content_type='application/json')
        self.assertEqual(resposta1.status_code, 200)
        self.assertEqual(resposta2.json()['status'], 'duplicado')
        self.assertEqual(WebhookRecebido.objects.count(), 1)

    def _webhook(self, payload, evento='message'):
        return self.client.post(
            reverse('integracao_webhook_waha', args=['piloto']),
            data=json.dumps({'event': evento, 'payload': payload}),
            content_type='application/json',
        )

    def test_webhook_ignora_mensagem_do_proprio_sistema(self):
        resposta = self._webhook({
            'id': 'eco-1',
            'from': '5511999999999@c.us',
            'fromMe': True,
            'body': 'Olá! Sou o assistente virtual...',
        })
        self.assertEqual(resposta.json()['status'], 'ignorado')
        self.assertFalse(Conversa.objects.exists())

    @patch('atendimento.services.mensageria.enviar_texto',
           return_value={'success': True, 'data': {'id': 'out-1'}})
    def test_primeira_mensagem_nao_cria_card(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        resposta = self._webhook({
            'id': 'evt-oi',
            'from': '5511999999999@c.us',
            'body': 'Oi',
        })
        self.assertEqual(resposta.json()['status'], 'ok')
        self.assertEqual(Tarefa.objects.count(), 0)

    @patch('atendimento.services.mensageria.enviar_texto',
           return_value={'success': True, 'data': {'id': 'out-1'}})
    def test_escolha_do_servico_cria_card(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self._webhook({'id': 'evt-oi', 'from': '5511999999999@c.us', 'body': 'Oi'})
        self._webhook({'id': 'evt-1', 'from': '5511999999999@c.us', 'body': '1'})
        self.assertEqual(Tarefa.objects.count(), 1)

    @patch('atendimento.services.mensageria.enviar_texto',
           return_value={'success': True, 'data': {'id': 'out-1'}})
    def test_webhook_guarda_o_chat_id_do_lid(self, _enviar):
        self._webhook({
            'id': 'evt-lid',
            'from': '127878373056719@lid',
            'body': 'Oi',
        })
        self.assertEqual(
            Contato.objects.get().chat_id, '127878373056719@lid')

    @patch('integracao.api.views.enviar_texto')
    def test_enviar_mensagem(self, mock_enviar):
        mock_enviar.return_value = {'success': True, 'data': {'id': 'out-1'}}
        contato = Contato.objects.create(empresa=self.empresa, wa_id='5511666666666')
        conversa = Conversa.objects.create(empresa=self.empresa, contato=contato)
        resposta = self.client.post(
            reverse('integracao_mensagens_enviar'),
            data=json.dumps({
                'conversa_id': conversa.id,
                'texto': 'Resposta automática',
                'sessao': 'piloto',
            }),
            **self.headers,
        )
        self.assertEqual(resposta.status_code, 200)
        mock_enviar.assert_called_once()


class RecuperacaoDeSessaoWahaTests(TestCase):
    """Sessão FAILED: tropeço do engine vs. credencial morta.

    O aparelho desvinculado no celular deixa a credencial guardada inválida. O
    'restart' sobe a sessão com ela, o WhatsApp recusa e ela cai de novo em
    segundos — e como a tela repete a chamada a cada poucos segundos, o QR nunca
    aparece. Depois de algumas falhas seguidas o caminho é apagar a credencial.
    """

    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Teste')
        self.sessao = WahaSessao.objects.create(
            empresa=self.empresa, nome_sessao=f'empresa_{self.empresa.id}')
        self.url = reverse('gerar_qr_code_empresa', args=[self.empresa.id])
        # A rota exige sessão: quem a chama é a barra lateral de quem está logado.
        usuario = get_user_model().objects.create_user('ana', password='x')
        usuario.empresas_vinculadas.all().delete()
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=usuario, ativo=True)
        self.client.force_login(usuario)

    def chamar(self, status):
        """Simula uma passada do polling da tela com a sessão naquele status."""
        with patch('integracao.views.WahaService.obter_status_sessao',
                   return_value=status), \
             patch('integracao.views.WahaService.obter_qr_code', return_value=None), \
             patch('integracao.views.WahaService.garantir_sessao_ativa') as garantir:
            self.client.get(self.url)
        self.sessao.refresh_from_db()
        # 'WORKING' responde 'conectado' antes de mexer na sessão.
        if not garantir.call_args:
            return None
        return garantir.call_args.kwargs.get('forcar_novo_pareamento')

    def test_primeira_falha_so_reinicia(self):
        self.assertFalse(self.chamar('FAILED'))

    def test_falhas_seguidas_pedem_novo_pareamento(self):
        self.chamar('FAILED')
        self.assertTrue(self.chamar('FAILED'))

    def test_starting_no_meio_nao_zera_o_contador(self):
        """O ciclo da sessão quebrada é FAILED → STARTING → FAILED.

        Zerar no STARTING faria o laço nunca escalar — era o que travava o QR.
        """
        self.chamar('FAILED')
        self.chamar('STARTING')
        self.assertTrue(self.chamar('FAILED'))

    def test_chegar_no_qr_zera_o_contador(self):
        self.chamar('FAILED')
        self.chamar('FAILED')
        self.chamar('SCAN_QR_CODE')

        self.assertEqual(self.sessao.tentativas_recuperacao, 0)
        self.assertFalse(self.chamar('FAILED'))

    def test_conectar_zera_o_contador(self):
        """Conectar depois de falhar não pode deixar o contador armado."""
        self.chamar('FAILED')
        self.chamar('WORKING')
        self.sessao.refresh_from_db()
        self.assertEqual(self.sessao.tentativas_recuperacao, 0)


class GarantirSessaoAtivaTests(TestCase):
    """O que é disparado no WAHA em cada situação."""

    def chamadas(self, status, **kwargs):
        with patch('integracao.services.waha_service.requests.post') as post:
            WahaService.garantir_sessao_ativa(
                'empresa_1', 'http://webhook/', status, **kwargs)
        return [c.args[0] for c in post.call_args_list]

    def test_failed_reinicia(self):
        self.assertEqual(
            self.chamadas('FAILED'),
            ['http://localhost:3001/api/sessions/empresa_1/restart'])

    def test_failed_com_credencial_morta_faz_logout_e_start(self):
        self.assertEqual(
            self.chamadas('FAILED', forcar_novo_pareamento=True),
            ['http://localhost:3001/api/sessions/empresa_1/logout',
             'http://localhost:3001/api/sessions/empresa_1/start'])

    def test_sessao_subindo_nao_e_tocada(self):
        for status in ('STARTING', 'SCAN_QR_CODE', 'WORKING'):
            self.assertEqual(self.chamadas(status), [], status)
