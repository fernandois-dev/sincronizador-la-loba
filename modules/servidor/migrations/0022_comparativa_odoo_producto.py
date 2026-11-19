import data.custom_fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('servidor', '0021_alter_compraodoo_fecha'),
    ]

    operations = [
        migrations.AddField(
            model_name='comparativa',
            name='odoo_producto',
            field=data.custom_fields.CustomCharField(blank=True, max_length=255, null=True, verbose_name='Descripción O.'),
        ),
    ]
