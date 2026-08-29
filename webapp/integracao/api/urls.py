from django.urls import path

from . import views

urlpatterns = [
    path('health/', views.health, name='integracao_health'),
    path('sessoes/<str:nome_sessao>/health/', views.sessao_health, name='integracao_sessao_health'),
    path('mensagens/', views.mensagens_ingest, name='integracao_mensagens_ingest'),
    path('mensagens/enviar/', views.mensagens_enviar, name='integracao_mensagens_enviar'),
    path('conversas/<int:conversa_id>/', views.conversa_detalhe, name='integracao_conversa_detalhe'),
    path('conversas/<int:conversa_id>/tarefas/', views.conversa_criar_tarefa,
         name='integracao_conversa_criar_tarefa'),
    path('documentos-recebidos/', views.documentos_receber, name='integracao_documentos_receber'),
    path('documentos-recebidos/<int:documento_id>/analisar/', views.documento_analisar,
         name='integracao_documento_analisar'),
    path('documentos-recebidos/<int:documento_id>/revisao/', views.documento_revisar,
         name='integracao_documento_revisar'),
    path('webhooks/waha/<str:nome_sessao>/', views.webhook_waha, name='integracao_webhook_waha'),
]
