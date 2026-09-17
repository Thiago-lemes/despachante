from django.shortcuts import render, redirect
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from .forms import CadastroEmpresaForm, CadastroFuncionarioForm
from empresas.models import EmpresaUsuario

ABAS = ('empresa', 'funcionario')
SESSAO_EMPRESA_SOLICITADA = 'cadastro_empresa_solicitada'


@login_not_required
def cadastro_despachante(request):
    """Cadastro em duas abas: criar a empresa ou entrar em uma já existente."""
    aba = request.POST.get('aba') or request.GET.get('aba') or 'empresa'
    if aba not in ABAS:
        aba = 'empresa'

    enviou_empresa = request.method == 'POST' and aba == 'empresa'
    enviou_funcionario = request.method == 'POST' and aba == 'funcionario'

    # auto_id distinto por aba: os dois formulários convivem no mesmo HTML e,
    # com o id padrão, 'id_username' apareceria duas vezes — o rótulo de uma aba
    # focaria o campo escondido da outra.
    form_empresa = CadastroEmpresaForm(
        request.POST if enviou_empresa else None, auto_id='empresa_%s')
    form_funcionario = CadastroFuncionarioForm(
        request.POST if enviou_funcionario else None, auto_id='funcionario_%s')

    if enviou_empresa and form_empresa.is_valid():
        user = form_empresa.save()
        login(request, user)

        # Define a empresa ativa na sessão. A vinculação do WhatsApp fica
        # a cargo do usuário, pelo botão "Vincular WhatsApp" do menu.
        vinculo = EmpresaUsuario.objects.filter(usuario=user, ativo=True).first()
        if vinculo:
            request.session['empresa_atual_id'] = vinculo.empresa_id

        return redirect('busca')

    if enviou_funcionario and form_funcionario.is_valid():
        form_funcionario.save()
        # Sem login: o vínculo nasce inativo e o acesso só existe após a
        # aprovação de um administrador da empresa.
        request.session[SESSAO_EMPRESA_SOLICITADA] = form_funcionario.empresa.nome
        return redirect('cadastro_enviado')

    return render(request, 'usuario/cadastro.html', {
        'form_empresa': form_empresa,
        'form_funcionario': form_funcionario,
        'aba': aba,
    })


@login_not_required
def cadastro_enviado(request):
    """Confirma ao funcionário que o pedido de acesso aguarda aprovação."""
    empresa_nome = request.session.pop(SESSAO_EMPRESA_SOLICITADA, None)
    if not empresa_nome:
        return redirect('cadastro')
    return render(request, 'usuario/cadastro_enviado.html', {'empresa_nome': empresa_nome})
