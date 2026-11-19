from django.db import migrations, models
from django.db.models import Count


def dedupe_resumen_venta(apps, schema_editor):
    """
    Elimina duplicados (producto, anio, mes) conservando la fila de mayor id,
    que es la que .first() con ordering=["-id"] venía devolviendo, para que
    los números visibles no cambien tras aplicar la constraint.
    """
    ResumenVentaProducto = apps.get_model("servidor", "ResumenVentaProducto")
    duplicados = (
        ResumenVentaProducto.objects.values("producto", "anio", "mes")
        .annotate(total=Count("id"))
        .filter(total__gt=1)
    )
    for grupo in duplicados:
        ids = list(
            ResumenVentaProducto.objects.filter(
                producto=grupo["producto"], anio=grupo["anio"], mes=grupo["mes"]
            )
            .order_by("-id")
            .values_list("id", flat=True)
        )
        ResumenVentaProducto.objects.filter(id__in=ids[1:]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("servidor", "0024_compra_mayorista"),
    ]

    operations = [
        migrations.RunPython(dedupe_resumen_venta, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="resumenventaproducto",
            constraint=models.UniqueConstraint(
                fields=("producto", "anio", "mes"),
                name="uniq_resumen_venta_prod_anio_mes",
            ),
        ),
    ]
