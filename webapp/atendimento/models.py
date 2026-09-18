import re
import uuid
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.conf import settings


class Contato(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='contatos')
    # Identificador do WhatsApp: pode ser o telefone ou um LID (contas novas),
    # por isso o número em si fica no campo 'telefone' quando o WAHA o informa.
    wa_id = models.CharField(max_length=20)
    # Endereço de chat completo informado pelo WAHA ('...@c.us' ou '...@lid').
    # É o destino real de envio: remontá-lo a partir do wa_id levaria um LID
    # para '@c.us', que é um endereço inexistente.
    chat_id = models.CharField(max_length=64, blank=True)
    telefone = models.CharField(max_length=20, blank=True)
    nome = models.CharField(max_length=255, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['empresa', 'wa_id'], name='contato_empresa_wa_id_unico'),
        ]

    @property
    def telefone_exibicao(self):
        """Telefone em formato legível: +55 (41) 99857-7211."""
        numero = ''.join(filter(str.isdigit, self.telefone or ''))
        if not numero:
            return ''
        if numero.startswith('55') and len(numero) in (12, 13):
            ddd, resto = numero[2:4], numero[4:]
            return f'+55 ({ddd}) {resto[:-4]}-{resto[-4:]}'
        if len(numero) in (10, 11):
            ddd, resto = numero[:2], numero[2:]
            return f'({ddd}) {resto[:-4]}-{resto[-4:]}'
        return f'+{numero}'

    @property
    def nome_exibicao(self):
        return self.nome or self.telefone_exibicao or 'Contato sem nome'

    def __str__(self):
        return f"{self.nome or 'Sem nome'} ({self.wa_id})"


class Servico(models.Model):
    """Uma opção do menu do WhatsApp.

    Uma opção pode ter sub-opções ("Transferência" → "Carro", "Moto"), em
    quantos níveis forem necessários. Só a opção-folha — a que não tem
    sub-opções ativas — pede documentos e faz nascer o card no Kanban; as
    intermediárias existem para ramificar a conversa.
    """

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='servicos')
    pai = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.CASCADE, related_name='subopcoes',
        help_text='Opção da qual esta é uma sub-opção. Vazio = opção do menu principal.')
    nome = models.CharField(max_length=255)
    descricao = models.TextField(blank=True)
    # Enviada assim que o cliente escolhe esta opção: numa opção-folha é o recado
    # antes de pedir documentos ("separe os documentos"); numa opção com
    # sub-opções é a pergunta que abre o submenu ("Transferência de quê?").
    mensagem_apos_escolha = models.TextField(blank=True)
    ativo = models.BooleanField(default=True)
    # Posição no menu do WhatsApp, entre as opções de mesmo pai. Empatados,
    # desempata pelo nome — foi assim que o menu se comportou antes de existir
    # ordem, e serviços novos entram com 0 sem embaralhar o que já estava.
    ordem = models.PositiveSmallIntegerField(default=0)
    criado_em = models.DateTimeField(auto_now_add=True)

    PERGUNTA_PADRAO = 'Escolha uma opção:'

    class Meta:
        ordering = ['ordem', 'nome']
        constraints = [
            # Em SQL, NULL != NULL: uma constraint única sobre ('empresa', 'pai',
            # 'nome') deixaria passar dois nomes iguais no menu principal. Daí as
            # duas, separadas pela condição.
            models.UniqueConstraint(
                fields=['empresa', 'nome'], condition=models.Q(pai__isnull=True),
                name='servico_empresa_nome_unico'),
            models.UniqueConstraint(
                fields=['empresa', 'pai', 'nome'], condition=models.Q(pai__isnull=False),
                name='servico_empresa_pai_nome_unico'),
        ]

    def __str__(self):
        return self.nome

    def subopcoes_do_menu(self):
        return list(self.subopcoes.filter(ativo=True).order_by('ordem', 'nome'))

    def e_folha(self):
        """Opção que conclui o pedido: sem sub-opção ativa para onde ramificar."""
        return not self.subopcoes.filter(ativo=True).exists()

    def ancestrais(self):
        """Do menu principal até o pai desta opção.

        O conjunto de visitados é uma guarda contra ciclo: um `pai` apontando
        para um descendente faria este laço rodar para sempre.
        """
        caminho, atual, vistos = [], self.pai, {self.pk}
        while atual is not None and atual.pk not in vistos:
            caminho.append(atual)
            vistos.add(atual.pk)
            atual = atual.pai
        caminho.reverse()
        return caminho

    def caminho(self, separador=' › '):
        return separador.join([s.nome for s in self.ancestrais()] + [self.nome])

    @property
    def nivel(self):
        return len(self.ancestrais())

    def pergunta_do_submenu(self):
        return self.mensagem_apos_escolha.strip() or self.PERGUNTA_PADRAO


class ConfiguracaoBot(models.Model):
    """Comportamento do chatbot de WhatsApp, por empresa.

    Existe uma linha por empresa, criada sob demanda por `para()`. Os defaults
    reproduzem exatamente os textos que estavam fixos em `services/bot.py`, de
    modo que uma empresa que nunca abrir a tela continua atendendo igual.
    """

    PLACEHOLDER_EMPRESA = '{empresa}'

    SAUDACAO_PADRAO = 'Olá! Sou o assistente virtual da {empresa}.'
    ROTULO_ATENDENTE_PADRAO = 'Falar com um atendente'
    NAO_ENTENDI_PADRAO = 'Não entendi.'
    TRANSFERENCIA_PADRAO = 'Vou chamar um atendente para falar com você por aqui. Só um momento.'
    CONCLUSAO_PADRAO = ('Recebi todos os documentos!\n\n'
                        'Um atendente vai analisar e falar com você por aqui.')
    PALAVRAS_ATENDENTE_PADRAO = 'atendente, humano, pessoa'

    empresa = models.OneToOneField(
        'empresas.Empresa', on_delete=models.CASCADE, related_name='configuracao_bot')
    ativo = models.BooleanField(
        default=True,
        help_text='Desligado, toda mensagem nova vai direto para um atendente.')
    saudacao = models.TextField(
        default=SAUDACAO_PADRAO,
        help_text='Primeira linha do menu. Use {empresa} para o nome da empresa.')
    rotulo_atendente = models.CharField(
        max_length=120, default=ROTULO_ATENDENTE_PADRAO,
        help_text='Texto da última opção do menu, que sempre chama um humano.')
    mensagem_nao_entendi = models.TextField(
        default=NAO_ENTENDI_PADRAO,
        help_text='Vem antes do menu repetido quando a resposta não é uma opção válida.')
    mensagem_transferencia = models.TextField(default=TRANSFERENCIA_PADRAO)
    mensagem_conclusao = models.TextField(
        default=CONCLUSAO_PADRAO,
        help_text='Enviada quando o cliente termina de mandar os documentos.')
    max_tentativas_invalidas = models.PositiveSmallIntegerField(
        default=3, validators=[MinValueValidator(1), MaxValueValidator(10)],
        help_text='Respostas seguidas não entendidas antes de transferir para um atendente.')
    palavras_atendente = models.CharField(
        max_length=255, default=PALAVRAS_ATENDENTE_PADRAO,
        help_text='Separadas por vírgula. Em qualquer etapa, transferem para um atendente.')
    atualizada_em = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'configuração do chatbot'
        verbose_name_plural = 'configurações do chatbot'

    def __str__(self):
        return f'Chatbot de {self.empresa}'

    @classmethod
    def para(cls, empresa):
        """Configuração da empresa, criando-a com os padrões na primeira vez."""
        configuracao, _ = cls.objects.get_or_create(empresa=empresa)
        return configuracao

    def saudacao_formatada(self):
        return self.saudacao.replace(self.PLACEHOLDER_EMPRESA, self.empresa.nome)

    def lista_palavras_atendente(self):
        return [p.strip() for p in (self.palavras_atendente or '').split(',') if p.strip()]

    def regex_atendente(self):
        """Regex das palavras que tiram o cliente do fluxo automático.

        Sem palavras cadastradas devolve None: um regex vazio casaria com tudo
        e transferiria toda mensagem.
        """
        palavras = self.lista_palavras_atendente()
        if not palavras:
            return None
        return re.compile(
            r'\b(' + '|'.join(re.escape(p) for p in palavras) + r')\b', re.IGNORECASE)


class Conversa(models.Model):
    class Estado(models.TextChoices):
        TRIAGEM = 'triagem', 'Triagem'
        COLETANDO_DOCUMENTOS = 'coletando_documentos', 'Coletando documentos'
        AGUARDANDO_ANALISE = 'aguardando_analise', 'Aguardando análise'
        AGUARDANDO_HUMANO = 'aguardando_humano', 'Aguardando humano'
        ENCERRADA = 'encerrada', 'Encerrada'

    class Modo(models.TextChoices):
        BOT = 'bot', 'Bot'
        HUMANO = 'humano', 'Humano'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='conversas')
    contato = models.ForeignKey(Contato, on_delete=models.PROTECT)
    servico = models.ForeignKey(Servico, null=True, blank=True, on_delete=models.SET_NULL)
    estado = models.CharField(max_length=30, choices=Estado.choices, default=Estado.TRIAGEM)
    modo = models.CharField(max_length=10, choices=Modo.choices, default=Modo.BOT)
    # Respostas seguidas que o menu do bot não reconheceu. Zera a cada acerto e,
    # ao estourar o limite, a conversa é transferida para um atendente.
    tentativas_invalidas = models.PositiveSmallIntegerField(default=0)
    criada_em = models.DateTimeField(auto_now_add=True)
    atualizada_em = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Conversa {self.id} — {self.contato} — {self.get_estado_display()}"


class Mensagem(models.Model):
    class Direcao(models.TextChoices):
        ENTRADA = 'entrada', 'Entrada'
        SAIDA = 'saida', 'Saída'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='mensagens')
    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='mensagens')
    direcao = models.CharField(max_length=10, choices=Direcao.choices)
    conteudo = models.TextField()
    wa_message_id = models.CharField(max_length=100, blank=True, db_index=True)
    criada_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.get_direcao_display()}: {self.conteudo[:50]}"


class DocumentoExigido(models.Model):
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='documentos_exigidos')
    servico = models.ForeignKey(Servico, on_delete=models.CASCADE, related_name='documentos_exigidos')
    tipo = models.CharField(max_length=100)
    obrigatorio = models.BooleanField(default=True)
    instrucoes = models.TextField()
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.tipo} ({self.servico.nome})"


class DocumentoRecebido(models.Model):
    class Status(models.TextChoices):
        PENDENTE = 'pendente', 'Pendente'
        APROVADO = 'aprovado', 'Aprovado'
        REPROVADO = 'reprovado', 'Reprovado'

    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='documentos_recebidos')
    conversa = models.ForeignKey(Conversa, on_delete=models.CASCADE, related_name='documentos_recebidos')
    documento_exigido = models.ForeignKey(DocumentoExigido, on_delete=models.PROTECT)
    arquivo = models.FileField(upload_to='atendimento/documentos/', blank=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDENTE)
    motivo_reprovacao = models.TextField(blank=True)
    resultado = models.JSONField(default=dict, blank=True)
    analisado_em = models.DateTimeField(null=True, blank=True)
    erro_analise = models.TextField(blank=True)
    revisado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True,
        on_delete=models.SET_NULL, related_name='documentos_revisados')
    revisado_em = models.DateTimeField(null=True, blank=True)
    criado_em = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.documento_exigido.tipo} — {self.get_status_display()}"


class Tarefa(models.Model):
    class Status(models.TextChoices):
        ABERTA = 'aberta', 'Aberta'
        EM_ATENDIMENTO = 'em_atendimento', 'Em atendimento'
        CONCLUIDA = 'concluida', 'Concluída'
        CANCELADA = 'cancelada', 'Cancelada'

    class Origem(models.TextChoices):
        FLUXO_COMPLETO = 'fluxo_completo', 'Fluxo completo'
        PEDIDO_ATENDENTE = 'pedido_atendente', 'Pedido de atendente'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    empresa = models.ForeignKey('empresas.Empresa', on_delete=models.PROTECT, related_name='tarefas')
    conversa = models.ForeignKey(Conversa, on_delete=models.PROTECT)
    contato = models.ForeignKey(Contato, on_delete=models.PROTECT)
    servico = models.ForeignKey(Servico, null=True, blank=True, on_delete=models.SET_NULL)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.ABERTA)
    origem = models.CharField(max_length=20, choices=Origem.choices)
    resumo_triagem = models.TextField()
    atendente = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL)
    criada_em = models.DateTimeField(auto_now_add=True)
    assumida_em = models.DateTimeField(null=True, blank=True)
    concluida_em = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['empresa', 'status', '-criada_em'], name='atend_empresa_status_idx'),
            models.Index(fields=['empresa', 'contato'], name='atend_empresa_contato_idx'),
        ]

    def __str__(self):
        return f"Tarefa {str(self.id)[:8]} — {self.contato} — {self.get_status_display()}"
