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
    ConfiguracaoBot, Contato, Conversa, DocumentoExigido, DocumentoRecebido,
    Mensagem, Servico, Tarefa,
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


@patch('atendimento.services.bot.enviar_texto',
       return_value={'success': True, 'data': {'id': 'out-1'}})
class ConfiguracaoBotAplicadaTests(TestCase):
    """O que a tela salva tem de chegar no que o cliente lê no WhatsApp."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Teste')
        WahaSessao.objects.create(empresa=self.empresa, nome_sessao='teste')
        self.contato = Contato.objects.create(
            empresa=self.empresa, wa_id='5541999990000', chat_id='5541999990000@c.us')
        self.conversa = Conversa.objects.create(
            empresa=self.empresa, contato=self.contato)
        self.config = ConfiguracaoBot.para(self.empresa)

    def receber(self, texto):
        mensagem = Mensagem.objects.create(
            empresa=self.empresa, conversa=self.conversa,
            direcao=Mensagem.Direcao.ENTRADA, conteudo=texto)
        self.conversa.refresh_from_db()
        bot.processar_mensagem(self.conversa, mensagem)
        self.conversa.refresh_from_db()

    @property
    def ultima_saida(self):
        return (self.conversa.mensagens.filter(direcao=Mensagem.Direcao.SAIDA)
                .order_by('criada_em').last().conteudo)

    def test_saudacao_e_rotulo_personalizados_aparecem_no_menu(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self.config.saudacao = 'Bom dia! Aqui é o robô da {empresa}.'
        self.config.rotulo_atendente = 'Chamar o despachante'
        self.config.save()

        self.receber('Oi')

        self.assertIn('Bom dia! Aqui é o robô da Despachante Teste.', self.ultima_saida)
        self.assertIn('2 - Chamar o despachante', self.ultima_saida)

    def test_ordem_define_a_numeracao_do_menu(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Zebra', ordem=1)
        Servico.objects.create(empresa=self.empresa, nome='Alfa', ordem=2)

        self.receber('Oi')

        self.assertIn('1 - Zebra', self.ultima_saida)
        self.assertIn('2 - Alfa', self.ultima_saida)

    def test_limite_de_tentativas_vem_da_configuracao(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self.config.max_tentativas_invalidas = 1
        self.config.save()

        self.receber('Oi')
        self.receber('não sei')

        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)

    def test_palavra_personalizada_transfere_para_humano(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self.config.palavras_atendente = 'despachante'
        self.config.save()

        self.receber('quero falar com o despachante')

        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)

    def test_palavra_padrao_nao_transfere_quando_foi_removida(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self.config.palavras_atendente = 'despachante'
        self.config.save()

        self.receber('atendente')

        self.assertEqual(self.conversa.modo, Conversa.Modo.BOT)

    def test_bot_desligado_entrega_direto_ao_atendente(self, _enviar):
        Servico.objects.create(empresa=self.empresa, nome='Licenciamento')
        self.config.ativo = False
        self.config.save()

        self.receber('Oi')

        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(Tarefa.objects.count(), 1)
        # Silêncio não serve: o cliente escreveu e recebe resposta.
        self.assertIn('atendente', self.ultima_saida)


class TelaChatbotTests(TestCase):
    """Acesso, isolamento e edição na tela de configuração do chatbot."""

    def setUp(self):
        User = get_user_model()
        self.empresa = Empresa.objects.create(nome='Despachante do Dono')
        self.outra_empresa = Empresa.objects.create(nome='Concorrente')

        self.dono = User.objects.create_user('dono', password='senha-segura')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=self.dono,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR, ativo=True)

        self.funcionario = User.objects.create_user('func', password='senha-segura')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=self.funcionario,
            papel=EmpresaUsuario.Papel.ATENDENTE, ativo=True)

        self.servico = Servico.objects.create(
            empresa=self.empresa, nome='Licenciamento')
        self.servico_alheio = Servico.objects.create(
            empresa=self.outra_empresa, nome='Transferência')

    def logar_dono(self):
        self.client.force_login(self.dono)

    def test_funcionario_nao_acessa_a_tela(self):
        self.client.force_login(self.funcionario)
        self.assertEqual(self.client.get(reverse('chatbot_config')).status_code, 403)

    def test_funcionario_nao_altera_a_configuracao(self):
        self.client.force_login(self.funcionario)
        resposta = self.client.post(reverse('chatbot_config'), data={
            'saudacao': 'invadido', 'rotulo_atendente': 'x',
            'mensagem_nao_entendi': 'x', 'mensagem_transferencia': 'x',
            'mensagem_conclusao': 'x', 'max_tentativas_invalidas': 3,
            'palavras_atendente': 'atendente',
        })
        self.assertEqual(resposta.status_code, 403)
        self.assertEqual(
            ConfiguracaoBot.para(self.empresa).saudacao,
            ConfiguracaoBot.SAUDACAO_PADRAO)

    def test_dono_acessa_e_ve_apenas_os_servicos_da_propria_empresa(self):
        self.logar_dono()
        resposta = self.client.get(reverse('chatbot_config'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(
            [item['servico'] for item in resposta.context['menu']], [self.servico])

    def test_campos_da_configuracao_ficam_ligados_ao_form(self):
        """Os campos moram fora do <form>, intercalados com a lista de opções.

        Sem o atributo form= eles simplesmente não seriam enviados, e o salvar
        passaria a perder dado em silêncio.
        """
        self.logar_dono()
        html = self.client.get(reverse('chatbot_config')).content.decode()

        for campo in ('id_saudacao', 'id_rotulo_atendente', 'id_ativo',
                      'id_max_tentativas_invalidas', 'id_palavras_atendente'):
            self.assertRegex(
                html, rf'id="{campo}"[^>]*form="form-chatbot"'
                      rf'|form="form-chatbot"[^>]*id="{campo}"',
                f'{campo} não está ligado ao formulário.')

    def test_salvar_configuracao(self):
        self.logar_dono()
        resposta = self.client.post(reverse('chatbot_config'), data={
            'ativo': 'on',
            'saudacao': 'Olá, aqui é a {empresa}.',
            'rotulo_atendente': 'Falar com alguém',
            'mensagem_nao_entendi': 'Como assim?',
            'mensagem_transferencia': 'Já te chamo alguém.',
            'mensagem_conclusao': 'Recebido!',
            'max_tentativas_invalidas': 2,
            'palavras_atendente': ' atendente , despachante ',
        })

        self.assertRedirects(resposta, reverse('chatbot_config'))
        config = ConfiguracaoBot.para(self.empresa)
        self.assertEqual(config.max_tentativas_invalidas, 2)
        self.assertEqual(config.palavras_atendente, 'atendente, despachante')
        self.assertEqual(config.saudacao_formatada(), 'Olá, aqui é a Despachante do Dono.')

    def test_sem_palavras_de_atendente_a_configuracao_e_recusada(self):
        self.logar_dono()
        resposta = self.client.post(reverse('chatbot_config'), data={
            'ativo': 'on',
            'saudacao': 'Olá',
            'rotulo_atendente': 'Atendente',
            'mensagem_nao_entendi': 'Como assim?',
            'mensagem_transferencia': 'Já te chamo.',
            'mensagem_conclusao': 'Recebido!',
            'max_tentativas_invalidas': 2,
            'palavras_atendente': '  ,  ',
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('palavras_atendente', resposta.context['form'].errors)

    def dados_do_servico(self, **extra):
        dados = {
            'nome': 'Segunda via de CRLV',
            'descricao': '',
            'ativo': 'on',
            'documentos_exigidos-TOTAL_FORMS': '1',
            'documentos_exigidos-INITIAL_FORMS': '0',
            'documentos_exigidos-MIN_NUM_FORMS': '0',
            'documentos_exigidos-MAX_NUM_FORMS': '1000',
            'documentos_exigidos-0-id': '',
            'documentos_exigidos-0-tipo': 'CRLV',
            'documentos_exigidos-0-obrigatorio': 'on',
            'documentos_exigidos-0-instrucoes': 'Foto do documento do veículo.',
        }
        dados.update(extra)
        return dados

    def test_formulario_de_servico_novo_abre_com_uma_linha_de_documento(self):
        self.logar_dono()
        resposta = self.client.get(reverse('chatbot_servico_novo'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(len(resposta.context['formset'].forms), 1)

    def test_tela_da_opcao_traz_os_moldes_reais_do_bot(self):
        """A prévia da conversa é montada no navegador com estes moldes.

        Se eles deixarem de vir do servidor, a prévia passa a mostrar um texto
        que o cliente não recebe.
        """
        self.logar_dono()
        resposta = self.client.get(reverse('chatbot_servico_novo'))

        textos = resposta.context['textos_bot']
        self.assertEqual(textos['primeiro_documento'], bot.TEXTO_PRIMEIRO_DOCUMENTO)
        self.assertEqual(textos['proximo_documento'], bot.TEXTO_PROXIMO_DOCUMENTO)
        self.assertEqual(
            textos['conclusao'], ConfiguracaoBot.para(self.empresa).mensagem_conclusao)
        self.assertContains(resposta, 'textos-do-bot')

    def test_criar_servico_com_documento(self):
        self.logar_dono()
        resposta = self.client.post(
            reverse('chatbot_servico_novo'), data=self.dados_do_servico())

        self.assertRedirects(resposta, reverse('chatbot_config'))
        criado = Servico.objects.get(nome='Segunda via de CRLV')
        self.assertEqual(criado.empresa, self.empresa)
        documento = criado.documentos_exigidos.get()
        self.assertEqual(documento.tipo, 'CRLV')
        # O documento herda a empresa do serviço, não do POST.
        self.assertEqual(documento.empresa, self.empresa)

    def test_servico_novo_entra_no_fim_do_menu(self):
        self.logar_dono()
        self.servico.ordem = 7
        self.servico.save()

        self.client.post(reverse('chatbot_servico_novo'), data=self.dados_do_servico())

        self.assertEqual(Servico.objects.get(nome='Segunda via de CRLV').ordem, 8)

    def reordenar(self, ids):
        return self.client.post(
            reverse('chatbot_reordenar_servicos'),
            data=json.dumps({'ordem': ids}),
            content_type='application/json',
        )

    def test_reordenar_grava_as_posicoes(self):
        self.logar_dono()
        segundo = Servico.objects.create(empresa=self.empresa, nome='Transferência')

        resposta = self.reordenar([segundo.id, self.servico.id])

        self.assertEqual(resposta.status_code, 200)
        segundo.refresh_from_db()
        self.servico.refresh_from_db()
        self.assertEqual(segundo.ordem, 1)
        self.assertEqual(self.servico.ordem, 2)

    def test_reordenar_recusa_lista_parcial(self):
        self.logar_dono()
        Servico.objects.create(empresa=self.empresa, nome='Transferência')

        resposta = self.reordenar([self.servico.id])

        self.assertEqual(resposta.status_code, 400)
        self.servico.refresh_from_db()
        self.assertEqual(self.servico.ordem, 0)

    def test_reordenar_ignora_servico_de_outra_empresa(self):
        self.logar_dono()

        resposta = self.reordenar([self.servico_alheio.id, self.servico.id])

        self.assertEqual(resposta.status_code, 400)
        self.servico_alheio.refresh_from_db()
        self.assertEqual(self.servico_alheio.ordem, 0)

    def test_funcionario_nao_reordena(self):
        self.client.force_login(self.funcionario)
        self.assertEqual(self.reordenar([self.servico.id]).status_code, 403)

    def test_nome_repetido_na_mesma_empresa_e_recusado(self):
        self.logar_dono()
        resposta = self.client.post(
            reverse('chatbot_servico_novo'),
            data=self.dados_do_servico(nome='licenciamento'))

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('nome', resposta.context['form'].errors)
        self.assertEqual(Servico.objects.filter(empresa=self.empresa).count(), 1)

    def test_nao_edita_servico_de_outra_empresa(self):
        self.logar_dono()
        resposta = self.client.get(
            reverse('chatbot_servico_editar', args=[self.servico_alheio.id]))
        self.assertEqual(resposta.status_code, 404)

    def test_excluir_servico_sem_atendimento(self):
        self.logar_dono()
        DocumentoExigido.objects.create(
            empresa=self.empresa, servico=self.servico,
            tipo='CNH', instrucoes='Foto da CNH.')

        resposta = self.client.post(
            reverse('chatbot_servico_excluir', args=[self.servico.id]))

        self.assertRedirects(resposta, reverse('chatbot_config'))
        self.assertFalse(Servico.objects.filter(pk=self.servico.pk).exists())
        self.assertEqual(DocumentoExigido.objects.count(), 0)

    def test_servico_com_atendimento_e_desativado_em_vez_de_excluido(self):
        self.logar_dono()
        contato = Contato.objects.create(empresa=self.empresa, wa_id='5541988887777')
        Conversa.objects.create(
            empresa=self.empresa, contato=contato, servico=self.servico)

        self.client.post(reverse('chatbot_servico_excluir', args=[self.servico.id]))

        self.servico.refresh_from_db()
        self.assertFalse(self.servico.ativo)


@patch('atendimento.services.bot.enviar_texto',
       return_value={'success': True, 'data': {'id': 'out-1'}})
class ReligarConversaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.dono = User.objects.create_user('dona', password='senha-segura')
        self.empresa = Empresa.objects.create(nome='Despachante da Dona')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=self.dono,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR, ativo=True)
        WahaSessao.objects.create(empresa=self.empresa, nome_sessao='teste')
        self.servico = Servico.objects.create(
            empresa=self.empresa, nome='Licenciamento')
        contato = Contato.objects.create(
            empresa=self.empresa, wa_id='5541977776666', chat_id='5541977776666@c.us')
        self.conversa = Conversa.objects.create(
            empresa=self.empresa, contato=contato,
            modo=Conversa.Modo.HUMANO, estado=Conversa.Estado.AGUARDANDO_HUMANO,
            tentativas_invalidas=3)
        self.client.force_login(self.dono)

    def religar(self):
        return self.client.post(
            reverse('chatbot_religar_conversa', args=[self.conversa.id]))

    def test_devolver_ao_bot_reabre_a_triagem_e_reenvia_o_menu(self, _enviar):
        self.assertRedirects(self.religar(), reverse('chatbot_config'))

        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.modo, Conversa.Modo.BOT)
        self.assertEqual(self.conversa.estado, Conversa.Estado.TRIAGEM)
        self.assertEqual(self.conversa.tentativas_invalidas, 0)
        ultima = self.conversa.mensagens.filter(
            direcao=Mensagem.Direcao.SAIDA).order_by('criada_em').last()
        self.assertIn('1 - Licenciamento', ultima.conteudo)

    def test_sem_servico_ativo_a_conversa_continua_com_o_humano(self, _enviar):
        self.servico.ativo = False
        self.servico.save()

        self.religar()

        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)

    def test_funcionario_nao_religa_conversa(self, _enviar):
        User = get_user_model()
        funcionario = User.objects.create_user('peao', password='senha-segura')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=funcionario,
            papel=EmpresaUsuario.Papel.ATENDENTE, ativo=True)
        self.client.force_login(funcionario)

        self.assertEqual(self.religar().status_code, 403)
        self.conversa.refresh_from_db()
        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)


@patch('atendimento.services.bot.enviar_texto',
       return_value={'success': True, 'data': {'id': 'out-1'}})
class SubOpcoesDoMenuTests(TestCase):
    """Ramificação da conversa: 'Transferência' → 'Carro' ou 'Moto'."""

    def setUp(self):
        self.empresa = Empresa.objects.create(nome='Despachante Teste')
        WahaSessao.objects.create(empresa=self.empresa, nome_sessao='teste')
        self.licenciamento = Servico.objects.create(
            empresa=self.empresa, nome='Licenciamento', ordem=1)
        self.transferencia = Servico.objects.create(
            empresa=self.empresa, nome='Transferência', ordem=2,
            mensagem_apos_escolha='Transferência de carro ou moto?')
        self.carro = Servico.objects.create(
            empresa=self.empresa, pai=self.transferencia, nome='Carro', ordem=1)
        self.moto = Servico.objects.create(
            empresa=self.empresa, pai=self.transferencia, nome='Moto', ordem=2,
            mensagem_apos_escolha='Para agilizar, separe os documentos.')
        DocumentoExigido.objects.create(
            empresa=self.empresa, servico=self.moto,
            tipo='CRLV da moto', instrucoes='Foto do documento.')

        self.contato = Contato.objects.create(
            empresa=self.empresa, wa_id='5541966665555', chat_id='5541966665555@c.us')
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
            self.conversa.mensagens.filter(direcao=Mensagem.Direcao.SAIDA)
            .order_by('criada_em').values_list('conteudo', flat=True))

    def test_menu_principal_nao_mostra_sub_opcoes(self, _enviar):
        self.receber('Oi')

        menu = self.saidas[0]
        self.assertIn('1 - Licenciamento', menu)
        self.assertIn('2 - Transferência', menu)
        self.assertIn('3 - Falar com um atendente', menu)
        self.assertNotIn('Moto', menu)

    def test_escolher_opcao_com_ramificacao_abre_o_submenu_sem_criar_card(self, _enviar):
        self.receber('Oi')
        self.receber('2')

        submenu = self.saidas[-1]
        self.assertIn('Transferência de carro ou moto?', submenu)
        self.assertIn('1 - Carro', submenu)
        self.assertIn('2 - Moto', submenu)
        self.assertIn('3 - Falar com um atendente', submenu)
        # O pedido ainda não está caracterizado: nada de card.
        self.assertFalse(Tarefa.objects.exists())
        self.assertEqual(self.conversa.estado, Conversa.Estado.TRIAGEM)
        self.assertEqual(self.conversa.servico, self.transferencia)

    def test_escolher_a_sub_opcao_cria_o_card_com_o_caminho(self, _enviar):
        self.receber('Oi')
        self.receber('2')
        self.receber('2')

        tarefa = Tarefa.objects.get()
        self.assertEqual(tarefa.servico, self.moto)
        self.assertIn('Transferência › Moto', tarefa.resumo_triagem)
        self.assertEqual(self.conversa.estado, Conversa.Estado.COLETANDO_DOCUMENTOS)

    def test_recado_da_opcao_abre_a_mensagem_de_documentos(self, _enviar):
        self.receber('Oi')
        self.receber('2')
        self.receber('2')

        resposta = self.saidas[-1]
        self.assertTrue(resposta.startswith('Para agilizar, separe os documentos.'))
        self.assertIn('CRLV da moto', resposta)

    def test_resposta_invalida_no_submenu_repete_o_submenu(self, _enviar):
        self.receber('Oi')
        self.receber('2')
        self.receber('caminhão')

        resposta = self.saidas[-1]
        self.assertIn('Não entendi', resposta)
        self.assertIn('Transferência de carro ou moto?', resposta)
        self.assertIn('1 - Carro', resposta)
        # A saudação abre a conversa, não se repete a cada erro.
        self.assertNotIn('assistente virtual', resposta)

    def test_atendente_no_submenu_transfere(self, _enviar):
        self.receber('Oi')
        self.receber('2')
        self.receber('3')

        self.assertEqual(self.conversa.modo, Conversa.Modo.HUMANO)
        self.assertEqual(Tarefa.objects.count(), 1)

    def test_sub_opcao_inativa_some_do_submenu(self, _enviar):
        self.carro.ativo = False
        self.carro.save()

        self.receber('Oi')
        self.receber('2')

        submenu = self.saidas[-1]
        self.assertIn('1 - Moto', submenu)
        self.assertNotIn('Carro', submenu)

    def test_opcao_cujas_sub_opcoes_estao_todas_inativas_vira_folha(self, _enviar):
        """Sem filho ativo não há para onde ramificar: o pedido se conclui ali."""
        self.carro.ativo = False
        self.carro.save()
        self.moto.ativo = False
        self.moto.save()

        self.receber('Oi')
        self.receber('2')

        tarefa = Tarefa.objects.get()
        self.assertEqual(tarefa.servico, self.transferencia)

    def test_tres_niveis_de_ramificacao(self, _enviar):
        """Sem limite de profundidade: a folha é que conclui, esteja onde estiver."""
        eletrica = Servico.objects.create(
            empresa=self.empresa, pai=self.moto, nome='Elétrica', ordem=1)

        self.receber('Oi')
        self.receber('2')   # Transferência
        self.receber('2')   # Moto  -> agora tem filha, vira submenu
        self.assertFalse(Tarefa.objects.exists())
        self.assertIn('1 - Elétrica', self.saidas[-1])

        self.receber('1')   # Elétrica
        tarefa = Tarefa.objects.get()
        self.assertEqual(tarefa.servico, eletrica)
        self.assertIn('Transferência › Moto › Elétrica', tarefa.resumo_triagem)

    def test_devolver_ao_bot_volta_para_o_menu_principal(self, _enviar):
        self.receber('Oi')
        self.receber('2')
        self.conversa.modo = Conversa.Modo.HUMANO
        self.conversa.save()

        bot.religar(self.conversa)
        self.conversa.refresh_from_db()

        self.assertIsNone(self.conversa.servico)
        self.assertIn('2 - Transferência', self.saidas[-1])

    def test_caminho_ignora_ciclo_de_pai(self, _enviar):
        """Um pai apontando para o próprio descendente não pode travar o bot."""
        Servico.objects.filter(pk=self.transferencia.pk).update(pai=self.moto)
        self.transferencia.refresh_from_db()

        self.assertIn('Moto', self.moto.caminho())


class TelaSubOpcoesTests(TestCase):
    """Cadastro, ordem e exclusão de sub-opções na tela do chatbot."""

    def setUp(self):
        User = get_user_model()
        self.empresa = Empresa.objects.create(nome='Despachante do Dono')
        self.dono = User.objects.create_user('dono', password='senha-segura')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=self.dono,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR, ativo=True)
        self.outra_empresa = Empresa.objects.create(nome='Concorrente')
        self.servico_alheio = Servico.objects.create(
            empresa=self.outra_empresa, nome='Alheio')

        self.transferencia = Servico.objects.create(
            empresa=self.empresa, nome='Transferência', ordem=1)
        self.carro = Servico.objects.create(
            empresa=self.empresa, pai=self.transferencia, nome='Carro', ordem=1)
        self.moto = Servico.objects.create(
            empresa=self.empresa, pai=self.transferencia, nome='Moto', ordem=2)
        self.client.force_login(self.dono)

    def dados(self, **extra):
        dados = {
            'nome': 'Caminhão',
            'mensagem_apos_escolha': '',
            'descricao': '',
            'ativo': 'on',
            'documentos_exigidos-TOTAL_FORMS': '0',
            'documentos_exigidos-INITIAL_FORMS': '0',
            'documentos_exigidos-MIN_NUM_FORMS': '0',
            'documentos_exigidos-MAX_NUM_FORMS': '1000',
        }
        dados.update(extra)
        return dados

    def test_criar_sub_opcao_pelo_pai(self):
        resposta = self.client.post(
            reverse('chatbot_servico_novo') + f'?pai={self.transferencia.id}',
            data=self.dados())

        self.assertRedirects(resposta, reverse('chatbot_config'))
        criada = Servico.objects.get(nome='Caminhão')
        self.assertEqual(criada.pai, self.transferencia)
        # Entra no fim do submenu em que nasceu, não no fim de tudo.
        self.assertEqual(criada.ordem, 3)

    def test_nao_pendura_sub_opcao_na_arvore_de_outra_empresa(self):
        resposta = self.client.get(
            reverse('chatbot_servico_novo') + f'?pai={self.servico_alheio.id}')
        self.assertEqual(resposta.status_code, 404)

    def test_nome_repetido_entre_irmaos_e_recusado(self):
        resposta = self.client.post(
            reverse('chatbot_servico_novo') + f'?pai={self.transferencia.id}',
            data=self.dados(nome='moto'))

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('nome', resposta.context['form'].errors)

    def test_nome_repetido_em_ramos_diferentes_e_permitido(self):
        """'Moto' pode existir sob 'Transferência' e sob 'Licenciamento'."""
        licenciamento = Servico.objects.create(
            empresa=self.empresa, nome='Licenciamento', ordem=2)

        resposta = self.client.post(
            reverse('chatbot_servico_novo') + f'?pai={licenciamento.id}',
            data=self.dados(nome='Moto'))

        self.assertRedirects(resposta, reverse('chatbot_config'))
        self.assertEqual(
            Servico.objects.filter(empresa=self.empresa, nome='Moto').count(), 2)

    def test_arvore_chega_aninhada_no_template(self):
        resposta = self.client.get(reverse('chatbot_config'))

        menu = resposta.context['menu']
        self.assertEqual([item['servico'] for item in menu], [self.transferencia])
        self.assertEqual(
            [item['servico'] for item in menu[0]['subopcoes']], [self.carro, self.moto])

    def reordenar(self, ids, pai=None):
        return self.client.post(
            reverse('chatbot_reordenar_servicos'),
            data=json.dumps({'pai': pai, 'ordem': ids}),
            content_type='application/json',
        )

    def test_reordenar_um_submenu(self):
        resposta = self.reordenar([self.moto.id, self.carro.id], pai=self.transferencia.id)

        self.assertEqual(resposta.status_code, 200)
        self.moto.refresh_from_db()
        self.carro.refresh_from_db()
        self.assertEqual(self.moto.ordem, 1)
        self.assertEqual(self.carro.ordem, 2)

    def test_reordenar_mistura_de_niveis_e_recusada(self):
        """A lista de um nível não pode conter opção de outro."""
        resposta = self.reordenar([self.carro.id, self.transferencia.id], pai=None)

        self.assertEqual(resposta.status_code, 400)
        self.transferencia.refresh_from_db()
        self.assertEqual(self.transferencia.ordem, 1)

    def test_nao_exclui_opcao_com_sub_opcoes(self):
        resposta = self.client.post(
            reverse('chatbot_servico_excluir', args=[self.transferencia.id]))

        self.assertRedirects(resposta, reverse('chatbot_config'))
        self.assertTrue(Servico.objects.filter(pk=self.transferencia.pk).exists())
        self.assertTrue(Servico.objects.filter(pk=self.carro.pk).exists())

    def test_previa_da_tela_mostra_o_submenu_quando_a_opcao_ramifica(self):
        resposta = self.client.get(
            reverse('chatbot_servico_editar', args=[self.transferencia.id]))

        self.assertEqual(
            resposta.context['previa_submenu']['opcoes'], ['Carro', 'Moto'])

    def test_previa_da_folha_nao_traz_submenu(self):
        resposta = self.client.get(
            reverse('chatbot_servico_editar', args=[self.moto.id]))

        self.assertEqual(resposta.context['previa_submenu']['opcoes'], [])
        self.assertEqual(resposta.context['pai'], self.transferencia)
