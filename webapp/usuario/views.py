from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from .forms import CadastroDespachanteForm


@login_not_required
def cadastro_despachante(request):
    if request.method == 'POST':
        form = CadastroDespachanteForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('busca')
    else:
        form = CadastroDespachanteForm()
    return render(request, 'usuario/cadastro.html', {'form': form})
print('DEBUG: View usuario chamada')
