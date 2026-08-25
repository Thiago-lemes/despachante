from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('django.contrib.auth.urls')),
    path('whatsapp/', include('atendimento.urls')),
    path('atendimento/', include('atendimento.urls')),  # ← Essa linha PRECISA estar aqui
    path('', include('documentos.urls')),
]