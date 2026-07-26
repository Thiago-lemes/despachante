# Comparativo de tecnologias para leitura de placa em PDFs de despachante

**Data:** 29/06/2026
**Amostra:** 2 PDFs digitalizados do DETRAN-PR (`007304018938.pdf`, `337305126920_002.pdf`)
**Gabarito:** `TBF2G31` (Honda CG 160) e `MIN5H43` (Kia Cerato) — ambos formato Mercosul.

Os dois arquivos são **PDFs de imagem** (sem camada de texto, sem fontes embutidas), então toda leitura depende de OCR sobre a imagem renderizada.

---

## As 3 tecnologias testadas

| # | Tecnologia | O que é | Custo | Onde roda |
|---|------------|---------|-------|-----------|
| T1 | **Tesseract puro** | Motor OCR open-source (LSTM), página inteira | Grátis | Local/offline |
| T2 | **OpenCV + Tesseract** | Visão computacional clássica (recorte, upscale, binarização) antes do OCR | Grátis | Local/offline |
| T3 | **Visão multimodal (IA generativa)** | Modelo de visão lê a imagem entendendo o contexto do formato | Pago por imagem | Nuvem/API |

> Observação: EasyOCR e PaddleOCR (OCR por deep learning) não puderam ser testados no ambiente por falta de acesso a repositório de pacotes. Em produção entram na mesma "família" do T3 quanto a robustez, com custo/infra intermediários.

---

## Resultados

Duas situações distintas apareceram nos próprios documentos:

**a) Páginas de formulário "Solicitação de Serviços" (impressão gerada digitalmente, nítida):**

| Documento | Gabarito | T1 | T2 | T3 |
|-----------|----------|----|----|----|
| PDF 1 — Solicitação | TBF2G31 | ✅ TBF2G31 | ✅ | ✅ |
| PDF 2 — Solicitação | MIN5H43 | ✅ MIN5H43 | ✅ | ✅ |

**b) Páginas de CRLV/CRV escaneadas ou fotografadas (ruído, fundo de segurança, baixo contraste):**

| Documento | Gabarito | T1 | T2 | T3 |
|-----------|----------|----|----|----|
| PDF 2 — CRV escaneado | MIN5H43 | ❌ `BHS3C11` (placa errada) | ⚠️ `MINSH43` (lê 5 como S → inválida) | ✅ MIN5H43 |

### Leitura dos resultados
- **T1 Tesseract puro** resolve muito bem o que é **impresso e limpo**, mas na imagem ruidosa devolveu uma **placa errada com aparência válida** (`BHS3C11`) — o pior tipo de erro, porque passa despercebido.
- **T2 OpenCV+Tesseract** localiza melhor o campo e chega perto (`MINSH43`), mas erra confusões clássicas de caractere (**5↔S, 0↔O, 1↔I, 8↔B**) quando o whitelist remove o contexto. A validação Mercosul barra o resultado, evitando o falso-positivo, mas **não entrega** a placa.
- **T3 Visão** lê **MIN5H43** correto inclusive no scan, porque entende o **padrão da placa** e desambigua 5 de S pelo contexto.

---

## Conclusão — por onde seguir

Nenhuma tecnologia isolada é a melhor em custo **e** acurácia. O caminho recomendado é um **pipeline híbrido em cascata**:

1. **Renderizar e rodar Tesseract na região estruturada.** Nos dois fluxos do DETRAN-PR existe a folha "Solicitação de Serviços" com o campo `Placa:` em texto impresso limpo — o Tesseract acerta 100% ali, de graça e offline. É a fonte primária.
2. **Validar sempre** a placa lida contra os padrões brasileiros (Mercosul `ABC1D23` e antigo `ABC1234`) e cruzar com Renavam/chassi. Isso elimina o falso-positivo do tipo `BHS3C11`.
3. **Escalar só os casos duvidosos para a Visão (T3).** Se a placa não validar, ou tiver caractere ambíguo (5/S, 0/O, 1/I, 8/B, 2/Z), manda **apenas aquele recorte** para um modelo de visão / OCR em nuvem. Como a maioria resolve na etapa 1, o custo por imagem incide em poucos casos.

**Resumo da recomendação:** Tesseract como motor base (cobre o volume, custo zero) + validação por regex/cruzamento + Visão como "segunda opinião" sob demanda. Isso entrega **alta acurácia com custo baixo** e elimina o risco de placa errada silenciosa.

O script `leitor_placa.py` já implementa as etapas 1–2 e tem um gancho (`vision_ocr`) pronto para plugar a etapa 3 (API de visão/OCR em nuvem) quando vocês escolherem o provedor.

### Próximos passos sugeridos
- Instalar o pacote de idioma português do Tesseract (`tesseract-ocr-por`) para melhorar o OCR dos demais campos (a placa não depende disso, mas nomes/endereços sim).
- Definir o provedor da etapa 3 (ex.: API de visão multimodal, Google Vision ou AWS Textract) e medir custo real por documento no volume de vocês.
- Validar em uma amostra maior (20–50 PDFs) para estimar a taxa de escalonamento e o custo mensal.
