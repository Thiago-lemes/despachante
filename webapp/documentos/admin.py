from django.contrib import admin

from empresas.admin_utils import EmpresaAdminMixin
from .models import Documento, ItemLote, Lote


class ItemLoteInline(admin.TabularInline):
    model = ItemLote
    extra = 0
    readonly_fields = ('documento', 'nome_original', 'ordem', 'reutilizado')


@admin.register(Lote)
class LoteAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('id', 'empresa', 'modo', 'criado_em', 'enviado_por')
    list_filter = ('modo', 'criado_em')
    inlines = (ItemLoteInline,)


@admin.register(Documento)
class DocumentoAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = (
        'empresa', 'placa', 'processo', 'pipeline', 'provedor_utilizado', 'status',
        'enviado_em', 'enviado_por',
    )
    list_filter = ('status', 'pipeline', 'provedor_utilizado', 'placa_valida')
    search_fields = ('placa', 'processo', 'renavam', 'proprietario', 'hash_sha256')
    readonly_fields = (
        'enviado_em', 'hash_sha256', 'processamento_iniciado_em',
        'processamento_finalizado_em',
    )
