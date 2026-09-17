from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse

from .models import EmpresaUsuario


class EmpresaAtualMiddleware:
    """Define a empresa ativa da sessão para todas as views autenticadas."""

    session_key = 'empresa_atual_id'

    # Rotas liberadas para quem está autenticado mas ainda não tem nenhum
    # vínculo ativo (funcionário aguardando aprovação). Sem isso o redirect
    # para a página de espera viraria um laço — e sem sair do lugar, já que
    # nem o logout responderia.
    rotas_livres = ('acesso_pendente', 'logout', 'login')

    def __init__(self, get_response):
        self.get_response = get_response
        self._caminhos_livres = None

    def __call__(self, request):
        request.empresa = None
        request.empresa_vinculo = None
        request.empresa_aprovacoes_pendentes = 0

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
                request.empresa_vinculo = vinculo
                if empresa_id != vinculo.empresa_id:
                    request.session[self.session_key] = vinculo.empresa_id
                if vinculo.pode_administrar():
                    request.empresa_aprovacoes_pendentes = EmpresaUsuario.objects.filter(
                        empresa=vinculo.empresa, ativo=False).count()
            elif self._aguarda_aprovacao(request.user) and self._deve_bloquear(request):
                return redirect('acesso_pendente')

        return self.get_response(request)

    def _aguarda_aprovacao(self, usuario):
        """Quem se cadastrou como funcionário e ainda não foi liberado.

        O desvio vale só para esse caso: uma conta sem vínculo nenhum é outra
        situação (usuário criado pelo admin do Django, por exemplo) e segue
        navegando como antes.
        """
        return EmpresaUsuario.objects.filter(usuario=usuario, ativo=False).exists()

    def _deve_bloquear(self, request):
        """Segura na página de espera só o usuário comum sem vínculo ativo."""
        if request.user.is_staff:
            return False
        prefixos = ['/admin/']
        for url in (settings.STATIC_URL, settings.MEDIA_URL):
            if url:
                prefixos.append(url)
        if any(request.path.startswith(prefixo) for prefixo in prefixos):
            return False
        # O middleware roda antes do roteamento, então resolver_match ainda é
        # None aqui: a comparação é pelos caminhos das rotas liberadas.
        if self._caminhos_livres is None:
            self._caminhos_livres = {reverse(nome) for nome in self.rotas_livres}
        return request.path not in self._caminhos_livres
