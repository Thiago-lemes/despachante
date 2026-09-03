from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('empresas/', include('empresas.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('api/', include('integracao.urls')),
    path('whatsapp/', include('atendimento.urls')),
    path('atendimento/', include('atendimento.urls')),
    path('', include('documentos.urls')),
    path('', include('usuario.urls')),
    path('api/v1/integracao/', include('integracao.urls')),
]