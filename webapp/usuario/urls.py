from django.urls import path
from . import views

urlpatterns = [
    path('cadastro/', views.cadastro_despachante, name='cadastro'),
    path('cadastro/enviado/', views.cadastro_enviado, name='cadastro_enviado'),
]
