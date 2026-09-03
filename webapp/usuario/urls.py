from django.urls import path
from . import views

urlpatterns = [
    path('cadastro/', views.cadastro_despachante, name='cadastro'),
]