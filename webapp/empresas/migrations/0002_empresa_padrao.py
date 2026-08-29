from django.conf import settings
from django.db import migrations


NOME_EMPRESA_PADRAO = 'Empresa padrão'


def criar_empresa_padrao_e_vinculos(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    EmpresaUsuario = apps.get_model('empresas', 'EmpresaUsuario')
    app_label, model_name = settings.AUTH_USER_MODEL.split('.')
    Usuario = apps.get_model(app_label, model_name)

    empresa, _ = Empresa.objects.get_or_create(
        nome=NOME_EMPRESA_PADRAO,
        defaults={'ativa': True},
    )
    for usuario in Usuario.objects.all().iterator():
        EmpresaUsuario.objects.get_or_create(
            empresa=empresa,
            usuario=usuario,
            defaults={'papel': 'administrador', 'ativo': True},
        )


class Migration(migrations.Migration):

    dependencies = [
        ('empresas', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(criar_empresa_padrao_e_vinculos, migrations.RunPython.noop),
    ]
