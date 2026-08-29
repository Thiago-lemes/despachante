"""Extração de dados de PDFs recebidos no atendimento (fase 8)."""

import json
import sys
import tempfile
from pathlib import Path

from django.conf import settings

DESPACHANTE_DIR = Path(__file__).resolve().parent.parent.parent.parent
if str(DESPACHANTE_DIR) not in sys.path:
    sys.path.insert(0, str(DESPACHANTE_DIR))

import gemini_placa  # noqa: E402

from documentos.services import _gemini_extrair, _openai_extrair  # noqa: E402


def extrair_dados_pdf(caminho_arquivo, *, pipeline='gemini', max_pages=2, dpi=300):
    """Extrai campos de um PDF usando o mesmo pipeline dos documentos de trânsito."""
    with tempfile.TemporaryDirectory() as tmp:
        imagens = gemini_placa.render_paginas(caminho_arquivo, dpi, tmp, max_pages)
        if not imagens:
            raise RuntimeError('O PDF não possui páginas renderizáveis.')

        if pipeline == 'openai':
            try:
                dados = _openai_extrair(imagens)
                dados['_provedor'] = 'OpenAI'
                dados['_modelo'] = settings.OPENAI_MODEL
            except Exception:
                dados = _gemini_extrair(imagens)
                dados['_provedor'] = 'Gemini'
                dados['_modelo'] = settings.GEMINI_MODEL
                dados['_fallback'] = True
        else:
            dados = _gemini_extrair(imagens)
            dados['_provedor'] = 'Gemini'
            dados['_modelo'] = settings.GEMINI_MODEL

    ok, placa = gemini_placa.valida_placa(dados.get('placa'))
    dados['placa'] = placa
    dados['placa_valida'] = ok
    return dados
