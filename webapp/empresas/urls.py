from django.urls import path

from . import views

urlpatterns = [
    path('selecionar/', views.selecionar_empresa, name='selecionar_empresa'),
    path('acesso-pendente/', views.acesso_pendente, name='acesso_pendente'),
    path('equipe/', views.equipe, name='equipe'),
    path('equipe/<int:vinculo_id>/aprovar/', views.aprovar_vinculo, name='aprovar_vinculo'),
    path('equipe/<int:vinculo_id>/recusar/', views.recusar_vinculo, name='recusar_vinculo'),
]
