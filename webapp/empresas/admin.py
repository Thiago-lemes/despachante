from django.contrib import admin

from .admin_utils import EmpresaAdminMixin
from .models import Empresa, EmpresaUsuario


class EmpresaUsuarioInline(admin.TabularInline):
    model = EmpresaUsuario
    extra = 0
    autocomplete_fields = ('usuario',)


@admin.register(Empresa)
class EmpresaAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    empresa_lookup = 'id'
    list_display = ('nome', 'cnpj', 'ativa', 'criada_em')
    list_filter = ('ativa',)
    search_fields = ('nome', 'cnpj')
    readonly_fields = ('criada_em', 'atualizada_em')
    inlines = (EmpresaUsuarioInline,)


@admin.register(EmpresaUsuario)
class EmpresaUsuarioAdmin(EmpresaAdminMixin, admin.ModelAdmin):
    list_display = ('usuario', 'empresa', 'papel', 'ativo')
    list_filter = ('empresa', 'papel', 'ativo')
    search_fields = ('usuario__username', 'usuario__email', 'empresa__nome')
    autocomplete_fields = ('usuario', 'empresa')
    readonly_fields = ('criado_em', 'atualizado_em')
