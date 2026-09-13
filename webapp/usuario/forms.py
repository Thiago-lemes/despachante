from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm
from empresas.models import Empresa, EmpresaUsuario

User = get_user_model()


class CadastroDespachanteForm(UserCreationForm):
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
        label='CNPJ da Empresa',
        help_text='Somente números ou com pontuação.',
        widget=forms.TextInput(attrs={'class': 'field', 'placeholder': '00.000.000/0000-00'})
    )

    class Meta:
        model = User
        fields = ['first_name', 'last_name', 'username', 'email', 'cnpj']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Aplica a classe CSS 'field' em todos os inputs do formulário
        for field in self.fields.values():
            if 'class' not in field.widget.attrs:
                field.widget.attrs['class'] = 'field'

    def clean_cnpj(self):
        cnpj = self.cleaned_data['cnpj']
        cnpj_limpo = ''.join(filter(str.isdigit, cnpj))
        if len(cnpj_limpo) != 14:
            raise forms.ValidationError('O CNPJ deve conter exatamente 14 dígitos.')
        return cnpj_limpo

    def save(self, commit=True):
        user = super().save(commit=commit)
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