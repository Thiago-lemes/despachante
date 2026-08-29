from django.contrib import admin
from django.utils import timezone
from empresas.admin_utils import EmpresaAdminMixin
from .models import Contato, Servico, Conversa, Mensagem, DocumentoExigido, DocumentoRecebido, Tarefa


@admin.register(Contato)
class ContatoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'wa_id', 'nome', 'criado_em')
    search_fields = ('wa_id', 'nome')


@admin.register(Servico)
class ServicoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('empresa', 'nome', 'ativo', 'criado_em')
    list_filter = ('ativo',)


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
