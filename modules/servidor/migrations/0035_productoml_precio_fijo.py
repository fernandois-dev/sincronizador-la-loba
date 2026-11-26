import data.custom_fields
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("servidor", "0034_productoml_atributos_origen"),
    ]

    operations = [
        migrations.AddField(
            model_name="productoml",
            name="precio_ml_fijo",
            field=data.custom_fields.CustomBooleanField(default=False, hidden=True, verbose_name="Precio ML fijado"),
        ),
        migrations.AddField(
            model_name="productoml",
            name="comision_normal",
            field=data.custom_fields.CustomMoneyField(default=0, column_width=120, hidden=True,
                                                     verbose_name="Comisión ML normal"),
        ),
    ]
