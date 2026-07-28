from django.urls import path

from . import views

urlpatterns = [
    path('', views.busca, name='busca'),
    path('enviar/', views.enviar, name='enviar'),
    path('conta/', views.conta, name='conta'),
    path('cadastro/', views.cadastro, name='cadastro'),
    path('historico/', views.historico, name='historico'),
    path('em-processamento/', views.em_processamento, name='em_processamento'),
    path('em-processamento/status/', views.em_processamento_status, name='em_processamento_status'),
    path('pendentes/', views.pendentes_status, name='pendentes_status'),
    path('lotes/', views.lotes, name='lotes'),
    path('lotes/<int:pk>/', views.lote_detalhe, name='lote_detalhe'),
    path('lotes/<int:pk>/status/', views.lote_status, name='lote_status'),
    path('doc/<int:pk>/', views.detalhe, name='detalhe'),
    path('doc/<int:pk>/status/', views.documento_status, name='documento_status'),
    path('doc/<int:pk>/arquivo/', views.arquivo, name='arquivo'),
    path('doc/<int:pk>/reprocessar/', views.reprocessar, name='reprocessar'),
    path('doc/<int:pk>/excluir/', views.excluir, name='excluir'),
]
