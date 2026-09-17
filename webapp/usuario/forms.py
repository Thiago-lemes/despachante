from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from django.db import transaction
from empresas.models import Empresa, EmpresaUsuario

User = get_user_model()


def somente_digitos(valor):
    return ''.join(filter(str.isdigit, valor or ''))


class CadastroBaseForm(UserCreationForm):
    """Dados pessoais comuns às duas abas do cadastro."""

    first_name = forms.CharField(
        max_length=150,
        required=True,
        label='Nome',
        widget=forms.TextInput(attrs={'class': 'field'})
    )
    last_name = forms.CharField(
        max_length=150,
        required=False,
        label='Sobrenome',
        widget=forms.TextInput(attrs={'class': 'field'})
    )
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={'class': 'field'})
    )
    cnpj = forms.CharField(
        max_length=18,
        label='CNPJ da empresa',
        help_text='Somente números ou com pontuação.',
        widget=forms.TextInput(attrs={
            'class': 'field',
            'placeholder': '00.000.000/0000-00',
            'inputmode': 'numeric',
            'data-mascara': 'cnpj',
        })
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aplica a classe CSS 'field' em todos os inputs do formulário
        for field in self.fields.values():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'field'

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Já existe uma conta com este e-mail.')
        return email

    def clean_cnpj(self):
        cnpj = somente_digitos(self.cleaned_data['cnpj'])
        if len(cnpj) != 14:
            raise forms.ValidationError('O CNPJ deve conter exatamente 14 dígitos.')
        return cnpj


class CadastroEmpresaForm(CadastroBaseForm):
    """Aba 1: cria a empresa e o usuário administrador dela."""

    nome_empresa = forms.CharField(
        max_length=150,
        required=True,
        label='Nome da empresa',
        widget=forms.TextInput(attrs={'class': 'field', 'placeholder': 'Despachante Silva'})
    )

    field_order = [
        'nome_empresa', 'cnpj', 'first_name', 'last_name',
        'username', 'email', 'password1', 'password2',
    ]

    def clean_nome_empresa(self):
        nome = self.cleaned_data['nome_empresa'].strip()
        if Empresa.objects.filter(nome__iexact=nome).exists():
            raise forms.ValidationError('Já existe uma empresa com este nome.')
        return nome

    def clean_cnpj(self):
        cnpj = super().clean_cnpj()
        if Empresa.objects.filter(cnpj=cnpj).exists():
            raise forms.ValidationError(
                'Já existe uma empresa cadastrada com este CNPJ. '
                'Use a aba "Sou funcionário" para solicitar acesso a ela.'
            )
        return cnpj

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=True)
        self.empresa = Empresa.objects.create(
            nome=self.cleaned_data['nome_empresa'],
            cnpj=self.cleaned_data['cnpj'],
        )
        EmpresaUsuario.objects.create(
            empresa=self.empresa,
            usuario=user,
            papel=EmpresaUsuario.Papel.ADMINISTRADOR,
            ativo=True,
        )
        return user


class CadastroFuncionarioForm(CadastroBaseForm):
    """Aba 2: cria o usuário e o vincula a uma empresa existente pelo CNPJ.

    O vínculo nasce inativo: o funcionário só enxerga os dados da empresa
    depois que um administrador dela aprova o pedido.
    """

    field_order = [
        'cnpj', 'first_name', 'last_name',
        'username', 'email', 'password1', 'password2',
    ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = None
        self.fields['cnpj'].help_text = 'CNPJ da empresa em que você trabalha.'

    def clean_cnpj(self):
        cnpj = super().clean_cnpj()
        empresa = Empresa.objects.filter(cnpj=cnpj, ativa=True).first()
        if empresa is None:
            raise forms.ValidationError(
                'Nenhuma empresa ativa foi encontrada com este CNPJ. '
                'Confira o número com o administrador da sua empresa.'
            )
        self.empresa = empresa
        return cnpj

    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=True)
        EmpresaUsuario.objects.create(
            empresa=self.empresa,
            usuario=user,
            papel=EmpresaUsuario.Papel.ATENDENTE,
            ativo=False,
        )
        return user
