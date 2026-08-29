from .models import EmpresaUsuario


class EmpresaAdminMixin:
    """Restringe o admin aos registros da empresa do usuário administrativo."""

    empresa_lookup = 'empresa'

    @staticmethod
    def _empresa_ids(request):
        return EmpresaUsuario.objects.filter(
            usuario=request.user,
            ativo=True,
            empresa__ativa=True,
        ).values_list('empresa_id', flat=True)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser:
            return queryset
        return queryset.filter(**{f'{self.empresa_lookup}__in': self._empresa_ids(request)})

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        """Não oferece no admin relações pertencentes a outra empresa."""
        if not request.user.is_superuser:
            empresa_ids = self._empresa_ids(request)
            modelo_relacionado = db_field.remote_field.model
            campos_relacionados = {
                campo.name for campo in modelo_relacionado._meta.get_fields()
            }
            if db_field.name == 'empresa':
                kwargs['queryset'] = modelo_relacionado.objects.filter(id__in=empresa_ids)
            elif 'empresa' in campos_relacionados:
                kwargs['queryset'] = modelo_relacionado.objects.filter(empresa_id__in=empresa_ids)
            elif db_field.name in {'enviado_por', 'atendente', 'usuario'}:
                kwargs['queryset'] = modelo_relacionado.objects.filter(
                    empresas_vinculadas__empresa_id__in=empresa_ids,
                    empresas_vinculadas__ativo=True,
                ).distinct()
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
