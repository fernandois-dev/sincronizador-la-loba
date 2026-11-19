# Generated migration for MovimientoProductoMes model

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('servidor', '0014_resumencompraproducto_proveedor'),
    ]

    operations = [
        migrations.CreateModel(
            name='MovimientoProductoMes',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('producto_id', models.IntegerField(default=0, verbose_name='ID Producto')),
                ('producto_nombre', models.CharField(default='', max_length=255, verbose_name='Nombre Producto')),
                ('mes', models.IntegerField(default=1, verbose_name='Mes')),
                ('anio', models.IntegerField(default=2025, verbose_name='Año')),
                ('cantidad_comprada', models.IntegerField(default=0, verbose_name='Cantidad Comprada')),
                ('total_compras', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Total Compras')),
                ('precio_compra_promedio', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Precio Compra Promedio')),
                ('cantidad_vendida', models.IntegerField(default=0, verbose_name='Cantidad Vendida')),
                ('total_ventas', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Total Ventas')),
                ('precio_venta_promedio', models.DecimalField(decimal_places=2, default=0, max_digits=12, verbose_name='Precio Venta Promedio')),
                ('stock_cierre_mes', models.IntegerField(default=0, verbose_name='Stock Cierre Mes')),
                ('fecha_actualizacion', models.DateTimeField(auto_now=True, verbose_name='Fecha Actualización')),
            ],
            options={
                'verbose_name': 'Movimiento Producto Mes',
                'verbose_name_plural': 'Movimientos Productos Mes',
                'ordering': ['anio', 'mes', 'producto_nombre'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='movimientoproductomes',
            unique_together={('producto_id', 'mes', 'anio')},
        ),
    ]
