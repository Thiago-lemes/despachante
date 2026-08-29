from django.urls import path, include

urlpatterns = [
    path('v1/integracao/', include('integracao.api.urls')),
]
