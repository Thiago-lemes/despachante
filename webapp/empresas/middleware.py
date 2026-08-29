from .models import EmpresaUsuario


class EmpresaAtualMiddleware:
    """Define a empresa ativa da sessão para todas as views autenticadas."""

    session_key = 'empresa_atual_id'

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.empresa = None
        if request.user.is_authenticated:
            vinculos = EmpresaUsuario.objects.filter(
                usuario=request.user,
                ativo=True,
                empresa__ativa=True,
            ).select_related('empresa')
            empresa_id = request.session.get(self.session_key)
            vinculo = vinculos.filter(empresa_id=empresa_id).first() if empresa_id else None
            vinculo = vinculo or vinculos.order_by('empresa__nome').first()
            if vinculo:
                request.empresa = vinculo.empresa
                if empresa_id != vinculo.empresa_id:
                    request.session[self.session_key] = vinculo.empresa_id
        return self.get_response(request)
