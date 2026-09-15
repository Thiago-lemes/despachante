from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from .forms import CadastroDespachanteForm
from empresas.models import EmpresaUsuario


@login_not_required
def cadastro_despachante(request):
    if request.method == 'POST':
        form = CadastroDespachanteForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)

            # Define a empresa ativa na sessão. A vinculação do WhatsApp fica
            # a cargo do usuário, pelo botão "Vincular WhatsApp" do menu.
            vinculo = EmpresaUsuario.objects.filter(usuario=user, ativo=True).first()
            if vinculo:
                request.session['empresa_atual_id'] = vinculo.empresa_id

            return redirect('busca')
    else:
        form = CadastroDespachanteForm()
    return render(request, 'usuario/cadastro.html', {'form': form})