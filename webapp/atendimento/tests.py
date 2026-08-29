import json

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from empresas.models import EmpresaUsuario

from .models import Contato, Conversa, Servico, Tarefa


class IsolamentoEmpresaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario_a = User.objects.create_user('ana', password='senha-segura')
        self.usuario_b = User.objects.create_user('bia', password='senha-segura')
        self.empresa_a = EmpresaUsuario.objects.get(usuario=self.usuario_a).empresa
        self.empresa_b = EmpresaUsuario.objects.get(usuario=self.usuario_b).empresa
        self.tarefa_a = self.criar_tarefa(self.empresa_a, '11111111111')
        self.tarefa_b = self.criar_tarefa(self.empresa_b, '22222222222')
        self.client.force_login(self.usuario_a)

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
