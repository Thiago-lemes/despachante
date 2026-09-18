"""Portão de acesso das telas restritas ao dono da empresa.

"Perfil da empresa" é o vínculo criado pela aba "Sou empresa" do cadastro, que
nasce como ADMINISTRADOR. Funcionário nasce ATENDENTE — e continua fora daqui
mesmo depois de aprovado.
"""
from functools import wraps

from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden


def pode_administrar(request):
    vinculo = getattr(request, 'empresa_vinculo', None)
    return getattr(request, 'empresa', None) is not None and (
        vinculo is not None and vinculo.pode_administrar())


def somente_administrador(mensagem='Apenas administradores da empresa acessam esta página.'):
    """Exige login e papel de administrador na empresa ativa."""
    def decorador(view):
        @wraps(view)
        @login_required
        def wrapper(request, *args, **kwargs):
            if not pode_administrar(request):
                return HttpResponseForbidden(mensagem)
            return view(request, *args, **kwargs)
        return wrapper
    return decorador
