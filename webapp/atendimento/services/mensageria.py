"""Envio de mensagem ao cliente pelo WhatsApp.

Um lugar só sabe escolher a sessão WAHA, resolver o endereço de destino e
registrar a saída no histórico. O bot e o atendente passam os dois por aqui —
manter duas cópias disso foi o defeito D da spec do chatbot, e o endereço
errado (`wa_id` no lugar de `chat_id`) foi o defeito B.
"""
import logging

from atendimento.models import Mensagem, nome_curto
from integracao.models import WahaSessao
from integracao.services.conversas import registrar_mensagem_saida
from integracao.services.waha_client import enviar_texto

logger = logging.getLogger(__name__)


def enviar_mensagem(conversa, texto, *, origem, autor=None, ator):
    """Manda o texto ao cliente e registra a saída. Devolve True se saiu."""
    sessao = WahaSessao.objects.filter(
        empresa=conversa.empresa, ativa=True).first()
    if not sessao:
        logger.error('Nenhuma sessão WAHA ativa para a empresa %s',
                     conversa.empresa_id)
        return False

    # chat_id, nunca wa_id: para contato novo do WhatsApp o wa_id é um LID, e
    # remontar o endereço a partir dele manda a mensagem para lugar nenhum.
    destino = conversa.contato.chat_id or conversa.contato.wa_id
    resultado = enviar_texto(
        sessao=sessao.nome_sessao, chat_id=destino, texto=texto)
    if not resultado['success']:
        logger.error('Falha ao enviar mensagem: %s', resultado.get('error'))
        return False

    registrar_mensagem_saida(
        conversa.empresa, conversa, texto, ator=ator, origem=origem, autor=autor,
        wa_message_id=str((resultado.get('data') or {}).get('id', '')),
    )
    return True


def assinar(usuario, texto):
    """Prefixa o nome de quem está falando.

    O cliente vê tudo chegando do mesmo número da empresa; sem o nome, ele não
    tem como saber que trocou de interlocutor no meio do atendimento.
    """
    return f'*{nome_curto(usuario)}:*\n{texto}'


def enviar_do_atendente(conversa, usuario, texto):
    return enviar_mensagem(
        conversa, assinar(usuario, texto),
        origem=Mensagem.Origem.ATENDENTE, autor=usuario, ator=usuario.username)


def anunciar_atendente(conversa, usuario, *, transferencia=False):
    """Avisa o cliente de quem passou a atendê-lo."""
    nome = nome_curto(usuario)
    texto = (f'O seu atendimento passou para *{nome}*, que continua daqui.'
             if transferencia else
             f'Olá! Sou {nome} e vou cuidar do seu atendimento a partir de agora.')
    return enviar_mensagem(
        conversa, texto,
        origem=Mensagem.Origem.ATENDENTE, autor=usuario, ator=usuario.username)
