import json
import logging

from django import template
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count, OuterRef, Subquery
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from empresas.models import Empresa, EmpresaUsuario
from empresas.permissoes import somente_administrador

from integracao.services.conversas import encerrar_conversa

from .forms import ConfiguracaoBotForm, DocumentoExigidoFormSet, ServicoForm
from .models import ConfiguracaoBot, Conversa, Mensagem, Tarefa, Servico, nome_curto
from .services import bot
from .services.atendimento import (
    assumir_tarefa,
    atribuir_tarefa,
    pode_responder,
    responder,
    tarefa_aberta_da_conversa,
)

register = template.Library()


@register.filter
def get_item(dictionary, key):
    return dictionary.get(key)


logger = logging.getLogger(__name__)


def _empresa_do_usuario(request):
    """Empresa ativa da requisição: middleware, sessão ou primeiro vínculo."""
    empresa = getattr(request, 'empresa', None)
    if empresa:
        return empresa

    empresa_id = request.session.get('empresa_atual_id')
    if empresa_id:
        empresa = Empresa.objects.filter(id=empresa_id, ativa=True).first()
        if empresa:
            return empresa

    vinculos = getattr(request.user, 'empresas_vinculadas', None)
    vinculo = vinculos.first() if vinculos else None
    if vinculo:
        request.session['empresa_atual_id'] = vinculo.empresa_id
        return vinculo.empresa

    return None


@login_required
def kanban_tarefas(request):
    """Renderiza o kanban visual de tarefas"""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')

    tarefas_por_status = {}
    total_tarefas = 0
    for status, _label in Tarefa.Status.choices:
        tarefas = list(
            Tarefa.objects.filter(empresa=empresa, status=status)
            .select_related('contato', 'servico', 'atendente', 'conversa')
            .prefetch_related('conversa__documentos_recebidos')
            .order_by('-criada_em')
        )
        tarefas_por_status[status] = tarefas
        total_tarefas += len(tarefas)

    servicos = Servico.objects.filter(empresa=empresa, ativo=True)

    return render(request, 'atendimento/kanban.html', {
        'tarefas_por_status': tarefas_por_status,
        'status_choices': Tarefa.Status.choices,
        'servicos': servicos,
        'total_tarefas': total_tarefas,
    })


@login_required
def tarefas_novas_status(request):
    """Quantidade de tarefas ainda não atendidas, para o badge do menu."""
    empresa = _empresa_do_usuario(request)
    total = 0
    if empresa:
        total = Tarefa.objects.filter(
            empresa=empresa, status=Tarefa.Status.ABERTA).count()
    return JsonResponse({'total': total})


@require_POST
@login_required
def atualizar_status_tarefa(request):
    """Atualiza o status de uma tarefa (drag-and-drop do Kanban)."""
    try:
        dados = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'erro', 'erro': 'JSON inválido.'}, status=400)

    tarefa_id = dados.get('tarefa_id')
    novo_status = dados.get('novo_status')

    if not tarefa_id or not novo_status:
        return JsonResponse({'status': 'erro', 'erro': 'Parâmetros inválidos.'}, status=400)

    if novo_status not in Tarefa.Status.values:
        return JsonResponse({'status': 'erro', 'erro': 'Status inválido.'}, status=400)

    if novo_status == Tarefa.Status.ABERTA:
        # Card assumido não volta para a fila: é isso que garante que só o dono
        # fale com o cliente. Para passar adiante existe a transferência.
        return JsonResponse({
            'status': 'erro',
            'erro': 'Um atendimento assumido não volta para a fila. '
                    'Use "atribuir para" no card para passá-lo a outra pessoa.',
        }, status=409)

    empresa = _empresa_do_usuario(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'erro': 'Nenhuma empresa ativa.'}, status=403)

    # Filtrar pela empresa impede mover tarefa de outro tenant sabendo o id.
    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)

    if tarefa.status == Tarefa.Status.ABERTA:
        assumida = assumir_tarefa(tarefa, request.user)
        if assumida is None:
            tarefa.refresh_from_db()
            return JsonResponse({
                'status': 'erro',
                'erro': f'{nome_curto(tarefa.atendente)} assumiu este atendimento '
                        'primeiro.' if tarefa.atendente else
                        'Este atendimento já saiu da fila.',
                'atendente': nome_curto(tarefa.atendente),
            }, status=409)
        tarefa = assumida
        if novo_status == Tarefa.Status.EM_ATENDIMENTO:
            return _resposta_da_tarefa(tarefa)

    # Daqui em diante o card já tem dono, e só ele o move. Quem quiser mexer no
    # card de outra pessoa passa pela transferência, que deixa rastro.
    if tarefa.atendente_id and tarefa.atendente_id != request.user.id:
        return JsonResponse({
            'status': 'erro',
            'erro': f'Este atendimento é de {nome_curto(tarefa.atendente)}. '
                    'Assuma o card antes de movê-lo.',
        }, status=403)

    agora = timezone.now()
    campos = ['status']
    tarefa.status = novo_status

    if novo_status in (Tarefa.Status.CONCLUIDA, Tarefa.Status.CANCELADA):
        tarefa.concluida_em = agora
        campos.append('concluida_em')
    elif tarefa.concluida_em:
        tarefa.concluida_em = None
        campos.append('concluida_em')

    tarefa.save(update_fields=campos)

    if novo_status in (Tarefa.Status.CONCLUIDA, Tarefa.Status.CANCELADA):
        # Fechar o card encerra a conversa. Sem isso ela ficaria viva em modo
        # humano para sempre: o bot não responde e ninguém é avisado, então a
        # mensagem do cliente que volta depois morreria no banco.
        encerrar_conversa(
            tarefa.conversa, motivo=f'tarefa_{novo_status}',
            ator=request.user.username)

    return _resposta_da_tarefa(tarefa)


def _resposta_da_tarefa(tarefa):
    return JsonResponse({
        'status': 'ok',
        'novo_status': tarefa.status,
        'atendente': nome_curto(tarefa.atendente),
    })


# --- Atendimento humano ------------------------------------------------------
# O WhatsApp entrega tudo por um número só e não sabe o que é um atendente.
# Quem pode falar com quem se decide aqui.

def _minhas_tarefas(empresa, usuario):
    """Atendimentos que estão comigo, com a última mensagem de cada um.

    A última mensagem é o que diz se a bola está com o cliente ou comigo —
    carregá-la por subconsulta evita uma ida ao banco por conversa na lista.
    """
    ultima = Mensagem.objects.filter(
        conversa=OuterRef('conversa')).order_by('-criada_em', '-id')
    return (
        Tarefa.objects
        .filter(empresa=empresa, atendente=usuario,
                status=Tarefa.Status.EM_ATENDIMENTO)
        .select_related('contato', 'servico', 'conversa')
        .annotate(
            ultima_direcao=Subquery(ultima.values('direcao')[:1]),
            ultima_conteudo=Subquery(ultima.values('conteudo')[:1]),
            ultima_em=Subquery(ultima.values('criada_em')[:1]),
        )
        .order_by('-ultima_em')
    )


@login_required
def minhas_conversas(request):
    """Só os atendimentos do usuário logado — o Kanban mostra os da empresa."""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')

    tarefas = list(_minhas_tarefas(empresa, request.user))
    # Última mensagem de entrada = o cliente falou e ainda não foi respondido.
    for tarefa in tarefas:
        tarefa.aguardando_resposta = (
            tarefa.ultima_direcao == Mensagem.Direcao.ENTRADA)

    return render(request, 'atendimento/minhas_conversas.html', {
        'tarefas': tarefas,
        'aguardando': sum(1 for t in tarefas if t.aguardando_resposta),
    })


@login_required
def minhas_conversas_status(request):
    """Quantas das minhas conversas esperam resposta, para o badge do menu."""
    empresa = _empresa_do_usuario(request)
    total = 0
    if empresa:
        total = _minhas_tarefas(empresa, request.user).filter(
            ultima_direcao=Mensagem.Direcao.ENTRADA).count()
    return JsonResponse({'total': total})


@login_required
def conversa(request, tarefa_id):
    """Histórico do atendimento, com campo de resposta só para o dono do card."""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa está vinculada a este usuário.')

    tarefa = get_object_or_404(
        Tarefa.objects.select_related('conversa', 'contato', 'servico', 'atendente'),
        id=tarefa_id, empresa=empresa)

    return render(request, 'atendimento/conversa.html', {
        'tarefa': tarefa,
        'conversa': tarefa.conversa,
        'linha_do_tempo': _linha_do_tempo(tarefa.conversa),
        # O polling compara contagem de mensagens, não da linha do tempo, que
        # também tem documentos — comparar coisas diferentes recarregaria sempre.
        'total_mensagens': tarefa.conversa.mensagens.count(),
        'pode_responder': pode_responder(tarefa.conversa, request.user),
        'na_fila': tarefa.status == Tarefa.Status.ABERTA,
        'colegas': _colegas(empresa, request.user),
    })


def _linha_do_tempo(conversa_obj):
    """Mensagens e documentos recebidos numa sequência só, em ordem.

    Documento numa lista à parte obriga o atendente a cruzar horários na mão
    para saber o que o cliente mandou em resposta a quê.
    """
    itens = [
        {'tipo': 'mensagem', 'quando': m.criada_em, 'mensagem': m}
        for m in conversa_obj.mensagens.select_related('autor')
    ]
    itens += [
        {'tipo': 'documento', 'quando': d.criado_em, 'documento': d}
        for d in conversa_obj.documentos_recebidos.select_related('documento_exigido')
    ]
    itens.sort(key=lambda item: item['quando'])
    return itens


def _colegas(empresa, usuario):
    """Quem pode receber um atendimento: vínculo ativo, menos o próprio."""
    return [
        vinculo.usuario for vinculo in EmpresaUsuario.objects
        .filter(empresa=empresa, ativo=True)
        .exclude(usuario=usuario)
        .select_related('usuario')
        .order_by('usuario__first_name', 'usuario__username')
    ]


@require_POST
@login_required
def conversa_responder(request, tarefa_id):
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'erro': 'Nenhuma empresa ativa.'}, status=403)

    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)
    texto = (request.POST.get('texto') or '').strip()
    if not texto:
        return JsonResponse({'status': 'erro', 'erro': 'Escreva a mensagem.'}, status=400)

    if not pode_responder(tarefa.conversa, request.user):
        dono = nome_curto(tarefa.atendente)
        return JsonResponse({
            'status': 'erro',
            'erro': f'Este atendimento é de {dono}.' if dono else
                    'Assuma o atendimento para poder responder.',
        }, status=403)

    if not responder(tarefa.conversa, request.user, texto):
        # Não gravar como enviada é o ponto: o atendente precisa ver que não saiu.
        return JsonResponse({
            'status': 'erro',
            'erro': 'A mensagem não foi enviada. Verifique o vínculo do WhatsApp.',
        }, status=502)

    return redirect('conversa', tarefa_id=tarefa.id)


@require_POST
@login_required
def tarefa_assumir(request, tarefa_id):
    """Puxa o card para si — da fila (com trava) ou de outro atendente."""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa.')

    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)

    if tarefa.status == Tarefa.Status.ABERTA:
        if assumir_tarefa(tarefa, request.user) is None:
            tarefa.refresh_from_db()
            messages.warning(
                request,
                f'{nome_curto(tarefa.atendente)} assumiu este atendimento primeiro.')
        else:
            messages.success(request, 'Atendimento assumido.')
    elif tarefa.atendente_id == request.user.id:
        messages.info(request, 'Este atendimento já é seu.')
    else:
        anterior = nome_curto(tarefa.atendente)
        atribuir_tarefa(tarefa, request.user, por=request.user)
        messages.success(
            request,
            f'Atendimento assumido{f" de {anterior}" if anterior else ""}.')

    return redirect('conversa', tarefa_id=tarefa.id)


@require_POST
@login_required
def tarefa_atribuir(request, tarefa_id):
    """Entrega o atendimento a um colega — inclusive o de quem saiu da empresa."""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return HttpResponseForbidden('Nenhuma empresa ativa.')

    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)

    # O destino tem que ter vínculo ativo: atribuir para quem não entra mais no
    # sistema é o problema que este requisito veio resolver, não criar.
    vinculo = EmpresaUsuario.objects.filter(
        empresa=empresa, usuario_id=request.POST.get('usuario_id'), ativo=True
    ).select_related('usuario').first()
    if not vinculo:
        messages.error(request, 'Escolha alguém com acesso ativo à empresa.')
        return redirect('conversa', tarefa_id=tarefa.id)

    atribuir_tarefa(tarefa, vinculo.usuario, por=request.user)
    messages.success(
        request, f'Atendimento atribuído a {nome_curto(vinculo.usuario)}.')
    return redirect('conversa', tarefa_id=tarefa.id)


@login_required
def conversa_novidades(request, tarefa_id):
    """Quantas mensagens a conversa tem agora, para a tela se atualizar sozinha."""
    empresa = _empresa_do_usuario(request)
    if not empresa:
        return JsonResponse({'total': 0})

    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)
    return JsonResponse({
        'total': tarefa.conversa.mensagens.count(),
        'status': tarefa.status,
        'atendente': nome_curto(tarefa.atendente),
    })


# --- Configuração do chatbot -------------------------------------------------
# Tela do dono da empresa: é ela que decide o que o cliente vê no WhatsApp.
# O decorator exige papel de administrador — funcionário aprovado não entra.

@somente_administrador('Apenas administradores da empresa configuram o chatbot.')
def chatbot_config(request):
    """Comportamento do bot, catálogo de serviços e conversas em modo humano."""
    empresa = request.empresa
    configuracao = ConfiguracaoBot.para(empresa)

    if request.method == 'POST':
        form = ConfiguracaoBotForm(request.POST, instance=configuracao)
        if form.is_valid():
            form.save()
            messages.success(request, 'Configuração do chatbot salva.')
            return redirect('chatbot_config')
    else:
        form = ConfiguracaoBotForm(instance=configuracao)

    servicos = list(
        Servico.objects.filter(empresa=empresa)
        .annotate(total_documentos=Count('documentos_exigidos'))
        .order_by('ordem', 'nome')
    )
    return render(request, 'atendimento/chatbot.html', {
        'form': form,
        'configuracao': configuracao,
        'menu': _arvore_do_menu(servicos),
        'tem_servicos': bool(servicos),
        'servicos_no_menu': [s for s in servicos if s.ativo and s.pai_id is None],
        'conversas_humanas': _conversas_em_atendimento_humano(empresa),
    })


def _arvore_do_menu(servicos):
    """Achata a árvore de opções em uma lista de níveis, para o template.

    O template não sabe recursão, e a tela precisa mostrar cada grupo de irmãos
    junto — é entre irmãos que a ordem do menu vale. Cada item leva o próprio
    grupo de filhos, montado de uma vez a partir dos serviços já carregados,
    sem uma consulta por nó.
    """
    filhos_de = {}
    for servico in servicos:
        filhos_de.setdefault(servico.pai_id, []).append(servico)

    def montar(pai_id, nivel):
        grupo = []
        for servico in filhos_de.get(pai_id, []):
            grupo.append({
                'servico': servico,
                'nivel': nivel,
                'subopcoes': montar(servico.id, nivel + 1),
            })
        return grupo

    return montar(None, 0)


def _conversas_em_atendimento_humano(empresa):
    return (
        Conversa.objects.filter(empresa=empresa, modo=Conversa.Modo.HUMANO)
        .exclude(estado=Conversa.Estado.ENCERRADA)
        .select_related('contato', 'servico')
        .order_by('-atualizada_em')[:50]
    )


@somente_administrador('Apenas administradores da empresa configuram o chatbot.')
def chatbot_servico(request, servico_id=None):
    """Cria ou edita uma opção do menu com os documentos que o bot vai pedir.

    `?pai=<id>` cria a opção como sub-opção de outra — é como o botão
    "Adicionar sub-opção" da lista chega aqui.
    """
    empresa = request.empresa
    servico = get_object_or_404(
        Servico, pk=servico_id, empresa=empresa) if servico_id else Servico(empresa=empresa)

    pai = None
    if servico_id:
        pai = servico.pai
    else:
        pai_id = request.POST.get('pai') or request.GET.get('pai')
        if pai_id:
            # Filtrar pela empresa impede pendurar uma opção na árvore de outro
            # tenant sabendo o id.
            pai = get_object_or_404(Servico, pk=pai_id, empresa=empresa)

    if request.method == 'POST':
        form = ServicoForm(request.POST, instance=servico, empresa=empresa, pai=pai)
        # O formset precisa da instância salva para amarrar os documentos, mas
        # só vale salvar o serviço se os dois estiverem válidos.
        formset = DocumentoExigidoFormSet(request.POST, instance=servico)
        if form.is_valid() and formset.is_valid():
            servico = form.save()
            formset.instance = servico
            formset.save()
            messages.success(request, f'Opção "{servico.caminho()}" salva.')
            return redirect('chatbot_config')
    else:
        form = ServicoForm(instance=servico, empresa=empresa, pai=pai)
        formset = DocumentoExigidoFormSet(instance=servico)

    configuracao = ConfiguracaoBot.para(empresa)
    subopcoes = servico.subopcoes_do_menu() if servico.pk else []
    return render(request, 'atendimento/chatbot_servico.html', {
        'form': form,
        'formset': formset,
        'servico': servico if servico.pk else None,
        'pai': pai,
        'subopcoes': subopcoes,
        # A prévia da conversa é montada no navegador com os moldes reais do bot,
        # para não reescrevê-los em JavaScript e vê-los divergir depois.
        'textos_bot': bot.textos_do_bot(configuracao),
        'previa_submenu': {
            # Quando a opção ramifica, a conversa não segue para documentos: o
            # que o cliente recebe é o submenu.
            'opcoes': [s.nome for s in subopcoes],
            'rotulo_atendente': configuracao.rotulo_atendente,
            'pergunta_padrao': Servico.PERGUNTA_PADRAO,
        },
    })


@require_POST
@somente_administrador('Apenas administradores da empresa configuram o chatbot.')
def chatbot_servico_excluir(request, servico_id):
    """Remove um serviço do menu.

    Serviço já usado em conversa ou tarefa é protegido pelo banco (PROTECT);
    nesse caso o caminho é desativar, não excluir.
    """
    servico = get_object_or_404(Servico, pk=servico_id, empresa=request.empresa)

    # Uma opção com sub-opções levaria o galho inteiro junto (FK em CASCADE), e
    # basta uma delas ter atendimento para o banco recusar no meio do caminho.
    if servico.subopcoes.exists():
        messages.error(request, (
            f'"{servico.nome}" tem sub-opções. Exclua ou esvazie as sub-opções antes, '
            'ou apenas desmarque "Aparece no menu do WhatsApp" para tirá-la do ar.'
        ))
        return redirect('chatbot_config')

    if servico.conversa_set.exists() or servico.tarefa_set.exists():
        servico.ativo = False
        servico.save(update_fields=['ativo'])
        messages.warning(request, (
            f'"{servico.nome}" já tem atendimentos registrados e não pode ser '
            'excluído. Ele foi desativado e não aparece mais no menu.'
        ))
    else:
        nome = servico.nome
        servico.documentos_exigidos.all().delete()
        servico.delete()
        messages.success(request, f'Opção "{nome}" excluída do menu.')
    return redirect('chatbot_config')


@require_POST
@somente_administrador('Apenas administradores da empresa configuram o chatbot.')
def chatbot_reordenar_servicos(request):
    """Grava a ordem do menu depois de arrastar um serviço na lista."""
    try:
        dados = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return JsonResponse({'status': 'erro', 'erro': 'JSON inválido.'}, status=400)

    ids = dados.get('ordem')
    if not isinstance(ids, list) or not ids:
        return JsonResponse({'status': 'erro', 'erro': 'Ordem inválida.'}, status=400)

    # A ordem vale entre irmãos: cada submenu tem a própria numeração, então a
    # lista que chega é a de um nível só, identificado pelo pai.
    pai_id = dados.get('pai')
    irmaos = Servico.objects.filter(empresa=request.empresa, pai_id=pai_id)

    servicos = {servico.id: servico for servico in irmaos.filter(id__in=ids)}
    # A lista precisa cobrir exatamente os irmãos daquele nível: uma ordem
    # parcial deixaria os ausentes com o número antigo, empatando com os novos.
    if len(servicos) != len(ids) or len(ids) != irmaos.count():
        return JsonResponse(
            {'status': 'erro', 'erro': 'A lista não corresponde às opções deste nível.'},
            status=400)

    for posicao, servico_id in enumerate(ids, 1):
        servicos[servico_id].ordem = posicao
    Servico.objects.bulk_update(servicos.values(), ['ordem'])

    return JsonResponse({'status': 'ok'})


@require_POST
@somente_administrador('Apenas administradores da empresa configuram o chatbot.')
def chatbot_religar_conversa(request, conversa_id):
    """Devolve ao bot uma conversa que estava em atendimento humano."""
    conversa = get_object_or_404(
        Conversa, pk=conversa_id, empresa=request.empresa,
        modo=Conversa.Modo.HUMANO)

    if not bot.servicos_do_menu(request.empresa):
        messages.error(request, (
            'Cadastre ao menos um serviço ativo antes de devolver conversas ao bot '
            '— sem menu ele não teria o que oferecer.'
        ))
        return redirect('chatbot_config')

    if bot.religar(conversa):
        messages.success(
            request, f'{conversa.contato.nome_exibicao} voltou para o atendimento automático.')
    else:
        # O modo já mudou; o que falhou foi o envio (sessão do WhatsApp fora do ar).
        messages.warning(request, (
            'A conversa voltou para o bot, mas o menu não pôde ser enviado. '
            'Confira o vínculo do WhatsApp.'
        ))
    return redirect('chatbot_config')
