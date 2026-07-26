#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gemini_extrai_tudo.py — Extração COMPLETA de PDFs de despachante via Gemini (visão).

Diferente do gemini_placa.py (que pede só os campos-chave das 2 primeiras páginas),
este envia TODAS as páginas, uma requisição por página, e pede ao modelo:
  - o tipo do documento da página (Solicitação, CRLV, CRV, ATPV, procuração, RG/CNH...)
  - TODOS os pares rótulo/valor legíveis
  - a transcrição integral do texto

Uso:
    export GEMINI_API_KEY=...
    python gemini_extrai_tudo.py 007304018938.pdf 337305126920_002.pdf --json saida.json

Opções:
    --model gemini-2.0-flash   --dpi 200   --max-pages 0 (0 = todas)
"""

import os, re, sys, json, base64, argparse, tempfile, time

import requests

RE_MERCOSUL = re.compile(r'[A-Z]{3}[0-9][A-Z][0-9]{2}')
RE_ANTIGA   = re.compile(r'[A-Z]{3}[0-9]{4}')

PROMPT = """Você é um leitor de documentos de trânsito brasileiros (DETRAN, despachante).
Analise a imagem desta página e responda APENAS com um JSON válido, sem texto extra:

{
  "tipo_documento": "identifique: Solicitação de Serviços, CRLV, CRV/ATPV, procuração, \
comprovante, RG, CNH, contrato, ou outro (descreva)",
  "campos": { "rotulo legível": "valor legível", "...": "..." },
  "texto_completo": "transcrição integral de todo o texto legível da página",
  "observacoes": "carimbos, assinaturas, trechos ilegíveis, qualidade da imagem"
}

Em "campos" inclua TODOS os pares rótulo/valor que conseguir ler (placa, renavam, chassi,
motor, marca/modelo, anos, cor, combustível, categoria, município, proprietário, CPF/CNPJ,
endereço, datas, números de processo/protocolo, valores, taxas etc.).
Atenção a placas: formato Mercosul (ABC1D23) ou antigo (ABC1234); não confunda
5/S, 0/O, 1/I, 8/B, 2/Z — use o formato para decidir. O que não conseguir ler, omita."""


def render_paginas(pdf_path, dpi, max_pages):
    """Renderiza páginas em JPEG (menor que PNG p/ upload). Retorna lista de bytes."""
    import fitz
    doc = fitz.open(pdf_path)
    mtx = fitz.Matrix(dpi / 72.0, dpi / 72.0)
    imgs = []
    for i, page in enumerate(doc):
        if max_pages and i >= max_pages:
            break
        pix = page.get_pixmap(matrix=mtx)
        imgs.append(pix.tobytes('jpeg'))
    return imgs


def gemini_pagina(img_bytes, api_key, model, tentativas=3):
    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{model}:generateContent?key={api_key}")
    body = {
        "contents": [{"parts": [
            {"text": PROMPT},
            {"inline_data": {"mime_type": "image/jpeg",
                             "data": base64.b64encode(img_bytes).decode()}},
        ]}],
        "generationConfig": {"temperature": 0, "response_mime_type": "application/json"},
    }
    for t in range(tentativas):
        r = requests.post(url, json=body, timeout=120)
        if r.status_code == 429 and t < tentativas - 1:
            time.sleep(15 * (t + 1))          # rate limit do tier gratuito
            continue
        r.raise_for_status()
        txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
        return json.loads(txt)
    raise RuntimeError("rate limit persistente")


def acha_placas(obj):
    """Varre o JSON da página atrás de qualquer placa em formato válido."""
    achadas = set()
    def walk(v):
        if isinstance(v, dict):
            for x in v.values(): walk(x)
        elif isinstance(v, list):
            for x in v: walk(x)
        elif isinstance(v, str):
            s = re.sub(r'[^A-Z0-9]', '', v.upper())
            achadas.update(RE_MERCOSUL.findall(s))
    walk(obj)
    return sorted(achadas)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('pdfs', nargs='+')
    ap.add_argument('--model', default='gemini-2.5-flash')
    ap.add_argument('--dpi', type=int, default=200)
    ap.add_argument('--max-pages', type=int, default=0, help="0 = todas")
    ap.add_argument('--json')
    args = ap.parse_args()

    key = os.environ.get('GEMINI_API_KEY')
    if not key:
        sys.exit("Defina a variável de ambiente GEMINI_API_KEY.")

    saida = []
    for pdf in args.pdfs:
        if not os.path.isfile(pdf):
            print(f"[!] não encontrado: {pdf}"); continue
        print(f"\n=== {os.path.basename(pdf)} ===")
        imgs = render_paginas(pdf, args.dpi, args.max_pages)
        doc = {'arquivo': os.path.basename(pdf), 'paginas': []}
        for n, img in enumerate(imgs, 1):
            try:
                dados = gemini_pagina(img, key, args.model)
            except Exception as e:
                print(f"  pg {n}: ERRO {e}")
                doc['paginas'].append({'pagina': n, 'erro': str(e)})
                continue
            dados['pagina'] = n
            doc['paginas'].append(dados)
            print(f"  pg {n}: {dados.get('tipo_documento','?')} "
                  f"({len(dados.get('campos') or {})} campos)")
        doc['placas_encontradas'] = acha_placas(doc)
        saida.append(doc)
        print(f"  placas válidas no documento: {doc['placas_encontradas'] or '-'}")

    if args.json:
        json.dump(saida, open(args.json, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f"\nJSON salvo em {args.json}")


if __name__ == '__main__':
    main()
