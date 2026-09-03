from django.urls import path, include
from . import views

urlpatterns = [
    path('v1/integracao/', include('integracao.api.urls')),
    path('webhooks/waha/<str:sessao>/', views.webhook_waha, name='webhook_waha'),
]
