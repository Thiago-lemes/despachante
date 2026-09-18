from django.contrib import admin
from django.utils import timezone
from empresas.admin_utils import EmpresaAdminMixin
from .models import (
    ConfiguracaoBot, Contato, Servico, Conversa, Mensagem, DocumentoExigido,
    DocumentoRecebido, Tarefa,
)


@admin.register(ConfiguracaoBot)
class ConfiguracaoBotAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    """Espelho da tela de chatbot, para suporte."""
    list_display = ('empresa', 'ativo', 'max_tentativas_invalidas', 'atualizada_em')
    list_filter = ('ativo',)
    readonly_fields = ('atualizada_em',)


@admin.register(Contato)
class ContatoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'wa_id', 'nome', 'criado_em')
    search_fields = ('wa_id', 'nome')


class DocumentoExigidoInline(admin.TabularInline):
    """
    Os documentos são cadastrados junto do serviço: separados, é fácil criar o
    serviço e esquecer a lista, e aí o bot não tem o que pedir.
    """
    model = DocumentoExigido
    extra = 1
    fields = ('tipo', 'obrigatorio', 'instrucoes')


@admin.register(Servico)
class ServicoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'nome', 'ordem', 'ativo', 'qtd_documentos', 'criado_em')
    list_filter = ('ativo',)
    inlines = [DocumentoExigidoInline]

    @admin.display(description='Documentos exigidos')
    def qtd_documentos(self, servico):
        return servico.documentos_exigidos.count()

    def save_formset(self, request, form, formset, change):
        """O documento herda a empresa do serviço — não é escolha do usuário."""
        if formset.model is not DocumentoExigido:
            return super().save_formset(request, form, formset, change)
        documentos = formset.save(commit=False)
        for documento in documentos:
            documento.empresa = form.instance.empresa
            documento.save()
        for documento in formset.deleted_objects:
            documento.delete()
        formset.save_m2m()


@admin.register(Conversa)
class ConverSaAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'empresa', 'contato', 'servico', 'estado', 'modo', 'criada_em')
    list_filter = ('estado', 'modo')
    readonly_fields = ('criada_em', 'atualizada_em')


@admin.register(Mensagem)
class MensagemAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'conversa', 'direcao', 'conteudo', 'criada_em')
    list_filter = ('direcao',)
    readonly_fields = ('criada_em',)


@admin.register(DocumentoExigido)
class DocumentoExigidoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'tipo', 'servico', 'obrigatorio', 'criado_em')
    list_filter = ('servico', 'obrigatorio')


@admin.register(DocumentoRecebido)
class DocumentoRecebidoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'conversa', 'documento_exigido', 'status', 'analisado_em', 'criado_em')
    list_filter = ('status',)
    readonly_fields = ('criado_em', 'analisado_em', 'revisado_em')


@admin.register(Tarefa)
class TarefaAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'empresa', 'contato', 'servico', 'status', 'atendente', 'criada_em')
    list_filter = ('status', 'servico')
    readonly_fields = ('id', 'criada_em', 'assumida_em', 'concluida_em')

    actions = ['assumir_tarefa', 'concluir_tarefa']

    def assumir_tarefa(self, request, queryset):
        atualizadas = queryset.filter(status=Tarefa.Status.ABERTA).update(
            status=Tarefa.Status.EM_ATENDIMENTO,
            atendente=request.user,
            assumida_em=timezone.now()
        )
        self.message_user(request, f"{atualizadas} tarefas assumidas.")

    def concluir_tarefa(self, request, queryset):
        atualizadas = queryset.filter(status=Tarefa.Status.EM_ATENDIMENTO).update(
            status=Tarefa.Status.CONCLUIDA,
            concluida_em=timezone.now()
        )
        self.message_user(request, f"{atualizadas} tarefas concluídas.")
