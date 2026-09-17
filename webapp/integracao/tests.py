import json
from unittest.mock import patch

from django.test import TestCase, override_settings
from django.urls import reverse

from empresas.models import Empresa, EmpresaUsuario
from atendimento.models import Contato, Conversa, Servico, Tarefa
from integracao.models import EventoAtendimento, WahaSessao, WebhookRecebido


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

    @patch('atendimento.services.bot.enviar_texto',
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

    @patch('atendimento.services.bot.enviar_texto',
           return_value={'success': True, 'data': {'id': 'out-1'}})
    def test_escolha_do_servico_cria_card(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self._webhook({'id': 'evt-oi', 'from': '5511999999999@c.us', 'body': 'Oi'})
        self._webhook({'id': 'evt-1', 'from': '5511999999999@c.us', 'body': '1'})
        self.assertEqual(Tarefa.objects.count(), 1)

    @patch('atendimento.services.bot.enviar_texto',
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
