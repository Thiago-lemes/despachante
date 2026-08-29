from django.urls import path
from . import views

urlpatterns = [
    path('webhook/', views.webhook_receive, name='webhook_receive'),
    path('webhook/verify/', views.webhook_verify, name='webhook_verify'),
    path('kanban/', views.kanban_tarefas, name='kanban_tarefas'),
    path('api/tarefa/status/', views.atualizar_status_tarefa, name='atualizar_status_tarefa'),
]