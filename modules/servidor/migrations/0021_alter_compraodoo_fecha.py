from django.db import migrations
import data.custom_fields
import datetime


def clear_compraodoo(apps, schema_editor):
    CompraOdoo = apps.get_model('servidor', 'CompraOdoo')
    CompraOdoo.objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('servidor', '0020_odooproducto_favorito'),
    ]

    operations = [
        migrations.RunPython(clear_compraodoo, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='compraodoo',
            name='fecha',
            field=data.custom_fields.CustomDateTimeField(column_width=180, default=datetime.datetime.now, verbose_name='Fecha'),
        ),
    ]
