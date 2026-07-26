from django.db import migrations, models


def renomear_para_openai(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    Documento.objects.filter(pipeline='deepseek').update(pipeline='openai')


def renomear_para_deepseek(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    Documento.objects.filter(pipeline='openai').update(pipeline='deepseek')


class Migration(migrations.Migration):
    dependencies = [('documentos', '0002_lotes_e_processamento')]

    operations = [
        migrations.AlterField(
            model_name='documento',
            name='pipeline',
            field=models.CharField(
                choices=[('gemini', 'Gemini visual'), ('openai', 'OpenAI visual')],
                default='gemini', max_length=12),
        ),
        migrations.RunPython(renomear_para_openai, renomear_para_deepseek),
    ]
