import json
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from empresas.models import Empresa, EmpresaUsuario
from integracao.models import WahaSessao
from integracao.services.conversas import obter_ou_criar_conversa

from .models import (
    Contato, Conversa, DocumentoExigido, DocumentoRecebido, Mensagem,
    Servico, Tarefa,
)
from .services import bot


class IsolamentoEmpresaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario_a = User.objects.create_user('ana', password='senha-segura')
        self.usuario_b = User.objects.create_user('bia', password='senha-segura')
        self.empresa_a = self.vincular(self.usuario_a, 'Despachante A')
        self.empresa_b = self.vincular(self.usuario_b, 'Despachante B')
        self.tarefa_a = self.criar_tarefa(self.empresa_a, '11111111111')
        self.tarefa_b = self.criar_tarefa(self.empresa_b, '22222222222')
        self.client.force_login(self.usuario_a)

    @staticmethod
    def vincular(usuario, nome_empresa):
        empresa = Empresa.objects.create(nome=nome_empresa)
        EmpresaUsuario.objects.create(empresa=empresa, usuario=usuario)
        return empresa

    @staticmethod
    def criar_tarefa(empresa, wa_id):
        contato = Contato.objects.create(empresa=empresa, wa_id=wa_id, nome='Cliente')
        servico = Servico.objects.create(empresa=empresa, nome='Licenciamento')
        conversa = Conversa.objects.create(empresa=empresa, contato=contato, servico=servico)
        return Tarefa.objects.create(
            empresa=empresa,
            conversa=conversa,
            contato=contato,
            servico=servico,
            origem=Tarefa.Origem.FLUXO_COMPLETO,
            resumo_triagem='Teste de isolamento',
        )

    def test_kanban_exibe_apenas_tarefas_da_empresa_ativa(self):
        resposta = self.client.get(reverse('kanban_tarefas'))

        abertas = resposta.context['tarefas_por_status'][Tarefa.Status.ABERTA]
        self.assertEqual(list(abertas), [self.tarefa_a])

    def test_nao_atualiza_tarefa_de_outra_empresa(self):
        resposta = self.client.post(
            reverse('atualizar_status_tarefa'),
            data=json.dumps({
                'tarefa_id': str(self.tarefa_b.id),
                'novo_status': Tarefa.Status.EM_ATENDIMENTO,
            }),
            content_type='application/json',
        )

        self.assertEqual(resposta.status_code, 404)
        self.tarefa_b.refresh_from_db()
        self.assertEqual(self.tarefa_b.status, Tarefa.Status.ABERTA)


@patch('atendimento.services.bot.enviar_texto',
       return_value={'success': True, 'data': {'id': 'out-1'}})
class BotTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Teste')
        WahaSessao.objects.create(empresa=self.empresa, nome_sessao='teste')
        self.licenciamento = Servico.objects.create(
            empresa=self.empresa, nome='Licenciamento')
        self.transferencia = Servico.objects.create(
            empresa=self.empresa, nome='Transferência')
        self.contato = Contato.objects.create(
            empresa=self.empresa, wa_id='127878373056719',
            chat_id='127878373056719@lid')
        self.conversa = Conversa.objects.create(
            empresa=self.empresa, contato=self.contato)

    def receber(self, texto, *, tem_midia=False):
        mensagem = Mensagem.objects.create(
            empresa=self.empresa, conversa=self.conversa,
            direcao=Mensagem.Direcao.ENTRADA, conteudo=texto)
        self.conversa.refresh_from_db()
        bot.processar_mensagem(self.conversa, mensagem, tem_midia=tem_midia)
        self.conversa.refresh_from_db()

    @property
    def saidas(self):
        return list(
            self.conversa.mensagens
            .filter(direcao=Mensagem.Direcao.SAIDA)
            .order_by('criada_em').values_list('conteudo', flat=True)
        )

    def test_primeira_mensagem_recebe_o_menu_uma_vez(self, _enviar):
        self.receber('Oi')
        self.assertEqual(len(self.saidas), 1)
        self.assertIn('1 - Licenciamento', self.saidas[0])
        self.assertIn('3 - Falar com um atendente', self.saidas[0])
        self.assertFalse(Tarefa.objects.exists())

    def test_envio_usa_o_chat_id_e_nao_o_wa_id(self, enviar):
        self.receber('Oi')
        self.assertEqual(
            enviar.call_args.kwargs['chat_id'], '127878373056719@lid')

    def test_escolher_servico_cria_o_card(self, _enviar):
        self.receber('Oi')
        self.receber('2')

        tarefa = Tarefa.objects.get()
        self.assertEqual(tarefa.servico, self.transferencia)
        self.assertEqual(self.conversa.servico, self.transferencia)
        # Sem documentos exigidos, o atendimento já vai para o humano.
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertIn('Protocolo', self.saidas[-1])

    def test_numero_no_meio_do_texto_nao_e_escolha(self, _enviar):
        self.receber('Oi')
        self.receber('quero a 2ª via do CRLV')
        self.assertFalse(Tarefa.objects.exists())
        self.assertIn('Não entendi', self.saidas[-1])

    def test_tres_respostas_invalidas_transferem_para_humano(self, _enviar):
        self.receber('Oi')
        self.receber('asdf')
        self.receber('blá')
        self.receber('???')

        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(self.conversa.estado, Conversa.Estado.AGUARDANDO_HUMANO)
        self.assertEqual(Tarefa.objects.count(), 1)
        self.assertIn('atendente', self.saidas[-1])

    def test_opcao_de_atendente_no_menu_transfere(self, _enviar):
        self.receber('Oi')
        self.receber('3')
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(Tarefa.objects.count(), 1)

    def test_bot_cala_quando_a_conversa_esta_em_modo_humano(self, _enviar):
        self.conversa.modo = Conversa.Modo.HUMANO
        self.conversa.save()
        self.receber('Oi')
        self.assertEqual(self.saidas, [])

    def test_coleta_de_documentos_ate_o_fim(self, _enviar):
        DocumentoExigido.objects.create(
            empresa=self.empresa, servico=self.licenciamento,
            tipo='CRLV', instrucoes='Foto do documento do veículo.')
        DocumentoExigido.objects.create(
            empresa=self.empresa, servico=self.licenciamento,
            tipo='CNH', instrucoes='Foto da sua CNH.')

        self.receber('Oi')
        self.receber('1')

        # Card nasce na escolha, mas o bot segue conduzindo a coleta.
        tarefa = Tarefa.objects.get()
        self.assertEqual(self.conversa.modo, Conversa.Modo.BOT)
        self.assertEqual(self.conversa.estado, Conversa.Estado.COLETANDO_DOCUMENTOS)
        self.assertIn('CRLV', self.saidas[-1])

        # Texto durante a coleta não vale como documento enviado.
        self.receber('e aí?')
        self.assertEqual(DocumentoRecebido.objects.count(), 0)
        self.assertIn('Ainda preciso', self.saidas[-1])

        self.receber('', tem_midia=True)
        self.assertEqual(DocumentoRecebido.objects.count(), 1)
        self.assertIn('CNH', self.saidas[-1])
        tarefa.refresh_from_db()
        self.assertIn('Documentos: 1 de 2.', tarefa.resumo_triagem)

        self.receber('', tem_midia=True)
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(self.conversa.estado, Conversa.Estado.AGUARDANDO_HUMANO)
        self.assertIn('Recebi todos os documentos', self.saidas[-1])
        # Nenhum card extra foi criado no caminho.
        self.assertEqual(Tarefa.objects.count(), 1)


class KanbanSilenciaBotTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user('caio', password='senha-segura')
        self.empresa = Empresa.objects.create(nome='Despachante do Caio')
        EmpresaUsuario.objects.create(empresa=self.empresa, usuario=self.usuario)
        contato = Contato.objects.create(empresa=self.empresa, wa_id='5541999999999')
        self.conversa = Conversa.objects.create(
            empresa=self.empresa, contato=contato, modo=Conversa.Modo.BOT)
        self.tarefa = Tarefa.objects.create(
            empresa=self.empresa, conversa=self.conversa, contato=contato,
            origem=Tarefa.Origem.FLUXO_COMPLETO, resumo_triagem='Pedido')
        self.client.force_login(self.usuario)

    def mover(self, status):
        return self.client.post(
            reverse('atualizar_status_tarefa'),
            data=json.dumps({'tarefa_id': str(self.tarefa.id), 'novo_status': status}),
            content_type='application/json',
        )

    def test_assumir_o_card_poe_a_conversa_em_modo_humano(self):
        self.assertEqual(self.mover(Tarefa.Status.EM_ATENDIMENTO).status_code, 200)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)

    def test_devolver_para_aberta_nao_religa_o_bot(self):
        self.mover(Tarefa.Status.EM_ATENDIMENTO)
        self.mover(Tarefa.Status.ABERTA)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)


class ExpiracaoDeConversaTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Teste')
        self.contato = Contato.objects.create(empresa=self.empresa, wa_id='5541988888888')

    def envelhecer(self, conversa, horas):
        Conversa.objects.filter(pk=conversa.pk).update(
            atualizada_em=timezone.now() - timedelta(hours=horas))

    def test_conversa_do_bot_parada_ha_mais_de_48h_recomeca(self):
        antiga = Conversa.objects.create(
            empresa=self.empresa, contato=self.contato,
            estado=Conversa.Estado.COLETANDO_DOCUMENTOS)
        self.envelhecer(antiga, 49)

        nova, criada = obter_ou_criar_conversa(self.empresa, self.contato)

        self.assertTrue(criada)
        self.assertNotEqual(nova.pk, antiga.pk)
        self.assertEqual(nova.estado, Conversa.Estado.TRIAGEM)
        antiga.refresh_from_db()
        self.assertEqual(antiga.estado, Conversa.Estado.ENCERRADA)

    def test_conversa_em_modo_humano_nao_expira(self):
        antiga = Conversa.objects.create(
            empresa=self.empresa, contato=self.contato,
            modo=Conversa.Modo.HUMANO,
            estado=Conversa.Estado.AGUARDANDO_HUMANO)
        self.envelhecer(antiga, 200)

        conversa, criada = obter_ou_criar_conversa(self.empresa, self.contato)

        self.assertFalse(criada)
        self.assertEqual(conversa.pk, antiga.pk)

    def test_conversa_recente_continua(self):
        antiga = Conversa.objects.create(empresa=self.empresa, contato=self.contato)
        self.envelhecer(antiga, 10)

        conversa, criada = obter_ou_criar_conversa(self.empresa, self.contato)

        self.assertFalse(criada)
        self.assertEqual(conversa.pk, antiga.pk)
