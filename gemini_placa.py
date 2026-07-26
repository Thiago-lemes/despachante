#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_placa.py — Lê placa e dados de PDFs de despachante usando a API do Gemini (visão).

É o "Teste 3 / etapa de visão" do comparativo, agora com um provedor real (Google Gemini).
Roda NA SUA MÁQUINA (precisa de internet). O sandbox do Cowork não tem saída de rede,
por isso este teste não pôde ser executado lá.

Uso:
    set GEMINI_API_KEY=sua_chave            (Windows)   |   export GEMINI_API_KEY=...  (Linux/Mac)
    python gemini_placa.py 007304018938.pdf 337305126920_002.pdf

Opções:
    --model gemini-2.0-flash    modelo (padrão: gemini-2.0-flash; alternativa: gemini-1.5-flash)
    --dpi 300                   resolução de render
    --max-pages 2               nº de páginas enviadas por PDF (a folha "Solicitação" basta)
    --json saida.json           salva o resultado

Dependências (instale no seu ambiente):
    pip install pymupdf requests          (poppler/pdftoppm também serve no lugar do pymupdf)

SEGURANÇA: nunca cole a chave dentro do código nem a compartilhe em chat. Use variável de
ambiente e rotacione a chave se ela vazar.
"""

import os, re, io, sys, json, base64, argparse, shutil, subprocess, tempfile
import requests

RE_MERCOSUL = re.compile(r'[A-Z]{3}[0-9][A-Z][0-9]{2}')
RE_ANTIGA   = re.compile(r'[A-Z]{3}[0-9]{4}')

PROMPT = """Você é um leitor de documentos de trânsito brasileiros (DETRAN).
Extraia da imagem os campos abaixo e responda APENAS com um JSON válido, sem texto extra.
Atenção à placa: o formato é Mercosul (ABC1D23) ou antigo (ABC1234). Não confunda
dígitos com letras parecidas (5/S, 0/O, 1/I, 8/B, 2/Z); use o formato para decidir.
Se um campo não aparecer, use null.

Atenção ao processo: no canto superior direito da página 1, acima do terceiro
código de barras (o mais à direita, ao lado da data e da hora), há um texto que
começa com "#" seguido do número do processo, no formato NNN.N.NNNNNNN-N (ex.:
"# 007.3.0401893-8"). Extraia esse número sem o "#". O mesmo número costuma
reaparecer mais abaixo no documento rotulado "Processo:", que pode ser usado
para conferência.

JSON esperado:
{
  "placa": "",
  "processo": "",
  "renavam": "",
  "chassi": "",
  "marca_modelo": "",
  "ano_fabricacao": "",
  "ano_modelo": "",
  "municipio_emplacamento": "",
  "proprietario": "",
  "cpf_cnpj": ""
}"""


def render_paginas(pdf_path, dpi, outdir, max_pages):
    pngs = []
    try:
        import fitz
        doc = fitz.open(pdf_path)
        mtx = fitz.Matrix(dpi/72.0, dpi/72.0)
        for i, page in enumerate(doc):
            if i >= max_pages:
                break
            out = os.path.join(outdir, f'pg-{i+1}.png')
            page.get_pixmap(matrix=mtx).save(out)
            pngs.append(out)
        return pngs
    except ImportError:
        pass
    if shutil.which('pdftoppm'):
        subprocess.run(['pdftoppm', '-r', str(dpi), '-png', '-f', '1',
                        '-l', str(max_pages), pdf_path, os.path.join(outdir, 'pg')],
                       check=True)
        return sorted(os.path.join(outdir, f) for f in os.listdir(outdir)
                      if f.endswith('.png'))
    raise RuntimeError("Instale pymupdf ou poppler (pdftoppm).")


def gemini_ocr(img_paths, api_key, model):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    parts = [{"text": PROMPT}]
    for p in img_paths:
        with open(p, 'rb') as f:
            b64 = base64.b64encode(f.read()).decode()
        parts.append({"inline_data": {"mime_type": "image/png", "data": b64}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"temperature": 0, "response_mime_type": "application/json"}}
    r = requests.post(url, json=body, timeout=300)
    r.raise_for_status()
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    return json.loads(txt)


def valida_placa(p):
    p = re.sub(r'[^A-Z0-9]', '', (p or '').upper())
    return bool(RE_MERCOSUL.fullmatch(p) or RE_ANTIGA.fullmatch(p)), p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdfs', nargs='+')
    ap.add_argument('--model', default='gemini-2.5-flash')
    ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--max-pages', type=int, default=2)
    ap.add_argument('--json')
    args = ap.parse_args()

    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        sys.exit("Defina a variável de ambiente GEMINI_API_KEY com sua chave.")

    saida = []
    for pdf in args.pdfs:
        if not os.path.isfile(pdf):
            print(f"[!] não encontrado: {pdf}"); continue
        with tempfile.TemporaryDirectory() as tmp:
            pngs = render_paginas(pdf, args.dpi, tmp, args.max_pages)
            try:
                dados = gemini_ocr(pngs, key, args.model)
            except Exception as e:
                print(f"[!] erro Gemini em {os.path.basename(pdf)}: {e}"); continue
        ok, placa = valida_placa(dados.get('placa'))
        dados['placa'] = placa
        dados['placa_valida'] = ok
        dados['arquivo'] = os.path.basename(pdf)
        saida.append(dados)
        print(f"{'OK ' if ok else '?? '}{dados['arquivo']:<28} "
              f"placa={placa or '-':<9} renavam={dados.get('renavam','-')}")

    if args.json:
        json.dump(saida, open(args.json, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f"\nJSON salvo em {args.json}")


if __name__ == '__main__':
    main()
