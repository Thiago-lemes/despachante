"""O que o cliente anexou à mensagem.

Vocabulário compartilhado: o webhook classifica o que chegou do WAHA e o bot
decide o que fazer com aquilo. Mora fora dos dois porque `waha_webhook` já
importa o bot — pôr as categorias em qualquer um deles fecharia um ciclo.

Tratar tudo como um booleano "tem mídia" fazia uma figurinha valer como o
documento pedido: o bot dava o CPF por recebido e seguia para o próximo.
"""

FIGURINHA = 'figurinha'
FOTO = 'foto'
DOCUMENTO = 'documento'
AUDIO = 'audio'
VIDEO = 'video'
LOCALIZACAO = 'localizacao'
CONTATO = 'contato'
OUTRO = 'outro'

# Só estes servem como documento: é foto ou arquivo que dá para ler.
VALEM_COMO_DOCUMENTO = (FOTO, DOCUMENTO)

# Como o anexo aparece no histórico quando vem sem legenda.
# "[arquivo enviado pelo cliente]" para tudo deixava o atendente sem saber se o
# cliente mandou o CPF ou um joinha.
DESCRICAO = {
    FIGURINHA: '[figurinha]',
    FOTO: '[foto]',
    DOCUMENTO: '[documento]',
    AUDIO: '[áudio]',
    VIDEO: '[vídeo]',
    LOCALIZACAO: '[localização]',
    CONTATO: '[contato]',
    OUTRO: '[anexo]',
}

_MIMES_DE_DOCUMENTO = (
    'application/pdf',
    'application/msword',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
)


def classificar(payload: dict):
    """Diz o que veio anexado, ou None quando é mensagem de texto puro."""
    tipo = (payload.get('type') or '').lower()
    mimetype = (payload.get('mimetype') or '').lower()
    dados = payload.get('_data') if isinstance(payload.get('_data'), dict) else {}

    # Figurinha é image/webp e passaria por foto; o sinal explícito vem antes.
    if tipo == 'sticker' or payload.get('isSticker') or dados.get('isSticker'):
        return FIGURINHA
    if mimetype == 'image/webp':
        return FIGURINHA

    if tipo in ('ptt', 'audio', 'voice') or mimetype.startswith('audio/'):
        return AUDIO
    if tipo == 'video' or mimetype.startswith('video/'):
        return VIDEO
    if tipo in ('location', 'livelocation'):
        return LOCALIZACAO
    if tipo in ('vcard', 'contact', 'contact_card', 'multi_vcard'):
        return CONTATO
    if tipo == 'image' or mimetype.startswith('image/'):
        return FOTO
    if tipo == 'document' or mimetype in _MIMES_DE_DOCUMENTO:
        return DOCUMENTO

    # Sobrou algo anexado que não soubemos nomear — melhor tratar como anexo
    # desconhecido do que deixar passar como texto.
    if payload.get('hasMedia') or payload.get('mediaUrl') or payload.get('media'):
        return OUTRO
    if mimetype and not mimetype.startswith('text/'):
        return OUTRO
    return None


def descrever(anexo):
    return DESCRICAO.get(anexo, '[anexo]')


def vale_como_documento(anexo):
    return anexo in VALEM_COMO_DOCUMENTO
