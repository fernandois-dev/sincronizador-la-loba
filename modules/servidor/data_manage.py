# -*- coding: utf-8 -*-
"""
esta clase gestionara la informacion obtenida desde odoo y la almacenara en la base de datos local.
"""

from datetime import datetime 
import json
import os
from .models import Comparativa, OdooProducto, OdooTarifa, OdooProveedor, OdooRuta, TablaBase
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection


class DataManage():

    @staticmethod
    def _convert_to_numeric(value, default=0):
        """
        Convierte un valor a numérico de forma segura.
        Maneja strings, integers, floats y valores None.
        
        Args:
            value: El valor a convertir
            default: Valor por defecto si la conversión falla
            
        Returns:
            float: Valor numérico convertido o el valor por defecto
        """
        if value is None:
            return default
            
        # Si ya es un número, validar que sea >= 0
        if isinstance(value, (int, float)):
            return value if value >= 0 else default
            
        # Si es string, intentar convertir
        if isinstance(value, str):
            # Limpiar el string: remover espacios y caracteres no numéricos comunes
            cleaned_value = value.strip().replace(',', '').replace(' ', '')
            
            # Si está vacío después de limpiar, retornar default
            if not cleaned_value:
                return default
                
            try:
                # Intentar convertir a float primero (maneja decimales)
                numeric_value = float(cleaned_value)
                return numeric_value if numeric_value >= 0 else default
            except (ValueError, TypeError):
                return default
                
        # Para cualquier otro tipo, retornar default
        return default

    @staticmethod
    def save_productos_odoo(products):
        # primero limpiamos la tabla de productos
        OdooProducto.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de OdooProducto
            productos_objs = [
                OdooProducto(
                    id=product.get("id"),
                    name=product.get("name"),
                    list_price=product.get("list_price"),
                    barcode=product.get("barcode"),
                    categ_id=product.get("categ_id"),
                    qty_available=product.get("qty_available"),
                    virtual_available=product.get("virtual_available"),
                    incoming_qty=product.get("incoming_qty"),
                    outgoing_qty=product.get("outgoing_qty"),
                    default_code=product.get("default_code"),
                    activo=product.get("sale_ok", True),
                    favorito=bool(product.get("is_favorite", False)),
                )
                for product in products
            ]
            # Guardamos todos los productos de una vez
            OdooProducto.objects.bulk_create(productos_objs)
            _avisar_indice_ia("recarga de productos de Odoo")
            
        except Exception as e:
            print(f"Error al guardar productos de Odoo: {e}")
            raise e
    
    @staticmethod    
    def save_tarifas_odoo(tarifas):
        # primero limpiamos la tabla de tarifas
        OdooTarifa.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de OdooTarifa
            tarifas_objs = [
                OdooTarifa(
                    id=tarifa.get("id"),
                    partner_id=tarifa.get("partner_id")[0] if tarifa.get("partner_id") else 0,
                    partner=tarifa.get("partner_id")[1] if tarifa.get("partner_id") else "",
                    product_tmpl_id=tarifa.get("product_tmpl_id")[0] if tarifa.get("product_tmpl_id") else 0,
                    product_tmpl=tarifa.get("product_tmpl_id")[1] if tarifa.get("product_tmpl_id") else "",
                    price=tarifa.get("price"),
                    sequence=tarifa.get("sequence"),
                    product_code=tarifa.get("product_code") or "",
                )
                for tarifa in tarifas
            ]
            # Guardamos todas las tarifas de una vez
            OdooTarifa.objects.bulk_create(tarifas_objs)
            
        except Exception as e:
            print(f"Error al guardar tarifas de Odoo: {e}")
            raise e

    @staticmethod
    def save_rutas_odoo(reglas):
        # primero limpiamos la tabla de reglas
        OdooRuta.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de OdooRegla
            reglas_objs = [
                OdooRuta(
                    id=regla.get("id"),
                    product_id=regla.get("product_id")[0] if regla.get("product_id") else 0,
                    product=regla.get("product_id")[1] if regla.get("product_id") else "",
                    product_tmpl_id=regla.get("product_tmpl_id")[0] if regla.get("product_tmpl_id") else 0,
                    location_id=regla.get("location_id")[0] if regla.get("location_id") else 8,
                    product_min_qty=regla.get("product_min_qty"),
                    product_max_qty=regla.get("product_max_qty"),
                )
                for regla in reglas
            ]
            # Guardamos todas las reglas de una vez
            OdooRuta.objects.bulk_create(reglas_objs)
            
        except Exception as e:
            print(f"Error al guardar reglas de Odoo: {e}")
            raise e
        
    @staticmethod  
    def save_proveedores_odoo(proveedores):
        # primero limpiamos la tabla de proveedores
        OdooProveedor.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de OdooProveedor
            proveedores_objs = [
                OdooProveedor(
                    id=proveedor.get("id"),
                    name=proveedor.get("name"),
                )
                for proveedor in proveedores
            ]
            # Guardamos todos los proveedores de una vez
            OdooProveedor.objects.bulk_create(proveedores_objs)
            
        except Exception as e:
            print(f"Error al guardar proveedores de Odoo: {e}")
            raise e
        
    @staticmethod
    def save_all_odoo_data(products, tarifas, rutas, proveedores):
        DataManage.save_productos_odoo(products)
        DataManage.save_tarifas_odoo(tarifas)
        DataManage.save_rutas_odoo(rutas)
        DataManage.save_proveedores_odoo(proveedores)
        
    @staticmethod
    def set_data_tabla_base(data):
        """
        Guarda la data de la tabla base en la base de datos local.
        """
        # Primero limpiamos la tabla base
        TablaBase.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de TablaBase
            tabla_base_objs = [
                TablaBase(
                    procesar=True,
                    descripcion=item.get("PRODUCTO", "").upper().replace("   "," ").replace("  "," ").lstrip().rstrip(),
                    precio=DataManage._convert_to_numeric(item.get("VENTA FLB", 0)),
                    stock=DataManage._convert_to_numeric(item.get("STOCK", 0)),
                    barcode=item.get("CODIGO BARRAS", ""),
                    categoria=item.get("CATEGORIA", ""),
                    ref_interna=item.get("REF INTERNA", ""),
                    proveedor_id=item.get("PROVEEDOR_ID", ""),
                    proveedor_descripcion=item.get("PROVEEDOR", ""),
                    precio_compra=DataManage._convert_to_numeric(item.get("$ Final", 0)),
                    # valida que min sea numerico y mayor que 0, si no, lo pone en 0
                    cant_min=DataManage._convert_to_numeric(item.get("MIN", 0)),
                    cant_max=DataManage._convert_to_numeric(item.get("MAX", 0)),
                    activo=item.get("ACTIVO", True) if isinstance(item.get("ACTIVO", True), bool) else True,
                    hoja_seleccionada=item.get("HOJA_SELECCIONADA", ""),
                    cantidad_compra=DataManage._convert_to_numeric(item.get("CANT. COMP", 0)),
                    precio_mayor=DataManage._convert_to_numeric(item.get("PRECIO POR MAYOR", 0)),
                    uds_agrupamiento=DataManage._convert_to_numeric(item.get("N° DE UDS", 0)),
                )
                for item in data if item.get("PRODUCTO", "").strip() != "" and DataManage._convert_to_numeric(item.get("VENTA FLB", 0)) > 0
            ]
            # Guardamos todos los items de la tabla base de una vez
            TablaBase.objects.bulk_create(tabla_base_objs)
            
        except Exception as e:
            print(f"Error al guardar datos en Tabla Base: {e}")
            raise e

    @staticmethod
    def compare_data_with_odoo():
        """
        Cruza cada fila de la tabla base con su producto de Odoo y regenera Comparativa.

        Una fila (hoja de un proveedor + REF INTERNA) se vincula a un producto:
          1. por su línea de proveedor en Odoo: proveedor de la hoja + código
             del proveedor (product.supplierinfo.product_code) = REF de la fila.
             Así un producto que se compra a varios proveedores queda vinculado
             a las filas de todas sus hojas, cada una con su propia REF.
          2. si no, por REF INTERNA = referencia interna del producto (default_code).
        """
        def clave(valor):
            return str(valor or "").strip().upper()

        productos = {p.id: p for p in OdooProducto.objects.all()}
        producto_por_ref = {}
        for p in productos.values():
            if p.default_code:
                producto_por_ref.setdefault(clave(p.default_code), p)

        tarifas_por_producto = {}
        tarifa_por_codigo = {}
        for t in OdooTarifa.objects.order_by("sequence", "id"):
            tarifas_por_producto.setdefault(t.product_tmpl_id, []).append(t)
            if t.product_code:
                tarifa_por_codigo.setdefault((t.partner_id, clave(t.product_code)), t)

        ruta_por_producto = {}
        ruta_por_nombre = {}
        for r in OdooRuta.objects.order_by("id"):
            if r.product_tmpl_id:
                ruta_por_producto.setdefault(r.product_tmpl_id, r)
            # Respaldo para reglas guardadas antes de tener product_tmpl_id
            # (hasta el próximo "Cargar Odoo"): se cruzan por "[REF] nombre".
            ruta_por_nombre.setdefault(r.product, r)

        def ruta_de(producto):
            return (ruta_por_producto.get(producto.id)
                    or ruta_por_nombre.get(f"[{(producto.default_code or '').strip()}] {(producto.name or '').strip()}"))

        proveedores = {}
        ids_proveedores = set(OdooProveedor.objects.values_list("id", flat=True))

        def proveedor_de(tb):
            llave = (tb.proveedor_id, tb.proveedor_descripcion)
            if llave not in proveedores:
                proveedores[llave] = DataManage._get_proveedor_safe(tb.proveedor_id, tb.proveedor_descripcion)
            return proveedores[llave]

        tabla_base_objs = []
        for tb in TablaBase.objects.all():
            proveedor = proveedor_de(tb)
            ref = clave(tb.ref_interna)

            tarifa_fila = tarifa_por_codigo.get((proveedor.id, ref)) if proveedor and ref else None
            if tarifa_fila:
                producto = productos.get(tarifa_fila.product_tmpl_id)
            else:
                producto = producto_por_ref.get(ref) if ref else None
            if producto and not tarifa_fila and proveedor:
                tarifa_fila = next((t for t in tarifas_por_producto.get(producto.id, [])
                                    if t.partner_id == proveedor.id), None)

            # Para mostrar se usa la tarifa del proveedor de la hoja; si aún no
            # existe, la principal del producto (como antes).
            tarifas = tarifas_por_producto.get(producto.id, []) if producto else []
            tarifa = tarifa_fila or (tarifas[0] if tarifas else None)
            ruta = ruta_de(producto) if producto else None

            tabla_base_objs.append(Comparativa(
                ref_interna=tb.ref_interna,
                producto=tb.descripcion,
                producto_id=producto.id if producto else None,
                existe=producto is not None,
                desc_ok=bool(producto and producto.name == tb.descripcion),
                odoo_producto=producto.name if producto else None,
                tb_precio=tb.precio,
                odoo_precio=producto.list_price if producto else None,
                tb_stock=tb.stock,
                odoo_stock=producto.qty_available if producto else None,
                tb_barcode=tb.barcode,
                odoo_barcode=producto.barcode if producto else None,
                tb_proveedor=proveedor,
                odoo_proveedor_id=tarifa.partner_id if tarifa and tarifa.partner_id in ids_proveedores else None,
                tb_precio_compra=tb.precio_compra,
                odoo_precio_compra=tarifa.price if tarifa else None,
                tb_min=tb.cant_min,
                odoo_min=ruta.product_min_qty if ruta else None,
                tb_max=tb.cant_max,
                odoo_max=ruta.product_max_qty if ruta else None,
                ruta_id=ruta.id if ruta else None,
                tb_activo=tb.activo,
                odoo_activo=bool(producto and producto.activo),
                # Ya vienen como Decimal desde TablaBase (validados al cargar la hoja);
                # _convert_to_numeric no reconoce Decimal y los dejaría en 0.
                cantidad_compra=tb.cantidad_compra or 0,
                precio_mayor=tb.precio_mayor or 0,
                uds_agrupamiento=tb.uds_agrupamiento or 0,
                tarifa_id=tarifa_fila.id if tarifa_fila else None,
                odoo_codigo_proveedor=(tarifa_fila.product_code or "") if tarifa_fila else "",
            ))

        Comparativa.objects.all().delete()
        try:
            Comparativa.objects.bulk_create(tabla_base_objs)
        except Exception as e:
            print(f"Error al guardar datos en Tabla Base: {e}")
            raise e

    @staticmethod
    def _get_proveedor_safe(proveedor_id, proveedor_descripcion=None):
        """
        Obtiene un proveedor de forma segura, retornando None si no existe
        """
        if not proveedor_id:
            # intenta encontrar el proveedor por descripción
            if proveedor_descripcion:
                try:
                    return OdooProveedor.objects.get(name=proveedor_descripcion)
                except ObjectDoesNotExist:
                    return None
            else:
                # Si no hay ID ni descripción, retornamos None
                return None
        try:
            return OdooProveedor.objects.get(id=proveedor_id)
        except (ObjectDoesNotExist, ValueError, TypeError):
            return None
        
    def save_oc_data(ocs):
        # primero limpiamos la tabla de ordenes de compra
        from .models import CompraOdoo  # Import here to avoid circular import
        CompraOdoo.objects.all().delete()
        
        try:
            # Creamos una lista de instancias de OdooOrdenCompra
            ocs_objs = [
                CompraOdoo(
                    id=oc.get("id"),
                    fecha=datetime.strptime(oc.get("date_order")[:19], "%Y-%m-%d %H:%M:%S") if oc.get("date_order") else None,
                    proveedor=oc.get("partner_id")[1] if oc.get("partner_id") else "",
                    total=oc.get("amount_total"),
                    iva=oc.get("amount_tax"),
                    neto=oc.get("amount_untaxed"),
                    estado=oc.get("state"),
                )
                for oc in ocs
            ]
            # Guardamos todas las ordenes de compra de una vez
            CompraOdoo.objects.bulk_create(ocs_objs)

        except Exception as e:
            print(f"Error al guardar ordenes de compra de Odoo: {e}")
            raise e
        
    @staticmethod
    def get_disabled_products():
        """Obtiene la lista de IDs de productos deshabilitados localmente"""
        file_path = os.path.join("data", "disabled_products.json")
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r") as f:
                return json.load(f)
        except Exception as e:
            print(f"Error al leer productos deshabilitados: {e}")
            return []

    @staticmethod
    def save_disabled_products(disabled_ids):
        """Guarda la lista de IDs de productos deshabilitados localmente"""
        file_path = os.path.join("data", "disabled_products.json")
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        try:
            with open(file_path, "w") as f:
                json.dump(list(set(disabled_ids)), f)
        except Exception as e:
            print(f"Error al guardar productos deshabilitados: {e}")
            raise e

    @staticmethod
    def reporte_stock(proveedor:int = None, producto:str = None, riesgo:str = None, favorito:bool = None, activo:bool = None):
        """
        Genera un reporte de stock con información de productos, proveedores y estado de riesgo.
        
        Returns:
            list: Lista de diccionarios con la información del reporte
        """
        def dictfetchall(cursor):
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        results = []
        # crear filtros SQL
        filtros = []
        if proveedor:
            filtros.append(f"proveedor_id = '{proveedor}'")
        if producto:
            filtros.append(f"producto LIKE '%{producto}%'")
        if riesgo:
            filtros.append(f"riesgo LIKE '%{riesgo}%'")
        if favorito is not None:
            filtros.append(f"favorito = {1 if favorito else 0}")
        if activo is not None:
            filtros.append(f"activo = {1 if activo else 0}")
        filtro_sql = " AND ".join(filtros)
        if filtro_sql:
            filtro_sql = "WHERE " + filtro_sql
        
        disabled_ids = DataManage.get_disabled_products()
        
        with connection.cursor() as cursor:
            cursor.execute(f"""select * from (
            SELECT distinct p.id, p.name producto, p.list_price precio, t.price precio_compra, p.qty_available stock, p.incoming_qty stock_entrando, p.outgoing_qty stock_saliendo, 
            p.virtual_available stock_proyeccion, so.product_min_qty stock_min, so.product_max_qty stock_max, t.partner proveedor, t.partner_id proveedor_id,
                            case 
                    when qty_available < so.product_min_qty then "CRITICO" 
                    when qty_available >= so.product_min_qty and qty_available <= so.product_min_qty * 1.2 then "SOLICITAR" 
                    ELSE "OK"
                END AS riesgo, activo, favorito
                FROM servidor_odooproducto p 
                join servidor_odooruta so on (so.product = concat("[",p.default_code,"] ", p.name))
                join servidor_odootarifa t on (t.product_tmpl_id = p.id) where p.activo = true ) as subquery
                {filtro_sql}""")
            results = dictfetchall(cursor)
        
        # Aplicar estado deshabilitado localmente
                
        return results
    
    @staticmethod
    def get_proveedores_con_productos():
        """
        Obtiene la lista de proveedores que tienen productos asociados en Odoo.
        
        Returns:
            QuerySet: Conjunto de proveedores con productos asociados
        """
        from .models import OdooProveedor
        return OdooProveedor.objects.filter(id__in=OdooTarifa.objects.values_list('partner_id', flat=True).distinct())
    
    @staticmethod
    def set_favorito_producto(product_id:int, favorito:bool):
        """
        Establece el estado de favorito de un producto.
        
        Args:
            product_id (int): ID del producto
            favorito (bool): Estado de favorito a establecer
        """
        try:
            producto = OdooProducto.objects.get(id=product_id)
            producto.favorito = favorito
            producto.save()
            return {"state":"S", "msg":"Producto actualizado correctamente"}
        except OdooProducto.DoesNotExist:
            print(f"Producto con ID {product_id} no existe.")
            return {"state":"E", "msg":"Producto no existe"}
        except Exception as e:
            print(f"Error al actualizar favorito del producto: {e}")
            return {"state":"E", "msg":"Error al actualizar favorito del producto"}
            
    @staticmethod
    def update_stock_limits(product_id: int, min_qty: float, max_qty: float):
        """
        Actualiza los límites de stock (mínimo y máximo) para un producto.
        """
        from .models import OdooRuta, OdooProducto
        from .odoo import OdooService
        try:
            #obtengo producto por id
            producto = OdooProducto.objects.get(id=product_id)

            # Buscamos las rutas asociadas al producto por su descripción [código] nombre
            product_str = f"[{producto.default_code}] {producto.name}"
            rutas = OdooRuta.objects.filter(product=product_str)
            
            if rutas.exists():
                for ruta in rutas:
                    # Actualizar localmente
                    ruta.product_min_qty = min_qty
                    ruta.product_max_qty = max_qty
                    ruta.save()
                    
                    # Actualizar en Odoo
                    OdooService.set_rutas({
                        "id": ruta.id,
                        "product_min_qty": min_qty,
                        "product_max_qty": max_qty,
                        "product_id": producto.id
                    })
                return True
            else:
                # Si no existen rutas locales, intentamos crear una nueva en Odoo directamente
                # Usamos una ubicación por defecto (8) como se ve en otros procesos de carga
                res = OdooService.set_rutas({
                    "id": None,
                    "product_min_qty": min_qty,
                    "product_max_qty": max_qty,
                    "product_id": producto.id,
                    "location_id": 8
                })
                return res.get("state") == "S"

        except Exception as e:
            print(f"Error al actualizar límites de stock: {e}")
            return False
        
    @staticmethod
    def productos_proveedor(proveedor:int = None, producto:str = None, favorito:bool = None, activo:bool = None):
        """
        Genera un reporte de stock con información de productos, proveedores y estado de riesgo.
        
        Returns:
            list: Lista de diccionarios con la información del reporte
        """
        def dictfetchall(cursor):
            columns = [col[0] for col in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]
        
        results = []
        # crear filtros SQL
        filtros = []
        if proveedor:
            filtros.append(f"proveedor_id = '{proveedor}'")
        if producto:
            filtros.append(f"producto LIKE '%{producto}%'")
        if favorito is not None:
            filtros.append(f"favorito = {1 if favorito else 0}")
        if activo is not None:
            filtros.append(f"activo = {1 if activo else 0}")
        filtro_sql = " AND ".join(filtros)
        if filtro_sql:
            filtro_sql = "WHERE " + filtro_sql
        
        disabled_ids = DataManage.get_disabled_products()
        
        with connection.cursor() as cursor:
            cursor.execute(f"""select * from (
    SELECT distinct p.id, p.name producto, p.favorito, p.activo, p.list_price precio, t.partner proveedor, t.partner_id proveedor_id
        FROM servidor_odooproducto p 
        join servidor_odootarifa t on (t.product_tmpl_id = p.id) order by p.favorito desc) as subquery
                {filtro_sql}""")
            results = dictfetchall(cursor)
                
        return results


def _avisar_indice_ia(motivo: str):
    """Pone al día el índice del asistente IA en segundo plano. Si algo falla, no afecta la sincronización."""
    try:
        from modules.ia.indexador import actualizar_en_segundo_plano
        actualizar_en_segundo_plano(motivo)
    except Exception:  # noqa: BLE001
        from logger_config import get_logger
        get_logger(__name__).warning("No se pudo avisar al índice IA", exc_info=True)
