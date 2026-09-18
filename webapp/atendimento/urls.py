from django.urls import path
from . import views

urlpatterns = [
    path('', views.kanban_tarefas, name='kanban_index'),
    path('kanban/', views.kanban_tarefas, name='kanban_tarefas'),
    path('api/tarefa/status/', views.atualizar_status_tarefa, name='atualizar_status_tarefa'),
    path('api/tarefas/novas/', views.tarefas_novas_status, name='tarefas_novas_status'),

    path('conversas/', views.minhas_conversas, name='minhas_conversas'),
    path('api/conversas/minhas/', views.minhas_conversas_status,
         name='minhas_conversas_status'),

    path('conversa/<uuid:tarefa_id>/', views.conversa, name='conversa'),
    path('conversa/<uuid:tarefa_id>/responder/', views.conversa_responder,
         name='conversa_responder'),
    path('conversa/<uuid:tarefa_id>/assumir/', views.tarefa_assumir,
         name='tarefa_assumir'),
    path('conversa/<uuid:tarefa_id>/atribuir/', views.tarefa_atribuir,
         name='tarefa_atribuir'),
    path('conversa/<uuid:tarefa_id>/novidades/', views.conversa_novidades,
         name='conversa_novidades'),

    path('chatbot/', views.chatbot_config, name='chatbot_config'),
    path('chatbot/servico/novo/', views.chatbot_servico, name='chatbot_servico_novo'),
    path('chatbot/servico/<int:servico_id>/', views.chatbot_servico, name='chatbot_servico_editar'),
    path('chatbot/servico/<int:servico_id>/excluir/', views.chatbot_servico_excluir,
         name='chatbot_servico_excluir'),
    path('chatbot/servicos/ordem/', views.chatbot_reordenar_servicos,
         name='chatbot_reordenar_servicos'),
    path('chatbot/conversa/<int:conversa_id>/religar/', views.chatbot_religar_conversa,
         name='chatbot_religar_conversa'),
]