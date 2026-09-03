from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.core.validators import RegexValidator
from empresas.models import Empresa, EmpresaUsuario

User = get_user_model()


class CadastroDespachanteForm(UserCreationForm):
    cnpj = forms.CharField(
        max_length=18,
        label='CNPJ da empresa',
        help_text='Informe o CNPJ da despachante. Se a empresa ja existir, voce sera vinculado como funcionario.'
    )
    email = forms.EmailField(required=True)
    first_name = forms.CharField(max_length=150, required=True, label='Nome')
    last_name = forms.CharField(max_length=150, required=False, label='Sobrenome')

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'email', 'username', 'password1', 'password2', 'cnpj']

    def clean_cnpj(self):
        cnpj = self.cleaned_data['cnpj']
        cnpj = ''.join(filter(str.isdigit, cnpj))
        if len(cnpj) != 14:
            raise forms.ValidationError('CNPJ deve ter 14 digitos.')
        return cnpj

    def save(self, commit=True):
        user = super().save(commit=True)
        cnpj = self.cleaned_data['cnpj']

        empresa, criada = Empresa.objects.get_or_create(
            cnpj=cnpj,
            defaults={'nome': f'Despachante {cnpj}'}
        )

        if criada:
            EmpresaUsuario.objects.create(
                empresa=empresa,
                usuario=user,
                papel=EmpresaUsuario.Papel.ADMINISTRADOR,
                ativo=True
            )
        else:
            EmpresaUsuario.objects.create(
                empresa=empresa,
                usuario=user,
                papel=EmpresaUsuario.Papel.ATENDENTE,
                ativo=False
            )

        return user