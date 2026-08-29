import hashlib

from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.decorators import login_not_required
from django.http import FileResponse, JsonResponse
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import content_disposition_header

from .forms import BuscaPlacaForm, CadastroForm, PerfilForm, UploadForm, normaliza_placa
from .models import Documento, ItemLote, Lote
from .services import campos_para_exibir


def _empresa_atual(request):
    if not request.empresa:
        raise PermissionDenied('Nenhuma empresa ativa está vinculada a este usuário.')
    return request.empresa


def _documentos_da_empresa(request):
    return Documento.objects.filter(empresa=_empresa_atual(request))


def _hash_arquivo(arquivo):
    digest = hashlib.sha256()
    for trecho in arquivo.chunks():
        digest.update(trecho)
    arquivo.seek(0)
    return digest.hexdigest()


def busca(request):
    form = BuscaPlacaForm(request.GET or None)
    contexto = {'form': form}
    if form.is_valid():
        placa = form.cleaned_data['placa']
        docs = _documentos_da_empresa(request).filter(placa=placa, status='concluido')
        contexto['placa_buscada'] = placa
        if docs:
            doc = docs.first()
            contexto.update({
                'documento': doc,
                'campos': campos_para_exibir(doc.resultado),
                'outros': docs[1:],
            })
        else:
            contexto['nao_encontrada'] = True
            contexto['upload_form'] = UploadForm(
                initial={'placa_esperada': placa, 'modo': 'avulso'})
    return render(request, 'documentos/busca.html', contexto)


def enviar(request):
    if request.method == 'POST':
        form = UploadForm(request.POST, request.FILES)
        if form.is_valid():
            modo = form.cleaned_data['modo']
            pipeline = 'openai' if modo == 'lote' else 'gemini'
            empresa = _empresa_atual(request)
            lote = Lote.objects.create(modo=modo, empresa=empresa, enviado_por=request.user)
            reutilizados = 0
            for ordem, arquivo in enumerate(form.cleaned_data['arquivos']):
                arquivo_hash = _hash_arquivo(arquivo)
                candidatos = _documentos_da_empresa(request).filter(
                    hash_sha256=arquivo_hash, pipeline=pipeline)
                existente = (
                    candidatos.filter(status='concluido').first()
                    or candidatos.exclude(status='erro').first()
                    or candidatos.first()
                )
                reutilizado = existente is not None
                if existente:
                    documento = existente
                    reutilizados += 1
                    if documento.status == 'erro':
                        documento.status = 'aguardando'
                        documento.erro = ''
                        documento.tentativas = 0
                        documento.processamento_iniciado_em = None
                        documento.processamento_finalizado_em = None
                        documento.save()
                else:
                    documento = Documento.objects.create(
                        arquivo=arquivo,
                        empresa=empresa,
                        hash_sha256=arquivo_hash,
                        enviado_por=request.user,
                        pipeline=pipeline,
                        status='aguardando',
                    )
                ItemLote.objects.create(
                    lote=lote,
                    documento=documento,
                    nome_original=arquivo.name[:255],
                    ordem=ordem,
                    reutilizado=reutilizado,
                )
            if reutilizados:
                messages.info(
                    request,
                    f'{reutilizados} arquivo(s) já conhecido(s) foram reutilizados.')
            if modo == 'avulso':
                return redirect('detalhe', pk=lote.itens.get().documento_id)
            return redirect('lote_detalhe', pk=lote.pk)
    else:
        form = UploadForm(initial={'modo': request.GET.get('modo', 'avulso')})
    return render(request, 'documentos/enviar.html', {'form': form})


@login_not_required
def cadastro(request):
    if request.user.is_authenticated:
        return redirect('busca')
    if request.method == 'POST':
        form = CadastroForm(request.POST)
        if form.is_valid():
            usuario = form.save()
            login(request, usuario)
            messages.success(request, 'Conta criada com sucesso.')
            return redirect('busca')
    else:
        form = CadastroForm()
    return render(request, 'registration/cadastro.html', {'form': form})


def conta(request):
    if request.method == 'POST':
        form = PerfilForm(request.POST, instance=request.user)
        if form.is_valid():
            form.save()
            messages.success(request, 'Dados atualizados.')
            return redirect('conta')
    else:
        form = PerfilForm(instance=request.user)
    return render(request, 'documentos/conta.html', {'form': form})


def pendentes_status(request):
    total = _documentos_da_empresa(request).filter(
        status__in=['aguardando', 'processando']).count()
    return JsonResponse({'total': total})


def historico(request):
    docs = _documentos_da_empresa(request).filter(status__in=['concluido', 'erro'])
    placa = normaliza_placa(request.GET.get('placa', ''))
    if placa:
        docs = docs.filter(placa__startswith=placa)
    return render(request, 'documentos/historico.html', {
        'documentos': docs[:200], 'placa': placa,
    })


def em_processamento(request):
    docs = list(_documentos_da_empresa(request).filter(
        status__in=['aguardando', 'processando']).order_by('enviado_em'))
    aguardando = sum(1 for d in docs if d.status == 'aguardando')
    processando = len(docs) - aguardando
    resumo = {'aguardando': aguardando, 'processando': processando, 'total': len(docs)}
    return render(request, 'documentos/em_processamento.html', {
        'documentos': docs, 'resumo': resumo,
    })


def em_processamento_status(request):
    docs = _documentos_da_empresa(request).filter(status__in=['aguardando', 'processando'])
    resumo = {
        'aguardando': docs.filter(status='aguardando').count(),
        'processando': docs.filter(status='processando').count(),
        'concluido': 0,
        'erro': 0,
    }
    return JsonResponse({'resumo': resumo})


def detalhe(request, pk):
    doc = get_object_or_404(_documentos_da_empresa(request), pk=pk)
    duplicata = None
    if doc.status == 'concluido' and doc.placa:
        duplicata = (_documentos_da_empresa(request)
                     .filter(placa=doc.placa, status='concluido')
                     .exclude(pk=doc.pk).order_by('-enviado_em').first())
    return render(request, 'documentos/detalhe.html', {
        'documento': doc,
        'campos': campos_para_exibir(doc.resultado),
        'duplicata': duplicata,
    })


def reprocessar(request, pk):
    doc = get_object_or_404(_documentos_da_empresa(request), pk=pk)
    if request.method == 'POST':
        if doc.status not in {'erro', 'concluido'}:
            messages.warning(request, 'Este documento já está na fila.')
        else:
            doc.status = 'aguardando'
            doc.erro = ''
            doc.tentativas = 0
            doc.processamento_iniciado_em = None
            doc.processamento_finalizado_em = None
            doc.save()
            messages.success(request, 'Documento enviado novamente para a fila.')
    return redirect('detalhe', pk=doc.pk)


def excluir(request, pk):
    doc = get_object_or_404(_documentos_da_empresa(request), pk=pk)
    if request.method == 'POST':
        doc.delete()
        messages.success(request, 'Documento excluído.')
        return redirect('historico')
    return redirect('detalhe', pk=doc.pk)


def arquivo(request, pk):
    doc = get_object_or_404(_documentos_da_empresa(request), pk=pk)
    resposta = FileResponse(doc.arquivo.open('rb'), content_type='application/pdf')
    resposta['Content-Disposition'] = content_disposition_header(
        as_attachment=False, filename=doc.nome_arquivo)
    resposta['X-Content-Type-Options'] = 'nosniff'
    return resposta


def documento_status(request, pk):
    doc = get_object_or_404(_documentos_da_empresa(request), pk=pk)
    return JsonResponse({
        'status': doc.status,
        'status_label': doc.get_status_display(),
        'finalizado': doc.status in {'concluido', 'erro'},
    })


def lotes(request):
    lista = Lote.objects.filter(empresa=_empresa_atual(request)).prefetch_related(
        'itens__documento')[:100]
    return render(request, 'documentos/lotes.html', {'lotes': lista})


def lote_detalhe(request, pk):
    lote = get_object_or_404(
        Lote.objects.filter(empresa=_empresa_atual(request)).prefetch_related(
            'itens__documento'), pk=pk)
    return render(request, 'documentos/lote_detalhe.html', {
        'lote': lote,
        'resumo': lote.resumo(),
    })


def lote_status(request, pk):
    lote = get_object_or_404(
        Lote.objects.filter(empresa=_empresa_atual(request)).prefetch_related(
            'itens__documento'), pk=pk)
    resumo = lote.resumo()
    itens = [{
        'id': item.documento_id,
        'status': item.documento.status,
        'status_label': item.documento.get_status_display(),
    } for item in lote.itens.all()]
    return JsonResponse({'resumo': resumo, 'itens': itens, 'agora': timezone.now()})
