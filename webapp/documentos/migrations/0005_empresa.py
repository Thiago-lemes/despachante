from django.db import migrations, models
import django.db.models.deletion


def associar_empresa_padrao(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    Documento = apps.get_model('documentos', 'Documento')
    Lote = apps.get_model('documentos', 'Lote')
    empresa = Empresa.objects.get(nome='Empresa padrão')
    Documento.objects.filter(empresa__isnull=True).update(empresa=empresa)
    Lote.objects.filter(empresa__isnull=True).update(empresa=empresa)


class Migration(migrations.Migration):

    dependencies = [
        ('documentos', '0004_documento_processo'),
        ('empresas', '0002_empresa_padrao'),
    ]

    operations = [
        migrations.RemoveIndex(
            model_name='documento', name='documentos_enviado_1780e0_idx'),
        migrations.AddField(
            model_name='documento',
            name='empresa',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='documentos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='lote',
            name='empresa',
            field=models.ForeignKey(
                null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name='lotes_documentos', to='empresas.empresa'),
        ),
        migrations.RunPython(associar_empresa_padrao, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='documento',
            name='empresa',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='documentos', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='lote',
            name='empresa',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name='lotes_documentos', to='empresas.empresa'),
        ),
        migrations.AddIndex(
            model_name='documento',
            index=models.Index(
                fields=['empresa', 'hash_sha256', 'pipeline'],
                name='documentos_empresa_hash_idx'),
        ),
    ]
