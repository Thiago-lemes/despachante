import json
import logging

from django import template
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.http import HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST
from empresas.models import Empresa
from empresas.permissoes import somente_administrador

from .forms import ConfiguracaoBotForm, DocumentoExigidoFormSet, ServicoForm
from .models import ConfiguracaoBot, Conversa, Tarefa, Servico
from .services import bot

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

    empresa = _empresa_do_usuario(request)
    if not empresa:
        return JsonResponse({'status': 'erro', 'erro': 'Nenhuma empresa ativa.'}, status=403)

    # Filtrar pela empresa impede mover tarefa de outro tenant sabendo o id.
    tarefa = get_object_or_404(Tarefa, id=tarefa_id, empresa=empresa)

    agora = timezone.now()
    campos = ['status']
    tarefa.status = novo_status

    if novo_status == Tarefa.Status.ABERTA:
        # Voltar para "Aberta" devolve a tarefa à fila, sem dono.
        tarefa.atendente = None
        tarefa.assumida_em = None
        campos += ['atendente', 'assumida_em']
    else:
        # Quem move a tarefa assume o atendimento.
        tarefa.atendente = request.user
        campos.append('atendente')
        if not tarefa.assumida_em:
            tarefa.assumida_em = agora
            campos.append('assumida_em')

    if novo_status in (Tarefa.Status.CONCLUIDA, Tarefa.Status.CANCELADA):
        tarefa.concluida_em = agora
        campos.append('concluida_em')
    elif tarefa.concluida_em:
        tarefa.concluida_em = None
        campos.append('concluida_em')

    tarefa.save(update_fields=campos)

    # Assumir o card cala o bot naquela conversa. Devolver para "Aberta" não o
    # religa: quem já foi atendido por uma pessoa não volta para a triagem
    # automática no meio do assunto.
    if novo_status != Tarefa.Status.ABERTA:
        conversa = tarefa.conversa
        if conversa.modo != Conversa.Modo.HUMANO:
            conversa.modo = Conversa.Modo.HUMANO
            conversa.save(update_fields=['modo', 'atualizada_em'])

    atendente = tarefa.atendente
    return JsonResponse({
        'status': 'ok',
        'novo_status': tarefa.status,
        'atendente': atendente.get_full_name() or atendente.username if atendente else '',
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
