from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('empresas/', include('empresas.urls')),
    path('accounts/', include('django.contrib.auth.urls')),
    path('atendimento/', include('atendimento.urls')),
    path('api/v1/integracao/', include('integracao.urls')),
    path('', include('documentos.urls')),
    path('', include('usuario.urls')),
]
