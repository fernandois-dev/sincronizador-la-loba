from django.db import migrations
import data.custom_fields


class Migration(migrations.Migration):

    dependencies = [
        ('servidor', '0023_alter_comparativa_producto'),
    ]

    operations = [
        migrations.AddField(
            model_name='tablabase',
            name='precio_mayor',
            field=data.custom_fields.CustomMoneyField(blank=True, column_width=150, default=0, null=True, verbose_name='Precio Por Mayor'),
        ),
        migrations.AddField(
            model_name='tablabase',
            name='uds_agrupamiento',
            field=data.custom_fields.CustomDecimalField(blank=True, column_width=120, default=0, null=True, verbose_name='N° de Uds.'),
        ),
        migrations.AddField(
            model_name='comparativa',
            name='precio_mayor',
            field=data.custom_fields.CustomMoneyField(blank=True, column_width=150, default=0, null=True, verbose_name='Precio Por Mayor'),
        ),
        migrations.AddField(
            model_name='comparativa',
            name='uds_agrupamiento',
            field=data.custom_fields.CustomDecimalField(blank=True, column_width=120, default=0, null=True, verbose_name='N° de Uds.'),
        ),
        migrations.AddField(
            model_name='detallecompra',
            name='uds_agrupamiento',
            field=data.custom_fields.CustomDecimalField(blank=True, column_width=100, default=0, null=True, verbose_name='N° Uds.'),
        ),
    ]
