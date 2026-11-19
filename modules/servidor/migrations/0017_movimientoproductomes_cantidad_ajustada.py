# Generated migration for adding cantidad_ajustada field to MovimientoProductoMes

import data.custom_fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('servidor', '0016_alter_movimientoproductomes_anio_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='movimientoproductomes',
            name='cantidad_ajustada',
            field=data.custom_fields.CustomIntegerField(default=0, verbose_name='Cantidad Ajustada'),
        ),
    ]
