from django.contrib.auth import get_user_model
from django.db import IntegrityError
from django.test import TestCase

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
