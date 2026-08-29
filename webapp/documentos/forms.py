import re

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import UserCreationForm

RE_PLACA = re.compile(r'^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$')


def normaliza_placa(valor):
    return re.sub(r'[^A-Z0-9]', '', (valor or '').upper())


class BuscaPlacaForm(forms.Form):
    placa = forms.CharField(
        label='Placa', max_length=8,
        widget=forms.TextInput(attrs={
            'placeholder': 'ABC1D23',
            'autofocus': True,
            'autocomplete': 'off',
            'class': 'field plate-input',
            'aria-label': 'Placa do veículo',
        }),
    )

    def clean_placa(self):
        placa = normaliza_placa(self.cleaned_data['placa'])
        if not RE_PLACA.fullmatch(placa):
            raise forms.ValidationError(
                'Informe uma placa Mercosul (ABC1D23) ou antiga (ABC1234).')
        return placa


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    widget = MultipleFileInput

    def clean(self, data, initial=None):
        arquivos = data if isinstance(data, (list, tuple)) else [data]
        # ``super()`` sem argumentos perde o contexto de classe dentro de uma
        # comprehension no Python. Guarde o métod antes de iterar para que
        # uploads individuais e múltiplos passem pela validação padrão do
        # Django da mesma forma.
        limpar_arquivo = super().clean
        return [limpar_arquivo(arquivo, initial) for arquivo in arquivos]


class UploadForm(forms.Form):
    MODO_CHOICES = [
        ('avulso', 'Envio avulso'),
        ('lote', 'Envio em lote'),
    ]

    modo = forms.ChoiceField(choices=MODO_CHOICES, initial='avulso')
    arquivos = MultipleFileField(
        label='Arquivos PDF',
        widget=MultipleFileInput(attrs={
            'accept': 'application/pdf,.pdf',
            'class': 'sr-only',
            'data-file-input': '',
        }),
    )
    placa_esperada = forms.CharField(required=False, widget=forms.HiddenInput)

    def clean_arquivos(self):
        arquivos = self.cleaned_data['arquivos']
        if len(arquivos) > settings.UPLOAD_MAX_FILES:
            raise forms.ValidationError(
                f'Selecione no máximo {settings.UPLOAD_MAX_FILES} arquivos por envio.')
        if sum(arquivo.size for arquivo in arquivos) > settings.UPLOAD_MAX_TOTAL_SIZE:
            raise forms.ValidationError('O envio completo ultrapassa 200 MB.')
        for arquivo in arquivos:
            if not arquivo.name.lower().endswith('.pdf'):
                raise forms.ValidationError(f'{arquivo.name}: selecione somente arquivos PDF.')
            if arquivo.size <= 0:
                raise forms.ValidationError(f'{arquivo.name}: o arquivo está vazio.')
            if arquivo.size > settings.UPLOAD_MAX_FILE_SIZE:
                raise forms.ValidationError(f'{arquivo.name}: o arquivo ultrapassa 30 MB.')
            assinatura = arquivo.read(5)
            arquivo.seek(0)
            if assinatura != b'%PDF-':
                raise forms.ValidationError(f'{arquivo.name}: o conteúdo não é um PDF válido.')
        return arquivos

    def clean(self):
        dados = super().clean()
        arquivos = dados.get('arquivos') or []
        if dados.get('modo') == 'avulso' and len(arquivos) != 1:
            self.add_error('arquivos', 'O envio avulso aceita exatamente um PDF.')
        return dados


class CadastroForm(UserCreationForm):
    email = forms.EmailField(
        label='E-mail', required=True,
        widget=forms.EmailInput(attrs={'class': 'field', 'autocomplete': 'email'}))

    class Meta:
        model = get_user_model()
        fields = ['username', 'email']
        widgets = {
            'username': forms.TextInput(attrs={'class': 'field', 'autocomplete': 'username'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for campo in ('password1', 'password2'):
            self.fields[campo].widget.attrs.update({'class': 'field'})

    def clean_email(self):
        email = self.cleaned_data['email']
        if get_user_model().objects.filter(email__iexact=email).exists():
            raise forms.ValidationError('Já existe uma conta com este e-mail.')
        return email


class PerfilForm(forms.ModelForm):
    class Meta:
        model = get_user_model()
        fields = ['first_name', 'last_name', 'email']
        labels = {
            'first_name': 'Nome',
            'last_name': 'Sobrenome',
            'email': 'E-mail',
        }
        widgets = {
            'first_name': forms.TextInput(attrs={'class': 'field'}),
            'last_name': forms.TextInput(attrs={'class': 'field'}),
            'email': forms.EmailInput(attrs={'class': 'field'}),
        }
