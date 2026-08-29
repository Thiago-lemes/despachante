from django.db import migrations, models
import django.db.models.deletion


MODELOS_COM_EMPRESA = [
    'Contato', 'Servico', 'Conversa', 'Mensagem', 'DocumentoExigido',
    'DocumentoRecebido', 'Tarefa',
]


def associar_empresa_padrao(apps, schema_editor):
    Empresa = apps.get_model('empresas', 'Empresa')
    empresa = Empresa.objects.get(nome='Empresa padrão')
    for nome_modelo in MODELOS_COM_EMPRESA:
        Modelo = apps.get_model('atendimento', nome_modelo)
        Modelo.objects.filter(empresa__isnull=True).update(empresa=empresa)


class Migration(migrations.Migration):

    dependencies = [
        ('atendimento', '0001_initial'),
        ('empresas', '0002_empresa_padrao'),
    ]

    operations = [
        migrations.AddField(
            model_name='contato', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='contatos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='servico', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='servicos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='conversa', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='conversas', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='mensagem', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='mensagens', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='documentoexigido', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_exigidos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='documentorecebido', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='documentos_recebidos', to='empresas.empresa'),
        ),
        migrations.AddField(
            model_name='tarefa', name='empresa',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='tarefas', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='contato', name='wa_id', field=models.CharField(max_length=20),
        ),
        migrations.RunPython(associar_empresa_padrao, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='contato', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='contatos', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='servico', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='servicos', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='conversa', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='conversas', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='mensagem', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='mensagens', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='documentoexigido', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_exigidos', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='documentorecebido', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='documentos_recebidos', to='empresas.empresa'),
        ),
        migrations.AlterField(
            model_name='tarefa', name='empresa',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tarefas', to='empresas.empresa'),
        ),
        migrations.AddConstraint(
            model_name='contato',
            constraint=models.UniqueConstraint(fields=('empresa', 'wa_id'), name='contato_empresa_wa_id_unico'),
        ),
        migrations.AddConstraint(
            model_name='servico',
            constraint=models.UniqueConstraint(fields=('empresa', 'nome'), name='servico_empresa_nome_unico'),
        ),
        migrations.RemoveIndex(model_name='tarefa', name='atendimento_status_d849fb_idx'),
        migrations.RemoveIndex(model_name='tarefa', name='atendimento_contato_6e7575_idx'),
        migrations.AddIndex(
            model_name='tarefa',
            index=models.Index(fields=['empresa', 'status', '-criada_em'], name='atend_empresa_status_idx'),
        ),
        migrations.AddIndex(
            model_name='tarefa',
            index=models.Index(fields=['empresa', 'contato'], name='atend_empresa_contato_idx'),
        ),
    ]
