from django.urls import path
from . import views

urlpatterns = [
    path('', views.kanban_tarefas, name='kanban_index'),
    path('kanban/', views.kanban_tarefas, name='kanban_tarefas'),
    path('api/tarefa/status/', views.atualizar_status_tarefa, name='atualizar_status_tarefa'),
    path('api/tarefas/novas/', views.tarefas_novas_status, name='tarefas_novas_status'),

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