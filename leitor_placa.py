#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
leitor_placa.py — Extrai placa e dados de PDFs de despachante (DETRAN-PR) digitalizados.

Pipeline híbrido recomendado (ver relatório comparativo):
  1) Renderiza as páginas (PyMuPDF; cai para poppler/pdftoppm se não houver PyMuPDF).
  2) OCR com Tesseract e extração por rótulos (Placa:, Renavam:, Chassi:, ...).
  3) Valida a placa contra os padrões brasileiros (Mercosul e antigo).
  4) Se a placa não validar OU houver caracteres ambíguos (5/S, 0/O, 1/I, 8/B, 2/Z),
     marca para ESCALAR a um modelo de visão (callback opcional `vision_ocr`).

Uso:
    python leitor_placa.py arquivo1.pdf arquivo2.pdf
    python leitor_placa.py *.pdf --json saida.json --dpi 300

Dependências mínimas: tesseract-ocr no PATH.
Opcionais (melhoram qualidade): PyMuPDF (fitz), opencv-python, pillow.
"""

import os, re, sys, json, shutil, argparse, subprocess, tempfile

# --------------------------------------------------------------------------- #
# Padrões de placa brasileira
# --------------------------------------------------------------------------- #
RE_MERCOSUL = re.compile(r'[A-Z]{3}[0-9][A-Z][0-9]{2}')   # ABC1D23
RE_ANTIGA   = re.compile(r'[A-Z]{3}[0-9]{4}')             # ABC1234

# Trocas mais comuns que o OCR erra em placas (dígito<->letra parecidos)
AMBIGUOS = {'5': 'S', 'S': '5', '0': 'O', 'O': '0',
            '1': 'I', 'I': '1', '8': 'B', 'B': '8', '2': 'Z', 'Z': '2'}

# Campos do formulário "SOLICITAÇÃO DE SERVIÇOS - VEÍCULO" do DETRAN-PR
CAMPOS = {
    'placa':     r'Placa[:\s]+([A-Z0-9\-\. ]{7,12})',
    'renavam':   r'Renavam[:\s]+([0-9\.\-]{8,14})',
    'chassi':    r'Chassi[:\s]+([A-Z0-9]{11,17})',
    'motor':     r'(?:N[uú]mero\s+Motor|Motor)[:\s]+([A-Z0-9]{6,20})',
    'marca':     r'Marca/Modelo[:\s]+([A-Z0-9/ \.\(\)]{4,40})',
    'ano_fab':   r'Ano\s+Fabrica[cç][aã]o[:\s]+(\d{4})',
    'ano_mod':   r'Ano\s+Modelo[:\s]+(\d{4})',
    'municipio': r'Munic\.?\s*Emplacamento[:\s]+([A-Z ]{3,40})',
    'proprietario_cpf':  r'CPF[:\s]+([0-9\.\-]{11,14})',
    'proprietario_cnpj': r'CNPJ[:\s]+([0-9\.\/\-]{14,18})',
    'processo':  r'#?\s*(\d{3}\.\d\.\d{7}-\d)',
}


def normaliza_placa(s: str) -> str:
    return re.sub(r'[^A-Z0-9]', '', s.upper())


def valida_placa(p: str) -> bool:
    p = normaliza_placa(p)
    return bool(RE_MERCOSUL.fullmatch(p) or RE_ANTIGA.fullmatch(p))


def placa_ambigua(p: str) -> bool:
    """True se a placa não valida mas vira válida ao trocar 1 caractere ambíguo."""
    p = normaliza_placa(p)
    if valida_placa(p):
        return False
    for i, ch in enumerate(p):
        if ch in AMBIGUOS:
            cand = p[:i] + AMBIGUOS[ch] + p[i+1:]
            if valida_placa(cand):
                return True
    return False


# --------------------------------------------------------------------------- #
# Renderização de páginas (PyMuPDF -> fallback poppler)
# --------------------------------------------------------------------------- #
def render_paginas(pdf_path: str, dpi: int, outdir: str):
    pngs = []
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        zoom = dpi / 72.0
        mtx = fitz.Matrix(zoom, zoom)
        for i, page in enumerate(doc):
            out = os.path.join(outdir, f'pg-{i+1}.png')
            page.get_pixmap(matrix=mtx).save(out)
            pngs.append(out)
        return pngs
    except ImportError:
        pass
    # Fallback: poppler
    if shutil.which('pdftoppm'):
        prefix = os.path.join(outdir, 'pg')
        subprocess.run(['pdftoppm', '-r', str(dpi), '-png', pdf_path, prefix],
                       check=True)
        return sorted(
            os.path.join(outdir, f) for f in os.listdir(outdir)
            if f.startswith('pg') and f.endswith('.png')
        )
    raise RuntimeError("Instale PyMuPDF (pip install pymupdf) ou poppler-utils (pdftoppm).")


# --------------------------------------------------------------------------- #
# OCR
# --------------------------------------------------------------------------- #
def ocr(img_path: str, psm: str = '3', whitelist: str = None, lang: str = 'por') -> str:
    cmd = ['tesseract', img_path, '-', '--psm', psm, '-l', lang]
    if whitelist:
        cmd += ['-c', 'tessedit_char_whitelist=' + whitelist]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 and lang != 'eng':       # cai para inglês se 'por' não instalado
        return ocr(img_path, psm, whitelist, 'eng')
    return r.stdout


def extrai_campos(texto: str) -> dict:
    dados = {}
    for nome, pat in CAMPOS.items():
        m = re.search(pat, texto, re.IGNORECASE)
        if m:
            dados[nome] = m.group(1).strip()
    return dados


# --------------------------------------------------------------------------- #
# Processamento de um PDF
# --------------------------------------------------------------------------- #
def processa_pdf(pdf_path: str, dpi: int = 300, lang: str = 'por',
                 vision_ocr=None) -> dict:
    """
    vision_ocr: callback opcional (img_path:str) -> str.
    Use para escalar recortes ambíguos a um modelo de visão / API de OCR em nuvem.
    """
    resultado = {'arquivo': os.path.basename(pdf_path), 'placa': None,
                 'placa_valida': False, 'confianca': 'baixa', 'campos': {},
                 'escalar_visao': False, 'paginas': 0}
    with tempfile.TemporaryDirectory() as tmp:
        pngs = render_paginas(pdf_path, dpi, tmp)
        resultado['paginas'] = len(pngs)

        # OCR de todas as páginas; consolida o melhor conjunto de campos
        texto_total, campos = '', {}
        for png in pngs:
            t = ocr(png, '3', lang=lang)
            texto_total += '\n' + t
            for k, v in extrai_campos(t).items():
                campos.setdefault(k, v)        # mantém a primeira ocorrência
        resultado['campos'] = campos

        # 1) Placa via rótulo "Placa:"
        cand = normaliza_placa(campos.get('placa', ''))[:7] if campos.get('placa') else ''
        # 2) Se não validar, varre o texto por qualquer padrão de placa
        if not valida_placa(cand):
            achados = [normaliza_placa(x) for x in
                       RE_MERCOSUL.findall(normaliza_placa(texto_total)) +
                       RE_ANTIGA.findall(normaliza_placa(texto_total))]
            for a in achados:
                if valida_placa(a):
                    cand = a
                    break
            else:
                cand = cand or (achados[0] if achados else '')

        resultado['placa'] = cand or None
        resultado['placa_valida'] = valida_placa(cand)

        # Decide confiança e necessidade de escalar
        if resultado['placa_valida']:
            resultado['confianca'] = 'alta'
        elif placa_ambigua(cand):
            resultado['confianca'] = 'media'
            resultado['escalar_visao'] = True
        else:
            resultado['confianca'] = 'baixa'
            resultado['escalar_visao'] = True

        # 3) Escalonamento opcional para visão (recorte da página inteira como fallback)
        if resultado['escalar_visao'] and vision_ocr:
            try:
                visto = normaliza_placa(vision_ocr(pngs[0]))
                m = RE_MERCOSUL.search(visto) or RE_ANTIGA.search(visto)
                if m:
                    resultado['placa'] = m.group(0)
                    resultado['placa_valida'] = True
                    resultado['confianca'] = 'alta (visão)'
                    resultado['escalar_visao'] = False
            except Exception as e:
                resultado['erro_visao'] = str(e)

    return resultado


def main():
    ap = argparse.ArgumentParser(description="Leitor de placa em PDFs de despachante.")
    ap.add_argument('pdfs', nargs='+', help="Um ou mais arquivos PDF.")
    ap.add_argument('--dpi', type=int, default=300)
    ap.add_argument('--lang', default='por', help="Idioma do Tesseract (por|eng).")
    ap.add_argument('--json', help="Salva o resultado consolidado em JSON.")
    args = ap.parse_args()

    saida = []
    for pdf in args.pdfs:
        if not os.path.isfile(pdf):
            print(f"[!] não encontrado: {pdf}"); continue
        r = processa_pdf(pdf, dpi=args.dpi, lang=args.lang)
        saida.append(r)
        flag = 'OK ' if r['placa_valida'] else ('?? ' if r['escalar_visao'] else '   ')
        print(f"{flag}{r['arquivo']:<28} placa={r['placa'] or '-':<9} "
              f"conf={r['confianca']:<12} "
              f"renavam={r['campos'].get('renavam','-')}")
        if r['escalar_visao']:
            print(f"     -> revisar manualmente ou escalar p/ visão (placa lida pode estar errada)")

    if args.json:
        json.dump(saida, open(args.json, 'w', encoding='utf-8'),
                  ensure_ascii=False, indent=2)
        print(f"\nJSON salvo em {args.json}")


if __name__ == '__main__':
    main()
