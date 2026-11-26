from datetime import datetime
from django.db import models
from data.custom_fields import CustomAutoField, CustomBooleanField, CustomCharField, CustomDateField, CustomDecimalField, CustomForeignKey, CustomIntegerField, CustomMoneyField, CustomDateTimeField


# class VistaSincronizacion(models.Model):
#     numero_caja = CustomCharField(max_length=100, verbose_name="Caja", null=False, blank=False, is_sortable=True, is_searchable=True, primary_key=True)
#     ip = CustomCharField(max_length=100, verbose_name="IP", null=False, blank=False, is_sortable=True, is_searchable=True)
#     ultima_venta = CustomDateTimeField(verbose_name="Ultima Venta", null=True, blank=True, is_sortable=True, is_searchable=True)
#     ultima_sincronizacion = CustomDateTimeField(verbose_name="Ultima Sincronización", null=True, blank=True, is_sortable=True, is_searchable=True)

#     class Meta:
#         managed = False  # Indica que Django no debe gestionar este modelo
#         db_table = 'vista_sincronizacion'  # Nombre de la vista en la base de datos
        
        
class HojasTablaBase(models.Model):
    """
    Clase base para las hojas de tabla.
    Contiene campos comunes que pueden ser utilizados en diferentes hojas de tabla.
    """
    id = CustomAutoField(primary_key=True, verbose_name="ID")
    nombre = CustomCharField(max_length=100, verbose_name="Nombre", null=False, blank=False, is_sortable=True, is_searchable=True, column_width=350)
    activo = CustomBooleanField(default=True, verbose_name="Activo", null=False, blank=False)

    class Meta:
        db_table = 'hojas_tabla_base'
        verbose_name = 'Hoja Tabla Base'
        verbose_name_plural = 'Hojas Tablas Base'
        ordering = ["id"]
        
    def __str__(self):
        return self.nombre
    
    
class OdooProducto(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    name = CustomCharField(max_length=255, verbose_name="Nombre", null=False, blank=False)
    list_price = CustomMoneyField(verbose_name="Precio", null=False, blank=False, default=0)
    barcode = CustomCharField(max_length=255, verbose_name="Código de Barras", null=True, blank=True)
    categ_id = CustomCharField(max_length=255, verbose_name="Categoría", null=True, blank=True, default="")
    qty_available = CustomIntegerField(verbose_name="Cantidad Disponible", null=True, blank=True, default=0)
    virtual_available = CustomIntegerField(verbose_name="Cantidad Virtual", null=True, blank=True, default=0)
    incoming_qty = CustomIntegerField(verbose_name="Cantidad Entrante", null=True, blank=True, default=0)
    outgoing_qty = CustomIntegerField(verbose_name="Cantidad Saliente", null=True, blank=True, default=0)
    default_code = CustomCharField(max_length=255, verbose_name="Código Interno", null=True, blank=True)
    activo = CustomBooleanField(verbose_name="Activo", default=True, null=False, blank=False)
    favorito = CustomBooleanField(verbose_name="Favorito", default=False, null=False, blank=False)

    def __str__(self):
        return f"{self.name} ({self.id})"

    class Meta:
        verbose_name = "Producto Odoo"
        verbose_name_plural = "Productos Odoo"
        ordering = ["-id"]
      
      
class OdooTarifa(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    partner_id = CustomIntegerField(verbose_name="ID Partner", null=False, blank=False, default=0)
    partner = CustomCharField(max_length=255, verbose_name="Partner", null=True, blank=True, default="")
    product_tmpl_id = CustomIntegerField(verbose_name="ID Producto", null=False, blank=False, default=0)
    product_tmpl = CustomCharField(max_length=255, verbose_name="Producto", null=True, blank=True, default="")
    price = CustomMoneyField(verbose_name="Precio", null=False, blank=False, default=0)
    sequence = CustomIntegerField(verbose_name="Secuencia", null=True, blank=True, default=0)
    # REF INTERNA de la fila en la hoja del proveedor (product.supplierinfo.product_code)
    product_code = CustomCharField(max_length=255, verbose_name="Código Proveedor", null=True, blank=True, default="")

    def __str__(self):
        return f"{self.partner} - {self.product_tmpl_id} ({self.price})"

    class Meta:
        verbose_name = "Tarifa Odoo"
        verbose_name_plural = "Tarifas Odoo"
        ordering = ["-id"]
        

class OdooRuta(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    product_id = CustomIntegerField(verbose_name="ID Producto", null=False, blank=False, default=0)
    product_tmpl_id = CustomIntegerField(verbose_name="ID Template", null=True, blank=True, default=0)
    product = CustomCharField(max_length=255, verbose_name="Producto Nombre", null=True, blank=True, default="")
    location_id = CustomIntegerField(verbose_name="ID Ubicación", null=False, blank=False, default=0)
    product_min_qty = CustomIntegerField(verbose_name="Cantidad Mínima", null=True, blank=True, default=0)
    product_max_qty = CustomIntegerField(verbose_name="Cantidad Máxima", null=True, blank=True, default=0)

    def __str__(self):
        return f"{self.product_id} - {self.location_id}"

    class Meta:
        verbose_name = "Regla Odoo"
        verbose_name_plural = "Reglas Odoo"
        ordering = ["-id"]

class OdooProveedor(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    name = CustomCharField(max_length=255, verbose_name="Nombre", null=False, blank=False)

    def __str__(self):
        return f"{self.name}"

    class Meta:
        verbose_name = "Proveedor Odoo"
        verbose_name_plural = "Proveedores Odoo"
        ordering = ["-id"]
        
class HojasSeleccionadas(models.Model):
    """
    Clase para las hojas seleccionadas.
    Permite seleccionar varias hojas de tabla base.
    """
    id = CustomAutoField(primary_key=True, verbose_name="ID")
    hoja = CustomCharField(max_length=100, verbose_name="Hoja", null=False, blank=False)
    proveedor = CustomForeignKey(OdooProveedor, verbose_name="Proveedor", null=True, blank=True, on_delete=models.SET_NULL)

    class Meta:
        db_table = 'hojas_seleccionadas'
        verbose_name = 'Hoja Seleccionada'
        verbose_name_plural = 'Hojas Seleccionadas'
        ordering = ["id"]
        
    def __str__(self):
        return str(self.hoja)  # Retorna el nombre de la hoja seleccionada

class TablaBase(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    procesar = CustomBooleanField(verbose_name="Procesar", default=True)
    descripcion = CustomCharField(max_length=255, verbose_name="Descripción", null=False, blank=False, column_width=300)
    precio = CustomMoneyField(verbose_name="Precio", null=False, blank=False, default=0, column_width=150)
    stock = CustomIntegerField(verbose_name="Stock", null=True, blank=True, default=0, column_width=130)
    barcode = CustomCharField(max_length=255, verbose_name="Código de Barras", null=True, blank=True, column_width=150)
    categoria = CustomCharField(max_length=255, verbose_name="Categoría", null=True, blank=True)
    ref_interna = CustomCharField(max_length=255, verbose_name="REF Interna", null=True, blank=True, column_width=150)
    proveedor_id = CustomCharField(max_length=255, verbose_name="Proveedor", null=True, blank=True, column_width=180)
    proveedor_descripcion = CustomCharField(max_length=255, verbose_name="Descripción Proveedor", null=True, blank=True, column_width=200)
    precio_compra = CustomMoneyField(verbose_name="Precio Compra", null=True, blank=True, default=0, column_width=150)
    cant_min = CustomIntegerField(verbose_name="Cantidad Mínima", null=True, blank=True, default=0, column_width=130)
    cant_max = CustomIntegerField(verbose_name="Cantidad Máxima", null=True, blank=True, default=0, column_width=130)
    activo = CustomBooleanField(verbose_name="Activo", default=True, null=False, blank=False, column_width=100)
    hoja_seleccionada = CustomForeignKey(HojasSeleccionadas, verbose_name="Hoja Seleccionada", null=True, blank=True, on_delete=models.CASCADE, column_width=200)
    cantidad_compra = CustomDecimalField(verbose_name="Cantidad Compra", null=True, blank=True, default=0, column_width=150)
    precio_mayor = CustomMoneyField(verbose_name="Precio Por Mayor", null=True, blank=True, default=0, column_width=150)
    uds_agrupamiento = CustomDecimalField(verbose_name="N° de Uds.", null=True, blank=True, default=0, column_width=120)

    def __str__(self):
        return f"{self.descripcion} ({self.id})"

    class Meta:
        verbose_name = "Tabla Base"
        verbose_name_plural = "Tablas Base"
        ordering = ["-id"]
  
        
class Comparativa(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    ref_interna = CustomCharField(max_length=255, verbose_name="REF Interna", null=True, blank=True, column_width=150, is_sortable=True)
    producto_id = CustomIntegerField(verbose_name="ID Producto", null=True, blank=True, default=0, column_width=150)
    producto = CustomCharField(max_length=255, verbose_name="Descripción T.B.", null=True, blank=True, column_width=350, is_sortable=True)
    odoo_producto = CustomCharField(max_length=255, verbose_name="Descripción O.", null=True, blank=True, column_width=350, is_sortable=True)
    existe = CustomBooleanField(verbose_name="E", default=False, column_width=80)
    desc_ok = CustomBooleanField(verbose_name="D. OK", default=False, column_width=80)
    tb_precio = CustomMoneyField(verbose_name="Precio T.B.", null=True, blank=True, default=0, column_width=150)
    odoo_precio = CustomMoneyField(verbose_name="Precio O.", null=True, blank=True, default=0, column_width=150)
    tb_stock = CustomIntegerField(verbose_name="Stock T.B.", null=True, blank=True, default=0, column_width=150)
    odoo_stock = CustomIntegerField(verbose_name="Stock O.", null=True, blank=True, default=0, column_width=150)
    tb_barcode = CustomCharField(max_length=255, verbose_name="C. Barras T.B.", null=True, blank=True, column_width=150)
    odoo_barcode = CustomCharField(max_length=255, verbose_name="C. Barras O.", null=True, blank=True, column_width=150)
    tb_proveedor = CustomForeignKey(OdooProveedor, verbose_name="ID Proveedor TB.", null=True, blank=True, on_delete=models.SET_NULL, column_width=300)
    odoo_proveedor = CustomForeignKey(OdooProveedor, verbose_name="ID Proveedor O.", null=True, blank=True, on_delete=models.SET_NULL, column_width=300)
    tb_precio_compra = CustomMoneyField(verbose_name="Precio Compra T.B.", null=True, blank=True, default=0, column_width=150)
    odoo_precio_compra = CustomMoneyField(verbose_name="Precio Compra O.", null=True, blank=True, default=0, column_width=150)
    tb_min = CustomIntegerField(verbose_name="C. Mín T.B.", null=True, blank=True, default=0, column_width=150)
    odoo_min = CustomIntegerField(verbose_name="C. Mín O.", null=True, blank=True, default=0, column_width=150)
    tb_max = CustomIntegerField(verbose_name="C. Máx T.B.", null=True, blank=True, default=0, column_width=150)
    odoo_max = CustomIntegerField(verbose_name="C. Máx O.", null=True, blank=True, default=0, column_width=150)
    new_stock = CustomIntegerField(verbose_name="Ajuste Stock", null=True, blank=True, default=0, column_width=150)
    ruta_id = CustomIntegerField(verbose_name="ID Ruta", null=True, blank=True, default=0, column_width=150)
    tb_activo = CustomBooleanField(verbose_name="Activo T.B.", default=True, null=False, blank=False, column_width=100, is_sortable=True)
    odoo_activo = CustomBooleanField(verbose_name="Activo O.", default=True, null=False, blank=False, column_width=100)
    cantidad_compra = CustomDecimalField(verbose_name="Cantidad Compra", null=True, blank=True, default=0, column_width=150)
    precio_mayor = CustomMoneyField(verbose_name="Precio Por Mayor", null=True, blank=True, default=0, column_width=150)
    uds_agrupamiento = CustomDecimalField(verbose_name="N° de Uds.", null=True, blank=True, default=0, column_width=120)
    # Línea de proveedor (product.supplierinfo) del proveedor de ESTA hoja; None si falta en Odoo
    tarifa_id = CustomIntegerField(verbose_name="ID Tarifa", null=True, blank=True, default=None, column_width=120)
    odoo_codigo_proveedor = CustomCharField(max_length=255, verbose_name="Cód. Proveedor O.", null=True, blank=True, default="", column_width=150)

    def __str__(self):
        return f"{self.producto}"

    class Meta:
        verbose_name = "Comparativa"
        verbose_name_plural = "Comparativas"
        ordering = ["id"]
        
    @property
    def name(self):
        return self.producto
        # unique_together = (("ref_interna", "producto"),)  # Asegura que no haya duplicados por REF Interna y Producto   
        

class Compra(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    fecha = CustomDateField(verbose_name="Fecha", null=False, blank=False, default=datetime.now)
    proveedor = CustomForeignKey(HojasTablaBase, verbose_name="Tabla Base", null=False, blank=False, on_delete=models.CASCADE)
    total = CustomMoneyField(verbose_name="Total", null=False, blank=False, default=0)

    def __str__(self):
        return f"Compra {self.id} - {self.proveedor.name} ({self.fecha})"
    
    class Meta:
        verbose_name = "Compra"
        verbose_name_plural = "Compras"
        ordering = ["-fecha"]   
        
class DetalleCompra(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    producto = CustomForeignKey(Comparativa, verbose_name="Producto", null=False, blank=False, on_delete=models.SET_NULL, column_width=350)
    cantidad = CustomIntegerField(verbose_name="Cantidad", null=False, blank=False, default=1, column_width=120)
    uds_agrupamiento = CustomDecimalField(verbose_name="N° Uds.", null=True, blank=True, default=0, column_width=100)
    precio_unitario = CustomMoneyField(verbose_name="Precio Unitario", null=False, blank=False, default=0, column_width=120)
    total = CustomMoneyField(verbose_name="Total", null=False, blank=False, default=0, column_width=120)

    def __str__(self):
        return f"{self.producto} - {self.cantidad} unidades"

    class Meta:
        verbose_name = "Detalle Compra"
        verbose_name_plural = "Detalles Compras"

class CompraOdoo(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False, column_width=100)
    fecha = CustomDateTimeField(verbose_name="Fecha", null=False, blank=False, default=datetime.now, column_width=180)
    proveedor = CustomCharField(max_length=255, verbose_name="Proveedor", null=False, blank=False, default="", column_width=300)
    total = CustomMoneyField(verbose_name="Total", null=False, blank=False, default=0, column_width=150)
    iva = CustomMoneyField(verbose_name="IVA", null=False, blank=False, default=0, column_width=150)
    neto = CustomMoneyField(verbose_name="Neto", null=False, blank=False, default=0, column_width=150)
    estado = CustomCharField(max_length=100, verbose_name="Estado", null=False, blank=False, default="borrador", column_width=150)

    def __str__(self):
        return f"Compra Odoo {self.id} - {self.proveedor} ({self.fecha})"

    class Meta:
        verbose_name = "Compra Odoo"
        verbose_name_plural = "Compras Odoo"
        ordering = ["-fecha"]
        

class DetalleCompraOdoo(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    producto = CustomCharField(max_length=255, verbose_name="Producto", null=False, blank=False, default="")
    cantidad = CustomIntegerField(verbose_name="Cantidad", null=False, blank=False, default=1)
    precio_unitario = CustomMoneyField(verbose_name="Precio Unitario", null=False, blank=False, default=0)
    total = CustomMoneyField(verbose_name="Total", null=False, blank=False, default=0)

    def __str__(self):
        return f"{self.producto} - {self.cantidad} unidades"

    class Meta:
        verbose_name = "Detalle Compra Odoo"
        verbose_name_plural = "Detalles Compras Odoo"
        
        
class ResumenVentaProducto(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    producto = CustomCharField(max_length=255, verbose_name="Producto", null=False, blank=False, default="")
    mes = CustomIntegerField(verbose_name="Mes", null=False, blank=False, default=1)
    anio = CustomIntegerField(verbose_name="Año", null=False, blank=False, default=2025)
    total_ventas = CustomMoneyField(verbose_name="Total Ventas", null=False, blank=False, default=0)
    cantidad_vendida = CustomIntegerField(verbose_name="Cantidad Vendida", null=False, blank=False, default=0)

    def __str__(self):
        return f"{self.producto}"

    class Meta:
        verbose_name = "Resumen Venta Producto"
        verbose_name_plural = "Resumenes Venta Productos"
        ordering = ["-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["producto", "anio", "mes"],
                name="uniq_resumen_venta_prod_anio_mes",
            )
        ]
        
class ResumenCompraProducto(models.Model):
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    producto = CustomCharField(max_length=255, verbose_name="Producto", null=False, blank=False, default="")
    mes = CustomIntegerField(verbose_name="Mes", null=False, blank=False, default=1)
    anio = CustomIntegerField(verbose_name="Año", null=False, blank=False, default=2025)
    total_compras = CustomMoneyField(verbose_name="Total Compras", null=False, blank=False, default=0)
    cantidad_comprada = CustomIntegerField(verbose_name="Cantidad Comprada", null=False, blank=False, default=0)
    precio_compra_promedio = CustomMoneyField(verbose_name="Precio Compra Promedio", null=False, blank=False, default=0)
    proveedor = CustomCharField(max_length=255, verbose_name="Proveedor", null=True, blank=True, default="")

    def __str__(self):
        return f"{self.producto}"

    class Meta:
        verbose_name = "Resumen Compra Producto"
        verbose_name_plural = "Resumenes Compra Productos"
        ordering = ["-id"]


class MovimientoProductoMes(models.Model):
    """
    Modelo para almacenar los movimientos de compra y venta mes a mes
    Evita hacer consultas repetidas a Odoo para los mismos períodos
    """
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    producto_id = CustomIntegerField(verbose_name="ID Producto", null=False, blank=False, default=0)
    producto_nombre = CustomCharField(max_length=255, verbose_name="Nombre Producto", null=False, blank=False, default="")
    mes = CustomIntegerField(verbose_name="Mes", null=False, blank=False, default=1)
    anio = CustomIntegerField(verbose_name="Año", null=False, blank=False, default=2025)
    
    # Movimientos de entrada (compras)
    cantidad_comprada = CustomIntegerField(verbose_name="Cantidad Comprada", null=False, blank=False, default=0)
    total_compras = CustomMoneyField(verbose_name="Total Compras", null=False, blank=False, default=0)
    precio_compra_promedio = CustomMoneyField(verbose_name="Precio Compra Promedio", null=False, blank=False, default=0)
    
    # Movimientos de salida (ventas)
    cantidad_vendida = CustomIntegerField(verbose_name="Cantidad Vendida", null=False, blank=False, default=0)
    total_ventas = CustomMoneyField(verbose_name="Total Ventas", null=False, blank=False, default=0)
    precio_venta_promedio = CustomMoneyField(verbose_name="Precio Venta Promedio", null=False, blank=False, default=0)
    
    # Ajustes de inventario (entradas/salidas manuales)
    cantidad_ajustada = CustomIntegerField(verbose_name="Cantidad Ajustada", null=False, blank=False, default=0)
    
    # Stock
    stock_cierre_mes = CustomIntegerField(verbose_name="Stock Cierre Mes", null=False, blank=False, default=0)
    
    # Control
    fecha_actualizacion = CustomDateTimeField(verbose_name="Fecha Actualización", null=False, blank=False, auto_now=True)
    
    def __str__(self):
        return f"{self.producto_nombre} - {self.mes:02d}/{self.anio}"

    class Meta:
        verbose_name = "Movimiento Producto Mes"
        verbose_name_plural = "Movimientos Productos Mes"
        ordering = ["anio", "mes", "producto_nombre"]
        unique_together = ("producto_id", "mes", "anio")  # Evita duplicados


class ProductoML(models.Model):
    """
    Producto de la Tabla Base marcado con la casilla ML, preparado para Mercado Libre.
    Se regenera completo cada vez que se carga la página "Productos ML"; la planilla
    sigue siendo la fuente de verdad.
    """
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    estado = CustomCharField(max_length=40, verbose_name="Estado", default="", column_width=170, is_sortable=True)
    pendientes = CustomCharField(max_length=255, verbose_name="Pendientes", default="", blank=True, column_width=260)
    hoja = CustomCharField(max_length=150, verbose_name="Hoja", default="", column_width=170, is_sortable=True, is_searchable=True)
    ref_interna = CustomCharField(max_length=100, verbose_name="REF Interna", default="", blank=True, column_width=130, is_sortable=True, is_searchable=True)
    producto = CustomCharField(max_length=255, verbose_name="Producto T.B.", default="", column_width=280, is_sortable=True, is_searchable=True)
    precio_local = CustomMoneyField(verbose_name="Precio Local", default=0, column_width=120)
    precio_ml = CustomMoneyField(verbose_name="Precio ML", default=0, column_width=120)
    comision = CustomMoneyField(verbose_name="Comisión ML", default=0, column_width=120)
    stock = CustomIntegerField(verbose_name="Stock Odoo", null=True, blank=True, column_width=100)
    peso_gr = CustomIntegerField(verbose_name="Peso gr", null=True, blank=True, column_width=90)
    medidas_paquete = CustomCharField(max_length=30, verbose_name="Medidas paquete", default="", blank=True, column_width=130)
    envio = CustomMoneyField(verbose_name="Envío ML", default=0, column_width=110)
    recargo_ml = CustomMoneyField(verbose_name="Recargo ML", default=0, column_width=110)
    # True si el precio ML lo fijó el usuario con la calculadora (dato PRECIO ML en la pestaña FICHAS ML)
    precio_ml_fijo = CustomBooleanField(verbose_name="Precio ML fijado", default=False, hidden=True)
    comision_normal = CustomMoneyField(verbose_name="Comisión ML normal", default=0, column_width=120, hidden=True)
    fotos = CustomIntegerField(verbose_name="Fotos", default=0, column_width=80)
    categoria_id = CustomCharField(max_length=30, verbose_name="Categoría ML", default="", blank=True, column_width=120)
    categoria_nombre = CustomCharField(max_length=255, verbose_name="Nombre Categoría", default="", blank=True, column_width=240)
    categoria_propuesta = CustomBooleanField(verbose_name="Cat. propuesta", default=False, hidden=True)
    marca = CustomCharField(max_length=100, verbose_name="Marca", default="", blank=True, column_width=120)
    marca_propuesta = CustomBooleanField(verbose_name="Marca propuesta", default=False, hidden=True)
    titulo = CustomCharField(max_length=255, verbose_name="Título ML", default="", blank=True, column_width=340)
    titulo_propuesta = CustomBooleanField(verbose_name="Título propuesto", default=False, hidden=True)
    descripcion = CustomCharField(max_length=5000, verbose_name="Descripción ML", default="", blank=True, hidden=True)
    descripcion_propuesta = CustomBooleanField(verbose_name="Descripción propuesta (IA)", default=False, hidden=True)
    barcode = CustomCharField(max_length=100, verbose_name="Código de Barras", default="", blank=True, hidden=True)
    fila = CustomIntegerField(verbose_name="Fila", default=0, hidden=True)
    col_categoria = CustomIntegerField(verbose_name="Col. categoría", null=True, blank=True, hidden=True)
    col_marca = CustomIntegerField(verbose_name="Col. marca", null=True, blank=True, hidden=True)
    col_titulo = CustomIntegerField(verbose_name="Col. título", null=True, blank=True, hidden=True)
    col_descripcion = CustomIntegerField(verbose_name="Col. descripción", null=True, blank=True, hidden=True)
    odoo_id = CustomIntegerField(verbose_name="ID Odoo", null=True, blank=True, hidden=True)
    # publicación vinculada en Mercado Libre (se busca por SKU = REF INTERNA en cada carga)
    ml_item_id = CustomCharField(max_length=30, verbose_name="Publicación ML", default="", blank=True, column_width=140)
    ml_estado = CustomCharField(max_length=30, verbose_name="Estado en ML", default="", blank=True, column_width=120)
    ml_link = CustomCharField(max_length=255, verbose_name="Link ML", default="", blank=True, hidden=True)
    # datos de la categoría leídos de las columnas "<DATO> ML" de la planilla, como JSON {"FORMA": "Rectangular", …}
    atributos_ml = CustomCharField(max_length=4000, verbose_name="Datos ML", default="{}", blank=True, hidden=True)
    # de dónde salió cada dato: {"FORMA": "planilla" | "ficha" | "por defecto"} (ver mercadolibre/fichas.py)
    atributos_origen = CustomCharField(max_length=2000, verbose_name="Origen datos ML", default="{}", blank=True,
                                       hidden=True)

    def __str__(self):
        return f"{self.producto} ({self.hoja})"

    @property
    def name(self):
        return self.producto

    @property
    def datos_ml(self) -> dict:
        import json
        try:
            return json.loads(self.atributos_ml or "{}")
        except ValueError:
            return {}

    @property
    def origen_datos_ml(self) -> dict:
        import json
        try:
            return json.loads(self.atributos_origen or "{}")
        except ValueError:
            return {}

    @property
    def tiene_propuestas(self):
        return self.categoria_propuesta or self.marca_propuesta or self.titulo_propuesta or self.descripcion_propuesta

    class Meta:
        verbose_name = "Producto ML"
        verbose_name_plural = "Productos ML"
        ordering = ["hoja", "fila"]


class MovimientoStock(models.Model):
    """
    Registro de cada cambio de stock enviado a Odoo desde el Gestor (ver
    modules/servidor/registro_stock.py). Solo se agregan filas, nunca se editan.
    """
    id = CustomAutoField(primary_key=True, verbose_name="ID", null=False, blank=False, editable=False)
    fecha = CustomDateTimeField(verbose_name="Fecha", auto_now_add=True, column_width=170, is_sortable=True)
    origen = CustomCharField(max_length=100, verbose_name="Origen", default="", column_width=230, is_sortable=True, is_searchable=True)
    lote = CustomCharField(max_length=20, verbose_name="Lote", default="", blank=True, column_width=100, is_sortable=True, is_searchable=True)
    ref_interna = CustomCharField(max_length=100, verbose_name="REF Interna", default="", blank=True, column_width=130, is_sortable=True, is_searchable=True)
    producto = CustomCharField(max_length=255, verbose_name="Producto", default="", blank=True, column_width=280, is_sortable=True, is_searchable=True)
    stock_anterior = CustomIntegerField(verbose_name="Stock Anterior", null=True, blank=True, column_width=120)
    valor_ingresado = CustomIntegerField(verbose_name="Valor Ingresado", null=True, blank=True, column_width=120)
    tipo = CustomCharField(max_length=20, verbose_name="Tipo", default="", blank=True, column_width=100)
    stock_final = CustomIntegerField(verbose_name="Stock Final", null=True, blank=True, column_width=110)
    estado = CustomCharField(max_length=20, verbose_name="Estado", default="", column_width=100, is_sortable=True, is_searchable=True)
    mensaje = CustomCharField(max_length=255, verbose_name="Mensaje", default="", blank=True, column_width=300)
    detalle = CustomCharField(max_length=255, verbose_name="Detalle del lote", default="", blank=True, column_width=380)
    equipo = CustomCharField(max_length=100, verbose_name="Usuario / Equipo", default="", blank=True, column_width=200, is_searchable=True)
    producto_id = CustomIntegerField(verbose_name="ID Producto", default=0, hidden=True)

    def __str__(self):
        return f"{self.fecha:%d-%m-%Y %H:%M} {self.producto}: {self.stock_anterior} → {self.stock_final}"

    @property
    def name(self):
        return self.producto

    class Meta:
        verbose_name = "Movimiento de Stock"
        verbose_name_plural = "Registro de Movimientos de Stock"
        ordering = ["-fecha", "-id"]
