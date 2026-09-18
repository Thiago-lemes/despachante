"""Formulários da tela de configuração do chatbot.

Todos recebem a empresa ativa e a fixam na instância: a empresa nunca é campo
de formulário, senão bastaria forjar o POST para escrever no tenant vizinho.
"""
from django import forms
from django.db import models
from django.forms import inlineformset_factory

from .models import ConfiguracaoBot, DocumentoExigido, Servico


class ConfiguracaoBotForm(forms.ModelForm):
    # A tela mostra a saudação e a última opção **junto das opções do menu**, que
    # são os Servico. Separá-las do resto é o que deixa o menu inteiro visível de
    # uma vez, em vez de espalhado entre duas seções.
    CAMPOS_DO_MENU = ('saudacao', 'rotulo_atendente')

    # Os campos ficam fora do <form>, intercalados com a lista de serviços (que
    # tem forms próprios de excluir). O atributo form= é o que os liga de volta.
    ID_DO_FORM = 'form-chatbot'

    class Meta:
        model = ConfiguracaoBot
        fields = (
            'ativo', 'saudacao', 'rotulo_atendente', 'mensagem_nao_entendi',
            'mensagem_transferencia', 'mensagem_conclusao',
            'max_tentativas_invalidas', 'palavras_atendente',
        )
        labels = {
            'ativo': 'Atendimento automático ligado',
            'saudacao': 'Saudação (abre o menu)',
            'rotulo_atendente': 'Última opção, sempre presente',
            'mensagem_nao_entendi': 'Quando não entende a resposta',
            'mensagem_transferencia': 'Ao transferir para um atendente',
            'mensagem_conclusao': 'Ao receber todos os documentos',
            'max_tentativas_invalidas': 'Tentativas antes de transferir',
            'palavras_atendente': 'Palavras que chamam um atendente',
        }
        help_texts = {
            'rotulo_atendente': 'O bot acrescenta esta opção no fim do menu, sozinho. '
                                'As demais opções são os serviços cadastrados acima.',
        }
        widgets = {
            'saudacao': forms.Textarea(attrs={'rows': 2}),
            'mensagem_nao_entendi': forms.Textarea(attrs={'rows': 2}),
            'mensagem_transferencia': forms.Textarea(attrs={'rows': 2}),
            'mensagem_conclusao': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            campo.widget.attrs['form'] = self.ID_DO_FORM
            if nome != 'ativo':
                campo.widget.attrs.setdefault('class', 'field')

    @property
    def campos_do_menu(self):
        return [self[nome] for nome in self.CAMPOS_DO_MENU]

    @property
    def campos_de_comportamento(self):
        return [campo for campo in self if campo.name not in self.CAMPOS_DO_MENU]

    def clean_saudacao(self):
        saudacao = self.cleaned_data['saudacao'].strip()
        if not saudacao:
            raise forms.ValidationError('A saudação não pode ficar vazia.')
        return saudacao

    def clean_palavras_atendente(self):
        """Lista vazia deixaria o cliente sem escapatória fora do menu."""
        bruto = self.cleaned_data['palavras_atendente']
        palavras = [p.strip() for p in bruto.split(',') if p.strip()]
        if not palavras:
            raise forms.ValidationError(
                'Informe ao menos uma palavra — é como o cliente pede um humano '
                'sem depender do menu.'
            )
        return ', '.join(palavras)


class ServicoForm(forms.ModelForm):
    """Nem a posição no menu nem o pai são campos daqui.

    A posição se define arrastando na lista — digitar um número em dois
    formulários diferentes é como se criam empates e ordens que não batem com o
    que a tela mostra. O pai vem de onde o botão "Adicionar sub-opção" foi
    clicado, e não muda depois: mover um galho inteiro de lugar é outra
    operação, que a tela ainda não oferece.
    """

    class Meta:
        model = Servico
        fields = ('nome', 'mensagem_apos_escolha', 'descricao', 'ativo')
        labels = {
            'nome': 'Nome da opção, como o cliente lê no menu',
            'mensagem_apos_escolha': 'Mensagem ao escolher esta opção',
            'descricao': 'Descrição (uso interno)',
            'ativo': 'Aparece no menu do WhatsApp',
        }
        widgets = {
            'descricao': forms.Textarea(attrs={'rows': 2}),
            'mensagem_apos_escolha': forms.Textarea(attrs={'rows': 2}),
        }

    def __init__(self, *args, empresa=None, pai=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa or (
            self.instance.empresa if self.instance.empresa_id else None)
        self.pai = pai if self.instance.pk is None else self.instance.pai

        # O mesmo campo tem dois papéis conforme a opção ramifique ou não, e o
        # texto de ajuda é o que evita o dono da empresa escrever a coisa errada.
        tem_subopcoes = bool(self.instance.pk) and not self.instance.e_folha()
        self.fields['mensagem_apos_escolha'].help_text = (
            'Esta opção tem sub-opções, então esta é a pergunta que abre o submenu '
            f'(ex.: "Transferência de carro ou moto?"). Em branco, o bot usa '
            f'"{Servico.PERGUNTA_PADRAO}".'
            if tem_subopcoes else
            'Recado enviado antes de pedir os documentos (ex.: "Para agilizar, '
            'separe os documentos."). Opcional. Se um dia esta opção ganhar '
            'sub-opções, vira a pergunta que abre o submenu.'
        )

        for nome, campo in self.fields.items():
            if nome != 'ativo':
                campo.widget.attrs.setdefault('class', 'field')

    def clean_nome(self):
        """A unicidade é por irmãos — (empresa, pai, nome) —, e nem empresa nem
        pai são campos do formulário: sem esta checagem o erro só apareceria
        como IntegrityError no save."""
        nome = self.cleaned_data['nome'].strip()
        irmaos = Servico.objects.filter(
            empresa=self.empresa, pai=self.pai, nome__iexact=nome)
        if self.instance.pk:
            irmaos = irmaos.exclude(pk=self.instance.pk)
        if irmaos.exists():
            raise forms.ValidationError(
                'Já existe uma opção com este nome no mesmo nível do menu.')
        return nome

    def save(self, commit=True):
        servico = super().save(commit=False)
        servico.empresa = self.empresa
        if servico.pk is None:
            servico.pai = self.pai
            # Opção nova entra no fim do menu em que nasce — entre os irmãos, não
            # entre todos os serviços da empresa. Dali o dono arrasta.
            ultima = Servico.objects.filter(
                empresa=self.empresa, pai=self.pai).aggregate(
                    maior=models.Max('ordem'))['maior']
            servico.ordem = (ultima or 0) + 1
        if commit:
            servico.save()
        return servico


class DocumentoExigidoForm(forms.ModelForm):
    class Meta:
        model = DocumentoExigido
        fields = ('tipo', 'obrigatorio', 'instrucoes')
        labels = {
            'tipo': 'Documento',
            'obrigatorio': 'Obrigatório',
            'instrucoes': 'Instruções enviadas ao cliente',
        }
        widgets = {'instrucoes': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nome, campo in self.fields.items():
            if nome != 'obrigatorio':
                campo.widget.attrs.setdefault('class', 'field')


class DocumentoExigidoBaseFormSet(forms.BaseInlineFormSet):
    def save_new(self, form, commit=True):
        """O documento herda a empresa do serviço — não é escolha do usuário."""
        documento = super().save_new(form, commit=False)
        documento.empresa = self.instance.empresa
        if commit:
            documento.save()
        return documento


DocumentoExigidoFormSet = inlineformset_factory(
    Servico,
    DocumentoExigido,
    form=DocumentoExigidoForm,
    formset=DocumentoExigidoBaseFormSet,
    extra=1,
    can_delete=True,
)
