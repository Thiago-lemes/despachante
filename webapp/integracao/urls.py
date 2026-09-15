from django.urls import path, include
from . import views

# Montado uma única vez em config/urls.py sob '/api/v1/integracao/'.
urlpatterns = [
    path('', include('integracao.api.urls')),
    path('empresa/<int:empresa_id>/qrcode/', views.gerar_qr_code_empresa, name='gerar_qr_code_empresa'),
]
