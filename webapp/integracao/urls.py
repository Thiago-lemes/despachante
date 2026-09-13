from django.contrib.auth.decorators import login_not_required
from django.urls import path, include
from . import views

urlpatterns = [
    path('v1/integracao/', include('integracao.api.urls')),
    path('webhooks/waha/<str:sessao>/', login_not_required(views.webhook_waha), name='webhook_waha'),
    path('empresa/<int:empresa_id>/qrcode/', views.gerar_qr_code_empresa, name='gerar_qr_code_empresa'),
]
