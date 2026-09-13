from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from .forms import CadastroDespachanteForm
from integracao.models import WahaSessao
from empresas.models import EmpresaUsuario


@login_not_required
def cadastro_despachante(request):
    if request.method == 'POST':
        form = CadastroDespachanteForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)

            # 1. Recupera a empresa associada a este novo usuário
            vinculo = EmpresaUsuario.objects.filter(usuario=user, ativo=True).first()
            if vinculo:
                empresa = vinculo.empresa
                request.session['empresa_atual_id'] = empresa.id

                # 2. Cria a sessão do WAHA para a nova empresa
                nome_sessao = f"empresa_{empresa.id}"
                WahaSessao.objects.get_or_create(
                    empresa=empresa,
                    nome_sessao=nome_sessao,
                    defaults={'ativa': True}
                )

                # 3. Redireciona para a tela do QR Code da empresa
                return redirect('gerar_qr_code_empresa', empresa_id=empresa.id)

            return redirect('busca')
    else:
        form = CadastroDespachanteForm()
    return render(request, 'usuario/cadastro.html', {'form': form})