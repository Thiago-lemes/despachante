from django.urls import path
from . import views

urlpatterns = [
    path('', views.kanban_tarefas, name='kanban_index'),
    path('kanban/', views.kanban_tarefas, name='kanban_tarefas'),
    path('api/tarefa/status/', views.atualizar_status_tarefa, name='atualizar_status_tarefa'),
    path('api/tarefas/novas/', views.tarefas_novas_status, name='tarefas_novas_status'),
]