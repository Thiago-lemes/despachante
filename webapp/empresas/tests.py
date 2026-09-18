from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase
from django.urls import reverse

from .models import Empresa, EmpresaUsuario


class EmpresaUsuarioTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username='ana', password='senha-segura')
        self.usuario.empresas_vinculadas.all().delete()
        self.empresa_a = Empresa.objects.create(nome='Despachante Alfa')
        self.empresa_b = Empresa.objects.create(nome='Despachante Beta')

    def test_usuario_pode_pertencer_a_empresas_distintas(self):
        EmpresaUsuario.objects.create(
            empresa=self.empresa_a,
            usuario=self.usuario,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR,
        )
        EmpresaUsuario.objects.create(
            empresa=self.empresa_b,
            usuario=self.usuario,
            papel=EmpresaUsuario.Papel.ATENDENTE,
        )

        self.assertEqual(self.usuario.empresas_vinculadas.count(), 2)

    def test_vinculo_duplicado_e_bloqueado(self):
        EmpresaUsuario.objects.create(empresa=self.empresa_a, usuario=self.usuario)

        with self.assertRaises(IntegrityError):
            EmpresaUsuario.objects.create(empresa=self.empresa_a, usuario=self.usuario)

    def test_apenas_administrador_ativo_pode_administrar(self):
        vinculo = EmpresaUsuario.objects.create(
            empresa=self.empresa_a,
            usuario=self.usuario,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR,
        )
        self.assertTrue(vinculo.pode_administrar())

        vinculo.ativo = False
        self.assertFalse(vinculo.pode_administrar())


class AprovacaoDeFuncionarioTests(TestCase):
    """Fluxo da aba 'Sou funcionário': pedido pendente até o admin liberar."""

    def setUp(self):
        User = get_user_model()
        self.empresa = Empresa.objects.create(
            nome='Despachante Alfa', cnpj='11222333000181')

        self.admin = User.objects.create_user(username='ana', password='senha-segura')
        self.admin.empresas_vinculadas.all().delete()
        EmpresaUsuario.objects.create(
            empresa=self.empresa,
            usuario=self.admin,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR,
            ativo=True,
        )

        self.funcionario = User.objects.create_user(username='bruno', password='senha-segura')
        self.funcionario.empresas_vinculadas.all().delete()
        self.pendente = EmpresaUsuario.objects.create(
            empresa=self.empresa,
            usuario=self.funcionario,
            papel=EmpresaUsuario.Papel.ATENDENTE,
            ativo=False,
        )

    def test_funcionario_pendente_e_desviado_para_a_pagina_de_espera(self):
        self.client.force_login(self.funcionario)

        resposta = self.client.get(reverse('busca'))

        self.assertRedirects(resposta, reverse('acesso_pendente'))

    def test_administrador_aprova_e_define_o_papel(self):
        self.client.force_login(self.admin)

        resposta = self.client.post(
            reverse('aprovar_vinculo', args=[self.pendente.pk]),
            {'papel': EmpresaUsuario.Papel.OPERADOR_DOCUMENTOS},
        )

        self.assertRedirects(resposta, reverse('equipe'))
        self.pendente.refresh_from_db()
        self.assertTrue(self.pendente.ativo)
        self.assertEqual(self.pendente.papel, EmpresaUsuario.Papel.OPERADOR_DOCUMENTOS)

    def test_aprovado_passa_a_acessar_o_sistema(self):
        self.pendente.ativo = True
        self.pendente.save(update_fields=['ativo'])
        self.client.force_login(self.funcionario)

        self.assertEqual(self.client.get(reverse('busca')).status_code, 200)

    def test_recusa_remove_o_vinculo_e_preserva_a_conta(self):
        self.client.force_login(self.admin)

        self.client.post(reverse('recusar_vinculo', args=[self.pendente.pk]))

        self.assertFalse(EmpresaUsuario.objects.filter(pk=self.pendente.pk).exists())
        self.assertTrue(get_user_model().objects.filter(username='bruno').exists())

    def test_funcionario_comum_nao_aprova_ninguem(self):
        self.pendente.ativo = True
        self.pendente.save(update_fields=['ativo'])
        outro = get_user_model().objects.create_user(username='carla', password='senha-segura')
        outro.empresas_vinculadas.all().delete()
        pedido = EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=outro, ativo=False)
        self.client.force_login(self.funcionario)

        resposta = self.client.post(reverse('aprovar_vinculo', args=[pedido.pk]))

        self.assertEqual(resposta.status_code, 403)
        pedido.refresh_from_db()
        self.assertFalse(pedido.ativo)

    def test_administrador_nao_aprova_pedido_de_outra_empresa(self):
        outra = Empresa.objects.create(nome='Despachante Beta', cnpj='22333444000199')
        forasteiro = get_user_model().objects.create_user(
            username='carla', password='senha-segura')
        forasteiro.empresas_vinculadas.all().delete()
        pedido = EmpresaUsuario.objects.create(
            empresa=outra, usuario=forasteiro, ativo=False)
        self.client.force_login(self.admin)

        resposta = self.client.post(reverse('aprovar_vinculo', args=[pedido.pk]))

        self.assertEqual(resposta.status_code, 404)
        pedido.refresh_from_db()
        self.assertFalse(pedido.ativo)

    def test_equipe_lista_pendentes_e_membros(self):
        self.client.force_login(self.admin)

        resposta = self.client.get(reverse('equipe'))

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual([v.pk for v in resposta.context['pendentes']], [self.pendente.pk])
        self.assertEqual(
            [v.usuario.username for v in resposta.context['membros']], ['ana'])


class BarraLateralWhatsAppTests(TestCase):
    """O item do WhatsApp na barra lateral.

    Ele nasce escondido e o JavaScript decide qual dos três estados mostrar
    conforme o status da sessão. O que se garante aqui é que os três cheguem ao
    HTML e que o item saiba de qual empresa está falando — sem isso o
    JavaScript desiste na primeira linha e a barra fica sem nada, sem dizer por quê.
    """

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username='dono', password='senha-segura')
        self.usuario.empresas_vinculadas.all().delete()
        self.empresa = Empresa.objects.create(nome='Despachante do Dono')
        EmpresaUsuario.objects.create(
            empresa=self.empresa, usuario=self.usuario,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR, ativo=True)
        self.client.force_login(self.usuario)

    def test_os_tres_estados_do_item_chegam_ao_html(self):
        html = self.client.get(reverse('equipe')).content.decode()

        self.assertIn('id="btn-vincular-whatsapp"', html)
        self.assertIn('id="indicador-whatsapp-conectado"', html)
        self.assertIn('id="btn-whatsapp-preparando"', html)

    def test_o_item_carrega_a_empresa_ativa(self):
        html = self.client.get(reverse('equipe')).content.decode()

        self.assertIn(f'data-empresa-id="{self.empresa.id}"', html)
