"""Processamento dos PDFs pelos pipelines Gemini e OpenAI (visao multimodal)."""

import base64
import json
import re
import sys
import tempfile
import time
from pathlib import Path

import requests
from django.conf import settings
from django.utils import timezone

DESPACHANTE_DIR = Path(__file__).resolve().parent.parent.parent
if str(DESPACHANTE_DIR) not in sys.path:
    sys.path.insert(0, str(DESPACHANTE_DIR))

import gemini_placa  # noqa: E402


PROMPT_OPENAI = """Voce e um leitor de documentos de transito brasileiros (DETRAN).
Extraia das imagens os campos abaixo e responda somente com um objeto JSON valido,
sem texto extra. Atencao a placa: o formato e Mercosul (ABC1D23) ou antigo (ABC1234).
Nao confunda digitos com letras parecidas (5/S, 0/O, 1/I, 8/B, 2/Z); use o formato
para decidir. Use null quando um campo nao estiver presente. Nao invente valores.

Atencao ao processo: no canto superior direito da pagina 1, acima do terceiro
codigo de barras (o mais a direita, ao lado da data e da hora), ha um texto que
comeca com "#" seguido do numero do processo, no formato NNN.N.NNNNNNN-N (ex.:
"# 007.3.0401893-8"). Extraia esse numero sem o "#". O mesmo numero costuma
reaparecer mais abaixo no documento rotulado "Processo:", que pode ser usado
para conferencia.

Formato JSON:
{
  "placa": null,
  "processo": null,
  "renavam": null,
  "chassi": null,
  "marca_modelo": null,
  "ano_fabricacao": null,
  "ano_modelo": null,
  "municipio_emplacamento": null,
  "proprietario": null,
  "cpf_cnpj": null
}
"""


def _renderizar(documento, pasta, max_pages=2, dpi=300):
    return gemini_placa.render_paginas(
        documento.arquivo.path, dpi, pasta, max_pages)


def _openai_extrair(caminhos):
    if not settings.OPENAI_API_KEY:
        raise RuntimeError('OPENAI_API_KEY nao configurada.')
    conteudo = [{'type': 'text', 'text': PROMPT_OPENAI}]
    for caminho in caminhos:
        b64 = base64.b64encode(Path(caminho).read_bytes()).decode()
        conteudo.append({
            'type': 'image_url',
            'image_url': {'url': f'data:image/png;base64,{b64}'},
        })
    resposta = requests.post(
        'https://api.openai.com/v1/chat/completions',
        headers={
            'Authorization': f'Bearer {settings.OPENAI_API_KEY}',
            'Content-Type': 'application/json',
        },
        json={
            'model': settings.OPENAI_MODEL,
            'messages': [{'role': 'user', 'content': conteudo}],
            'response_format': {'type': 'json_object'},
            'temperature': 0,
            'max_tokens': 1200,
        },
        timeout=300,
    )
    resposta.raise_for_status()
    texto = resposta.json()['choices'][0]['message']['content']
    dados = json.loads(texto)
    if not isinstance(dados, dict):
        raise ValueError('A OpenAI nao retornou um objeto JSON.')
    return dados


def _gemini_extrair(caminhos):
    if not settings.GEMINI_API_KEY:
        raise RuntimeError('GEMINI_API_KEY nao configurada.')
    return gemini_placa.gemini_ocr(
        caminhos, settings.GEMINI_API_KEY, settings.GEMINI_MODEL)


def _normalizar_resultado(documento, dados):
    ok, placa = gemini_placa.valida_placa(dados.get('placa'))
    dados['placa'] = placa
    dados['placa_valida'] = ok
    documento.resultado = dados
    documento.placa = placa
    documento.placa_valida = ok
    documento.processo = str(dados.get('processo') or '')[:20]
    documento.renavam = str(dados.get('renavam') or '')[:14]
    documento.proprietario = str(dados.get('proprietario') or '')[:120]


def _motivo_publico(erro):
    mensagem = str(erro).strip() or erro.__class__.__name__
    mensagem = re.sub(r'(?i)(api[_ -]?key[=:\s]+)\S+', r'\1[oculta]', mensagem)
    return mensagem[:1000]


def processar(documento, max_pages=2, dpi=300):
    """Processa um documento ja reivindicado pelo worker."""
    documento.erro = ''
    documento.usou_fallback = False
    documento.motivo_fallback = ''
    try:
        with tempfile.TemporaryDirectory() as tmp:
            imagens = _renderizar(documento, tmp, max_pages=max_pages, dpi=dpi)
            if not imagens:
                raise RuntimeError('O PDF nao possui paginas renderizaveis.')

            if documento.pipeline == 'openai':
                try:
                    ultimo_erro = None
                    for tentativa in range(3):
                        try:
                            dados = _openai_extrair(imagens)
                            break
                        except (requests.RequestException, ValueError, KeyError) as erro:
                            ultimo_erro = erro
                            if tentativa < 2:
                                time.sleep(2 ** tentativa)
                    else:
                        raise ultimo_erro
                    documento.provedor_utilizado = 'OpenAI'
                    documento.modelo_utilizado = settings.OPENAI_MODEL
                except Exception as erro_openai:
                    documento.usou_fallback = True
                    documento.motivo_fallback = _motivo_publico(erro_openai)
                    dados = _gemini_extrair(imagens)
                    documento.provedor_utilizado = 'Gemini'
                    documento.modelo_utilizado = settings.GEMINI_MODEL
            else:
                dados = _gemini_extrair(imagens)
                documento.provedor_utilizado = 'Gemini'
                documento.modelo_utilizado = settings.GEMINI_MODEL

        _normalizar_resultado(documento, dados)
        documento.status = 'concluido'
    except Exception as erro:
        documento.status = 'erro'
        documento.erro = _motivo_publico(erro)
    documento.processamento_finalizado_em = timezone.now()
    documento.save()
    return documento


CAMPOS_EXIBICAO = [
    ('processo', 'Processo'),
    ('placa', 'Placa'),
    ('renavam', 'Renavam'),
    ('chassi', 'Chassi'),
    ('marca_modelo', 'Marca/Modelo'),
    ('ano_fabricacao', 'Ano fabricacao'),
    ('ano_modelo', 'Ano modelo'),
    ('municipio_emplacamento', 'Municipio de emplacamento'),
    ('proprietario', 'Proprietario'),
    ('cpf_cnpj', 'CPF/CNPJ'),
]


def campos_para_exibir(resultado):
    if not resultado:
        return []
    vistos = {'placa_valida'}
    linhas = []
    for chave, rotulo in CAMPOS_EXIBICAO:
        vistos.add(chave)
        linhas.append((rotulo, resultado.get(chave) or '-'))
    for chave, valor in resultado.items():
        if chave not in vistos and not isinstance(valor, (dict, list)):
            linhas.append((chave.replace('_', ' ').capitalize(), valor or '-'))
    return linhas
