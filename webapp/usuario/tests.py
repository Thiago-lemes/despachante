from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from empresas.models import Empresa, EmpresaUsuario

SENHA = 'senha-bem-forte-123'


def dados_pessoais(username):
    return {
        'first_name': 'Ana',
        'last_name': 'Souza',
        'username': username,
        'email': f'{username}@exemplo.com',
        'password1': SENHA,
        'password2': SENHA,
    }


class CadastroEmpresaTests(TestCase):
    def test_cria_empresa_e_administrador_ativo(self):
        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'empresa',
            'nome_empresa': 'Despachante Alfa',
            'cnpj': '11.222.333/0001-81',
            **dados_pessoais('ana'),
        })

        self.assertRedirects(resposta, reverse('busca'))
        empresa = Empresa.objects.get(cnpj='11222333000181')
        self.assertEqual(empresa.nome, 'Despachante Alfa')

        vinculo = EmpresaUsuario.objects.get(empresa=empresa)
        self.assertEqual(vinculo.papel, EmpresaUsuario.Papel.ADMINISTRADOR)
        self.assertTrue(vinculo.ativo)
        self.assertEqual(self.client.session['empresa_atual_id'], empresa.pk)

    def test_recusa_cnpj_de_empresa_existente(self):
        Empresa.objects.create(nome='Despachante Alfa', cnpj='11222333000181')

        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'empresa',
            'nome_empresa': 'Outro Nome',
            'cnpj': '11222333000181',
            **dados_pessoais('ana'),
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['aba'], 'empresa')
        self.assertIn('cnpj', resposta.context['form_empresa'].errors)
        self.assertFalse(get_user_model().objects.filter(username='ana').exists())

    def test_recusa_cnpj_invalido(self):
        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'empresa',
            'nome_empresa': 'Despachante Alfa',
            'cnpj': '123',
            **dados_pessoais('ana'),
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertIn('cnpj', resposta.context['form_empresa'].errors)
        self.assertFalse(Empresa.objects.filter(nome='Despachante Alfa').exists())


class CadastroFuncionarioTests(TestCase):
    def setUp(self):
        self.empresa = Empresa.objects.create(
            nome='Despachante Alfa', cnpj='11222333000181')

    def test_vincula_pelo_cnpj_aguardando_aprovacao(self):
        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'funcionario',
            'cnpj': '11.222.333/0001-81',
            **dados_pessoais('bruno'),
        })

        self.assertRedirects(resposta, reverse('cadastro_enviado'))
        vinculo = EmpresaUsuario.objects.get(usuario__username='bruno')
        self.assertEqual(vinculo.empresa, self.empresa)
        self.assertEqual(vinculo.papel, EmpresaUsuario.Papel.ATENDENTE)
        self.assertFalse(vinculo.ativo)

    def test_nao_autentica_o_funcionario_pendente(self):
        self.client.post(reverse('cadastro'), {
            'aba': 'funcionario',
            'cnpj': '11222333000181',
            **dados_pessoais('bruno'),
        })

        self.assertNotIn('_auth_user_id', self.client.session)

    def test_recusa_cnpj_sem_empresa(self):
        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'funcionario',
            'cnpj': '99999999000191',
            **dados_pessoais('bruno'),
        })

        self.assertEqual(resposta.status_code, 200)
        self.assertEqual(resposta.context['aba'], 'funcionario')
        self.assertIn('cnpj', resposta.context['form_funcionario'].errors)
        self.assertFalse(get_user_model().objects.filter(username='bruno').exists())

    def test_recusa_empresa_inativa(self):
        self.empresa.ativa = False
        self.empresa.save(update_fields=['ativa'])

        resposta = self.client.post(reverse('cadastro'), {
            'aba': 'funcionario',
            'cnpj': '11222333000181',
            **dados_pessoais('bruno'),
        })

        self.assertIn('cnpj', resposta.context['form_funcionario'].errors)

    def test_pagina_de_confirmacao_exige_cadastro_recente(self):
        resposta = self.client.get(reverse('cadastro_enviado'))
        self.assertRedirects(resposta, reverse('cadastro'))
