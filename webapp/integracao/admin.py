from django.contrib import admin

from .models import EventoAtendimento, WahaSessao, WebhookRecebido


@admin.register(WahaSessao)
class WahaSessaoAdmin(admin.ModelAdmin):
    list_display = ('nome_sessao', 'empresa', 'ativa', 'criada_em')
    list_filter = ('ativa', 'empresa')
    search_fields = ('nome_sessao', 'empresa__nome')
    readonly_fields = ('webhook_secret', 'criada_em', 'atualizada_em')


@admin.register(WebhookRecebido)
class WebhookRecebidoAdmin(admin.ModelAdmin):
    list_display = ('origem', 'id_externo', 'empresa', 'processado_em')
    list_filter = ('origem', 'empresa')
    search_fields = ('id_externo',)
    readonly_fields = ('processado_em',)


@admin.register(EventoAtendimento)
class EventoAtendimentoAdmin(admin.ModelAdmin):
    list_display = ('tipo', 'empresa', 'ator', 'conversa', 'criado_em')
    list_filter = ('tipo', 'ator', 'empresa')
    search_fields = ('correlation_id',)
    readonly_fields = ('criado_em',)
