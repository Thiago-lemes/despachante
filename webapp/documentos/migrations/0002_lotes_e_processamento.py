import hashlib

from django.db import migrations, models
import django.db.models.deletion


def preencher_hashes(apps, schema_editor):
    Documento = apps.get_model('documentos', 'Documento')
    for documento in Documento.objects.all().iterator():
        try:
            digest = hashlib.sha256()
            with documento.arquivo.open('rb') as arquivo:
                for trecho in iter(lambda: arquivo.read(1024 * 1024), b''):
                    digest.update(trecho)
            documento.hash_sha256 = digest.hexdigest()
            documento.pipeline = 'gemini'
            documento.provedor_utilizado = 'Gemini'
            documento.modelo_utilizado = 'gemini-2.5-flash'
            documento.save(update_fields=[
                'hash_sha256', 'pipeline', 'provedor_utilizado', 'modelo_utilizado'])
        except OSError:
            continue


class Migration(migrations.Migration):
    dependencies = [('documentos', '0001_initial')]

    operations = [
        migrations.CreateModel(
            name='Lote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('modo', models.CharField(choices=[('avulso', 'Envio avulso'), ('lote', 'Envio em lote')], max_length=8)),
                ('criado_em', models.DateTimeField(auto_now_add=True)),
                ('enviado_por', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='lotes_documentos', to='auth.user')),
            ],
            options={'ordering': ['-criado_em']},
        ),
        migrations.AddField(model_name='documento', name='hash_sha256', field=models.CharField(blank=True, db_index=True, max_length=64)),
        migrations.AddField(model_name='documento', name='pipeline', field=models.CharField(choices=[('gemini', 'Gemini visual'), ('deepseek', 'OCR + DeepSeek Pro')], default='gemini', max_length=12)),
        migrations.AddField(model_name='documento', name='provedor_utilizado', field=models.CharField(blank=True, max_length=20)),
        migrations.AddField(model_name='documento', name='modelo_utilizado', field=models.CharField(blank=True, max_length=80)),
        migrations.AddField(model_name='documento', name='usou_fallback', field=models.BooleanField(default=False)),
        migrations.AddField(model_name='documento', name='motivo_fallback', field=models.TextField(blank=True)),
        migrations.AddField(model_name='documento', name='tentativas', field=models.PositiveSmallIntegerField(default=0)),
        migrations.AddField(model_name='documento', name='processamento_iniciado_em', field=models.DateTimeField(blank=True, null=True)),
        migrations.AddField(model_name='documento', name='processamento_finalizado_em', field=models.DateTimeField(blank=True, null=True)),
        migrations.AlterField(model_name='documento', name='status', field=models.CharField(choices=[('aguardando', 'Na fila'), ('processando', 'Processando'), ('concluido', 'Concluido'), ('erro', 'Erro')], default='aguardando', max_length=12)),
        migrations.AlterField(model_name='documento', name='enviado_por', field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='documentos', to='auth.user', verbose_name='enviado por')),
        migrations.RunPython(preencher_hashes, migrations.RunPython.noop),
        migrations.AddIndex(model_name='documento', index=models.Index(fields=['enviado_por', 'hash_sha256', 'pipeline'], name='documentos_enviado_1780e0_idx')),
        migrations.CreateModel(
            name='ItemLote',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome_original', models.CharField(max_length=255)),
                ('ordem', models.PositiveSmallIntegerField(default=0)),
                ('reutilizado', models.BooleanField(default=False)),
                ('documento', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='itens_lote', to='documentos.documento')),
                ('lote', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='itens', to='documentos.lote')),
            ],
            options={'ordering': ['ordem', 'pk']},
        ),
        migrations.AddConstraint(model_name='itemlote', constraint=models.UniqueConstraint(fields=('lote', 'ordem'), name='item_lote_ordem_unica')),
    ]
