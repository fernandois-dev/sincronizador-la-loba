import asyncio
"""
Módulo de lógica de negocio para el sistema de gestión La Loba.
Contiene funciones reutilizables para operaciones comunes del negocio.
"""

from datetime import datetime, timedelta
import time
import flet as ft

from utilities import pendientes
from utilities.flet_compat import abrir_dialogo, abrir_unico, tarea_async
from logger_config import get_logger

logger = get_logger(__name__)
from django.db import transaction
from django.db.models import Q
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import HojasSeleccionadas, ResumenCompraProducto, ResumenVentaProducto, TablaBase, Comparativa, MovimientoProductoMes
from modules.servidor.odoo import OdooService


class TablaBaseManager:
    """
    Clase para manejar la lógica de negocio relacionada con la carga de tabla base
    """
    
    @staticmethod
    def leer_tabla_base(hojas_seleccionadas):
        """Lee las hojas de Google y guarda la Tabla Base y la Comparativa (sin pantalla).

        Bloquea: llamarla desde un hilo o con asyncio.to_thread.
        Devuelve las filas leídas (lista vacía si no hay datos).
        """
        with transaction.atomic():
            all_data = []
            for hoja in hojas_seleccionadas:
                logger.debug("Leyendo hoja Google Sheets: '%s'", hoja)
                proveedor = GoogleService.get_proveedor(hoja)
                hoja_nueva = TablaBaseManager.agregar_hoja_seleccionada({"hoja": hoja, "proveedor_id": proveedor["id"]})
                data = [{**item, "HOJA_SELECCIONADA": hoja_nueva} for item in GoogleService.get_data(hoja)]
                if proveedor["id"]:
                    data = [{**item, "PROVEEDOR_ID": proveedor["id"]} for item in data]
                logger.debug("Hoja '%s': %d filas obtenidas.", hoja, len(data))
                all_data.extend(data)
            if not all_data:
                return all_data
            DataManage.set_data_tabla_base(all_data)
            DataManage.compare_data_with_odoo()
            return all_data

    @staticmethod
    @tarea_async
    async def cargar_tabla_base(page, hojas_seleccionadas=None, update_view_callback=None, loading_widget=None):
        """
        Carga la tabla base con las hojas seleccionadas desde Google Sheets
        
        Args:
            hojas_seleccionadas (list): Lista de nombres de hojas a cargar
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la carga fue exitosa, False en caso contrario
        """
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Cargando datos de Google Sheets...")
        
        if hojas_seleccionadas is None:
            hojas_seleccionadas = TablaBaseManager.obtener_hojas_seleccionadas()
        await asyncio.sleep(3)
        try:
            logger.info("Iniciando carga de tabla base. Hojas: %s", hojas_seleccionadas)

            # Google y la base corren en un hilo; la pantalla se actualiza aquí, en el loop.
            all_data = await asyncio.to_thread(TablaBaseManager.leer_tabla_base, hojas_seleccionadas)
            if not all_data:
                logger.warning("No se encontraron datos en las hojas seleccionadas: %s", hojas_seleccionadas)
                abrir_unico(page, ft.SnackBar(ft.Text("No se encontraron datos en las hojas seleccionadas.")))
                if loading_widget:
                    loading_widget.hide()
                return False

            logger.info("Tabla base cargada correctamente. Total filas: %d", len(all_data))
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)
            if loading_widget:
                loading_widget.hide()
            return True

        except Exception as e:
            logger.error("Error al cargar tabla base desde Google Sheets.", exc_info=True)
            if loading_widget:
                loading_widget.hide()
            abrir_unico(page, ft.SnackBar(ft.Text(f"Error al cargar datos: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False


    @staticmethod
    def obtener_hojas_seleccionadas():
        """
        Obtiene las hojas seleccionadas desde la base de datos
        
        Returns:
            list: Lista de nombres de hojas seleccionadas
        """
        return list(HojasSeleccionadas.objects.values_list('hoja', flat=True))

    @staticmethod
    def agregar_hoja_seleccionada(hoja_seleccionada):
        """
        Guarda las hojas seleccionadas en la base de datos
        
        Args:
            hojas_seleccionadas (list): Lista de nombres de hojas seleccionadas
        """
        # si no existe la hoja, la crea
        if HojasSeleccionadas.objects.filter(hoja=hoja_seleccionada["hoja"]).exists():
            return HojasSeleccionadas.objects.get(hoja=hoja_seleccionada["hoja"])
        hoja = HojasSeleccionadas(hoja=hoja_seleccionada["hoja"], proveedor_id=hoja_seleccionada["proveedor_id"])
        hoja.save()
        return hoja


    @staticmethod
    def eliminar_todas_las_hojas_seleccionadas():
        """
        Elimina todas las hojas seleccionadas de la base de datos
        """
        HojasSeleccionadas.objects.all().delete()

    @staticmethod
    @tarea_async
    async def limpiar_tablas(page, update_view_callback=None, loading_widget=None):
        """
        Limpia las tablas HojasSeleccionadas, TablaBase y Comparativa
        
        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la limpieza fue exitosa, False en caso contrario
        """
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Limpiando tablas...")
        
        try:
            logger.info("Limpiando tablas HojasSeleccionadas, TablaBase y Comparativa.")
            def limpiar():
                with transaction.atomic():
                    HojasSeleccionadas.objects.all().delete()
                    TablaBase.objects.all().delete()
                    Comparativa.objects.all().delete()

            await asyncio.to_thread(limpiar)
            logger.info("Tablas limpiadas correctamente.")
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)
            if loading_widget:
                loading_widget.hide()
            abrir_unico(page, ft.SnackBar(ft.Text("Tablas limpiadas correctamente.")))
            return True

        except Exception as e:
            logger.error("Error al limpiar tablas.", exc_info=True)
            if loading_widget:
                loading_widget.hide()
            abrir_unico(page, ft.SnackBar(ft.Text(f"Error al limpiar tablas: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False
        
    @staticmethod
    @tarea_async
    async def elimina_hoja_seleccionada(hoja, page, update_view_callback=None, loading_widget=None):
        """
        Elimina la hoja seleccionada de la base de datos

        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la eliminación fue exitosa, False en caso contrario
        """
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Eliminando hoja seleccionada...")
        
        try:
            logger.info("Eliminando hoja seleccionada: '%s'", hoja)
            def eliminar():
                HojasSeleccionadas.objects.filter(hoja=hoja).delete()
                Comparativa.objects.all().delete()
                DataManage.compare_data_with_odoo()

            await asyncio.to_thread(eliminar)
            logger.info("Hoja '%s' eliminada. Comparativa recalculada.", hoja)
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)
            if loading_widget:
                loading_widget.hide()
            abrir_unico(page, ft.SnackBar(ft.Text("Hoja seleccionada eliminada correctamente.")))
            return True

        except Exception as e:
            logger.error("Error al eliminar hoja seleccionada '%s'.", hoja, exc_info=True)
            if loading_widget:
                loading_widget.hide()
            abrir_unico(page, ft.SnackBar(ft.Text(f"Error al eliminar hoja seleccionada: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False


class ConteoManager:
    """
    Clase para manejar la lógica de negocio relacionada con la carga de conteos
    físicos de stock registrados por proveedor en la app de conteo (Google Sheets).
    """

    _PALABRAS_IGNORADAS = {
        "SPA", "LTDA", "LIMITADA", "COMPAÑIA", "COMPANIA", "COMERCIAL",
        "COMERCIALIZADORA", "IMPORTADORA", "IMPORT", "Y", "DE", "DEL",
    }

    @staticmethod
    def _normalizar(texto):
        import re
        return re.sub(r"[^A-Z0-9]", "", (texto or "").upper())

    @staticmethod
    def _tokens_significativos(nombre):
        import re
        return [
            p for p in re.split(r"\s+", (nombre or "").upper())
            if len(p) > 3 and p not in ConteoManager._PALABRAS_IGNORADAS and not p.isdigit()
        ]

    @staticmethod
    def buscar_hoja_conteo(nombre_hoja_tb):
        """
        Busca la pestaña del workbook de conteo cuyo nombre calza mejor con
        el nombre de la hoja de tabla base cargada (ej. "ORING PULGADAS 2025"
        -> pestaña "ORING PULGADAS 2025" o similar; no siempre son idénticas).
        El match es por nombre de hoja, no por nombre de proveedor: la app de
        conteo nombra sus pestañas igual que la tabla base, no como la razón
        social del proveedor en Odoo.

        Se usa un puntaje por cantidad de palabras coincidentes (en vez de
        "la primera que calce con alguna palabra") porque varias pestañas
        pueden compartir una palabra genérica (ej. "ORING PULGADAS 2025" y
        "ORING MILIMET.2025" comparten "ORING"); se elige la que más
        palabras específicas tiene en común. Compara en ambas direcciones
        porque a veces el nombre coincidente queda "pegado" dentro de una
        sola palabra compuesta (sin espacios).
        """
        hojas = GoogleService.get_hojas_conteo()

        # 1) Match exacto (ignorando mayúsculas/espacios) tiene prioridad absoluta.
        tb_norm_simple = (nombre_hoja_tb or "").strip().upper()
        for hoja in hojas:
            if (hoja or "").strip().upper() == tb_norm_simple:
                return hoja

        # 2) Match por mejor puntaje de palabras coincidentes.
        tb_blob = ConteoManager._normalizar(nombre_hoja_tb)
        tb_tokens = ConteoManager._tokens_significativos(nombre_hoja_tb)

        mejor_hoja = None
        mejor_puntaje = 0
        for hoja in hojas:
            hoja_blob = ConteoManager._normalizar(hoja)
            hoja_tokens = ConteoManager._tokens_significativos(hoja)
            puntaje = (
                sum(1 for t in tb_tokens if ConteoManager._normalizar(t) in hoja_blob)
                + sum(1 for t in hoja_tokens if ConteoManager._normalizar(t) in tb_blob)
            )
            if puntaje > mejor_puntaje:
                mejor_puntaje = puntaje
                mejor_hoja = hoja
        return mejor_hoja

    @staticmethod
    def obtener_hoja_actual():
        """
        Retorna el nombre de la hoja de tabla base actualmente cargada, o None
        si no hay ninguna cargada o hay más de una distinta.
        """
        hojas = list(HojasSeleccionadas.objects.values_list('hoja', flat=True).distinct())
        if len(hojas) == 1:
            return hojas[0]
        return None

    @staticmethod
    def cargar_conteo_proveedor(nombre_hoja_tb):
        """
        Busca la hoja de conteo correspondiente a la hoja de tabla base cargada
        y la matchea contra los productos ya cargados en Comparativa (por REF INTERNA).

        Returns:
            tuple: (nombre_hoja_encontrada | None, [(Comparativa, nuevo_stock), ...])
        """
        hoja = ConteoManager.buscar_hoja_conteo(nombre_hoja_tb)
        if not hoja:
            return None, []

        datos_conteo = GoogleService.get_ultimo_conteo(hoja)
        if not datos_conteo:
            return hoja, []

        conteo_por_ref = {}
        for d in datos_conteo:
            ref = (d.get("ref_interna") or "").strip().upper()
            if ref:
                conteo_por_ref[ref] = d["stock"]

        filas = []
        for obj in Comparativa.objects.all():
            ref = (obj.ref_interna or "").strip().upper()
            if ref in conteo_por_ref:
                filas.append((obj, conteo_por_ref[ref]))
        return hoja, filas


class OdooSyncManager:
    """
    Clase para manejar la lógica de negocio relacionada con la sincronización con Odoo
    """

    @staticmethod
    @tarea_async
    async def cargar_datos_odoo_completo(page, update_view_callback=None, loading_widget=None):
        """
        Carga todos los datos de Odoo (productos, tarifas, rutas, proveedores)
        
        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la carga fue exitosa, False en caso contrario
        """
        from modules.servidor.odoo import OdooService
        
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Cargando datos de Odoo...")
        
        try:
            logger.info("Iniciando carga completa de datos desde Odoo (productos, tarifas, rutas, proveedores).")
            def cargar():
                DataManage.save_all_odoo_data(
                    products=OdooService.get_productos(),
                    tarifas=OdooService.get_tarifas(),
                    rutas=OdooService.get_rutas(),
                    proveedores=OdooService.get_proveedores()
                )
                DataManage.compare_data_with_odoo()

            await asyncio.to_thread(cargar)
            logger.info("Carga completa de Odoo finalizada correctamente.")
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            return True

        except Exception as e:
            logger.error("Error al cargar datos completos desde Odoo.", exc_info=True)
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False

    @staticmethod
    @tarea_async
    async def cargar_productos_odoo(page, update_view_callback=None, loading_widget=None):
        """
        Carga solo los productos de Odoo
        
        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la carga fue exitosa, False en caso contrario
        """
        from modules.servidor.odoo import OdooService
        
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Cargando datos de Odoo...")

        try:
            logger.info("Iniciando carga de productos desde Odoo.")
            def cargar():
                DataManage.save_productos_odoo(products=OdooService.get_productos())
                DataManage.compare_data_with_odoo()

            await asyncio.to_thread(cargar)
            logger.info("Carga de productos Odoo finalizada correctamente.")
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            return True

        except Exception as e:
            logger.error("Error al cargar productos desde Odoo.", exc_info=True)
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False

    @staticmethod
    def actualizar_precio_producto_local(producto_id, nuevo_precio):
        """
        Actualiza el precio de un producto localmente tanto en OdooProducto como en Comparativa
        """
        from modules.servidor.models import OdooProducto, Comparativa
        try:
            with transaction.atomic():
                # Actualizar el producto en nuestra caché local de Odoo
                OdooProducto.objects.filter(id=producto_id).update(list_price=nuevo_precio)
                # Actualizar la tabla de comparativa para que refleje el cambio inmediatamente
                Comparativa.objects.filter(producto_id=producto_id).update(odoo_precio=nuevo_precio)
            return True
        except Exception as e:
            logger.error("Error al actualizar precio local (producto_id=%s).", producto_id, exc_info=True)
            return False

    @staticmethod
    def actualizar_nombre_producto_local(producto_id, nuevo_nombre):
        """
        Actualiza el nombre de un producto localmente (OdooProducto y Comparativa)
        y marca desc_ok=True para que desaparezca del listado de diferencias.
        """
        from modules.servidor.models import OdooProducto, Comparativa
        try:
            with transaction.atomic():
                OdooProducto.objects.filter(id=producto_id).update(name=nuevo_nombre)
                Comparativa.objects.filter(producto_id=producto_id).update(
                    odoo_producto=nuevo_nombre, desc_ok=True,
                )
            return True
        except Exception as e:
            logger.error("Error al actualizar nombre local (producto_id=%s).", producto_id, exc_info=True)
            return False

    @staticmethod
    def actualizar_barcode_producto_local(producto_id, nuevo_barcode):
        """
        Actualiza el código de barras de un producto localmente tanto en OdooProducto como en Comparativa
        """
        from modules.servidor.models import OdooProducto, Comparativa
        try:
            with transaction.atomic():
                OdooProducto.objects.filter(id=producto_id).update(barcode=nuevo_barcode)
                Comparativa.objects.filter(producto_id=producto_id).update(odoo_barcode=nuevo_barcode)
            return True
        except Exception as e:
            logger.error("Error al actualizar barcode local (producto_id=%s).", producto_id, exc_info=True)
            return False

    @staticmethod
    def actualizar_activo_producto_local(producto_id, activo):
        """
        Actualiza el estado activo de un producto localmente tanto en OdooProducto como en Comparativa
        """
        from modules.servidor.models import OdooProducto, Comparativa
        try:
            with transaction.atomic():
                OdooProducto.objects.filter(id=producto_id).update(activo=activo)
                Comparativa.objects.filter(producto_id=producto_id).update(odoo_activo=activo)
            return True
        except Exception as e:
            logger.error("Error al actualizar activo local (producto_id=%s).", producto_id, exc_info=True)
            return False

    @staticmethod
    def actualizar_stock_producto_local(producto_id, nuevo_stock):
        """
        Actualiza el stock de un producto localmente tanto en OdooProducto como en Comparativa
        """
        from modules.servidor.models import OdooProducto, Comparativa
        try:
            with transaction.atomic():
                OdooProducto.objects.filter(id=producto_id).update(qty_available=nuevo_stock)
                Comparativa.objects.filter(producto_id=producto_id).update(odoo_stock=nuevo_stock, new_stock=0)
            return True
        except Exception as e:
            logger.error("Error al actualizar stock local (producto_id=%s).", producto_id, exc_info=True)
            return False

    @staticmethod
    def crear_producto_nuevo_local(fila, producto_odoo_id, ruta_id=None, tarifa_id=None):
        """
        Crea/actualiza localmente los registros relacionados cuando se crea un producto nuevo en Odoo
        para evitar recargar todo el set de productos.
        """
        from modules.servidor.models import OdooProducto, OdooRuta, OdooTarifa, Comparativa
        try:
            ref_interna = (fila.ref_interna or "").strip()
            producto_nombre = (fila.producto or "").strip()
            nombre_display = f"[{ref_interna}] {producto_nombre}" if ref_interna else producto_nombre

            with transaction.atomic():
                OdooProducto.objects.update_or_create(
                    id=producto_odoo_id,
                    defaults={
                        "name": producto_nombre,
                        "list_price": fila.tb_precio,
                        "barcode": fila.tb_barcode,
                        "categ_id": "All / Ferreteria",
                        "qty_available": 0,
                        "virtual_available": 0,
                        "incoming_qty": 0,
                        "outgoing_qty": 0,
                        "default_code": fila.ref_interna,
                        "activo": fila.tb_activo,
                    },
                )

                ruta_defaults = {
                    "product_id": producto_odoo_id,
                    "product_tmpl_id": producto_odoo_id,
                    "product": nombre_display,
                    "location_id": 8,
                    "product_min_qty": fila.tb_min,
                    "product_max_qty": fila.tb_max,
                }
                if ruta_id:
                    OdooRuta.objects.update_or_create(id=ruta_id, defaults=ruta_defaults)
                else:
                    OdooRuta.objects.update_or_create(
                        product_id=producto_odoo_id,
                        location_id=8,
                        defaults=ruta_defaults,
                    )

                proveedor_nombre = ""
                if getattr(fila, "tb_proveedor", None):
                    proveedor_nombre = getattr(fila.tb_proveedor, "name", "") or ""

                tarifa_defaults = {
                    "partner_id": fila.tb_proveedor_id or 0,
                    "partner": proveedor_nombre,
                    "product_tmpl_id": producto_odoo_id,
                    "product_tmpl": nombre_display,
                    "price": fila.tb_precio_compra or 0,
                    "sequence": 1,
                    "product_code": (fila.ref_interna or "").strip(),
                }
                if tarifa_id:
                    OdooTarifa.objects.update_or_create(id=tarifa_id, defaults=tarifa_defaults)
                else:
                    OdooTarifa.objects.update_or_create(
                        product_tmpl_id=producto_odoo_id,
                        partner_id=fila.tb_proveedor_id or 0,
                        sequence=1,
                        defaults=tarifa_defaults,
                    )

                comparativa_defaults = {
                    "producto_id": producto_odoo_id,
                    "existe": True,
                    "desc_ok": True,
                    "odoo_precio": fila.tb_precio,
                    "odoo_stock": 0,
                    "odoo_barcode": fila.tb_barcode,
                    "odoo_precio_compra": fila.tb_precio_compra or 0,
                    "tarifa_id": tarifa_id,
                    "odoo_codigo_proveedor": fila.ref_interna if tarifa_id else "",
                    "odoo_min": fila.tb_min,
                    "odoo_max": fila.tb_max,
                    "ruta_id": ruta_id,
                    "odoo_activo": fila.tb_activo,
                    "new_stock": 0,
                }
                if fila.tb_proveedor_id:
                    comparativa_defaults["odoo_proveedor_id"] = fila.tb_proveedor_id
                else:
                    comparativa_defaults["odoo_proveedor_id"] = None

                updated = Comparativa.objects.filter(id=fila.id).update(**comparativa_defaults)
                if not updated:
                    Comparativa.objects.filter(
                        ref_interna=fila.ref_interna,
                        producto=fila.producto,
                    ).update(**comparativa_defaults)

            from modules.servidor.data_manage import _avisar_indice_ia
            _avisar_indice_ia("producto nuevo")
            return True
        except Exception as e:
            print(f"Error al crear producto local: {e}")
            return False

    @staticmethod
    @tarea_async
    async def cargar_rutas_odoo(page, update_view_callback=None, loading_widget=None):
        """
        Carga las rutas de abastecimiento de Odoo
        
        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la carga fue exitosa, False en caso contrario
        """
        from modules.servidor.odoo import OdooService
        
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Cargando datos de Odoo...")

        try:
            # Cargar datos de Odoo
            def cargar():
                DataManage.save_rutas_odoo(reglas=OdooService.get_rutas())
                DataManage.compare_data_with_odoo()

            await asyncio.to_thread(cargar)
            
            # Actualizar la vista si se proporciona callback
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)

            # Ocultar loading
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            return True

        except Exception as e:
            # Ocultar loading en caso de error
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False

    @staticmethod
    @tarea_async
    async def cargar_oc_odoo(page, update_view_callback=None, loading_widget=None):
        """
        Carga las órdenes de compra de Odoo

        Args:
            loading_widget: Widget de loading para mostrar progreso
            page: Página de Flet para mostrar mensajes
            update_view_callback (callable, optional): Función callback para actualizar la vista
            
        Returns:
            bool: True si la carga fue exitosa, False en caso contrario
        """
        from modules.servidor.odoo import OdooService
        
        # Mostrar loading
        if loading_widget:
            loading_widget.show("Cargando datos de Odoo...")

        try:
            # Cargar datos de Odoo
            def cargar():
                DataManage.save_oc_data(OdooService.listar_ordenes_compra())
                DataManage.compare_data_with_odoo()

            await asyncio.to_thread(cargar)
            
            # Actualizar la vista si se proporciona callback
            if update_view_callback:
                update_view_callback()
            pendientes.refrescar(page)

            # Ocultar loading
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            return True

        except Exception as e:
            # Ocultar loading en caso de error
            if loading_widget:
                loading_widget.hide()
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return False
    
    
    def calcula_resumen_ventas(data_odoo = None) -> dict:
        total_ventas = 0
        cantidad_vendida = 0
        if data_odoo:
            for venta in data_odoo:
                total_ventas += venta.get("price_unit", 0) * venta.get("product_uom_qty", 0)
                cantidad_vendida += venta.get("product_uom_qty", 0)

        return {"total_ventas": total_ventas, "cantidad_vendida": cantidad_vendida}

    @staticmethod
    def calcula_resumenes_ventas_por_producto(data_odoo=None) -> dict:
        """
        Agrupa líneas de venta de Odoo por producto y calcula sus totales.
        Retorna {producto_id: {"total_ventas": float, "cantidad_vendida": float}}.
        Misma aritmética que calcula_resumen_ventas.
        """
        resumenes = {}
        if data_odoo:
            for venta in data_odoo:
                if not venta.get("product_id"):
                    continue
                pid = venta["product_id"][0]
                totales = resumenes.setdefault(pid, {"total_ventas": 0, "cantidad_vendida": 0})
                totales["total_ventas"] += venta.get("price_unit", 0) * venta.get("product_uom_qty", 0)
                totales["cantidad_vendida"] += venta.get("product_uom_qty", 0)
        return resumenes
        
        
    @staticmethod
    def genera_reporte_ventas_ultimos_meses(hoja, page, meses=3) -> list:
        
        """
        Genera un reporte de ventas de los últimos meses para un proveedor específico

        Args:
            proveedor_id (int): ID del proveedor
            meses (int): Número de meses a considerar (por defecto 6)

        Returns:
            list: Lista con el resumen de ventas
        """
        ret = []
        # 1 obtener la tabla base con la hoja seleccionada
        TablaBaseManager.leer_tabla_base([hoja])
        
        # 2 obtener las referencias (codigos) de los productos en la tabla base para esa hoja
        productos_tb_ids = list(TablaBase.objects.filter(hoja_seleccionada__hoja=hoja).values_list('ref_interna', flat=True).distinct())
        # 3 obtener codigos de productos en odoo y stock actual
        productos_odoo = OdooService.get_productos_odoo_by_refs(productos_tb_ids)
        # 4 calcular los ultimos {meses} meses anteriores a la fecha actual
        import datetime
        today = datetime.date.today()
        meses_list = []
        for i in range(1, meses + 1):
            mes = (today.month - i - 1) % 12 + 1
            anio = today.year - ((today.month - i - 1) // 12)
            meses_list.append((anio, mes))
        # 5 calculamos el mes - año actual
        mes_actual = (today.month, today.year)
        
        # 6 prefetch: todos los resúmenes ya cacheados en BD, en una sola query.
        # Se filtra por pares (anio, mes) exactos — anio__in + mes__in daría falsos
        # positivos cuando el rango cruza el año. order_by('id') hace que ante
        # duplicados históricos gane la fila de mayor id, igual que el antiguo
        # .first() con ordering=["-id"].
        import functools
        import operator
        from django.db.models import Q as _Q
        pares_q = functools.reduce(operator.or_, (_Q(anio=a, mes=m) for a, m in meses_list))
        existentes = ResumenVentaProducto.objects.filter(
            producto__in=[str(p['id']) for p in productos_odoo]
        ).filter(pares_q).order_by('id')
        cache_resumenes = {(int(r.producto), r.anio, r.mes): r for r in existentes}

        # 7 detectar (producto, mes) faltantes y traerlos de Odoo en una sola
        # llamada por mes (antes: una llamada XML-RPC por producto × mes)
        faltantes_por_mes = {}
        for producto in productos_odoo:
            for anio, mes in meses_list:
                if (producto['id'], anio, mes) not in cache_resumenes:
                    faltantes_por_mes.setdefault((anio, mes), []).append(producto['id'])

        nuevos = []
        for (anio, mes), ids_faltantes in faltantes_por_mes.items():
            lineas = OdooService.obtener_resumenes_ventas(productos=ids_faltantes, mes=mes, anio=anio)
            por_producto = OdooSyncManager.calcula_resumenes_ventas_por_producto(lineas)
            # se persiste también el resumen en cero de los productos sin ventas,
            # para no volver a consultar Odoo por ese mes en usos futuros
            for pid in ids_faltantes:
                totales = por_producto.get(pid, {"total_ventas": 0, "cantidad_vendida": 0})
                resumen_venta = ResumenVentaProducto(
                    producto=str(pid),
                    anio=anio,
                    mes=mes,
                    total_ventas=totales["total_ventas"],
                    cantidad_vendida=totales["cantidad_vendida"],
                )
                nuevos.append(resumen_venta)
                cache_resumenes[(pid, anio, mes)] = resumen_venta
        if nuevos:
            ResumenVentaProducto.objects.bulk_create(nuevos, ignore_conflicts=True)

        for producto in productos_odoo:
            fila = {
                "producto_id": producto['id'],
                "producto_name": producto['name'],
                "stock_actual": producto['qty_available'],
                "favorito": bool(producto.get('is_favorite', False)),
                "ventas": []
            }
            promedio_total_ventas = 0
            promedio_cantidad_vendida = 0
            for anio, mes in meses_list:
                resumen_venta = cache_resumenes[(producto['id'], anio, mes)]
                promedio_total_ventas += resumen_venta.total_ventas
                promedio_cantidad_vendida += resumen_venta.cantidad_vendida

                fila["ventas"].append({
                    "anio": anio,
                    "mes": mes,
                    "total_ventas": resumen_venta.total_ventas,
                    "cantidad_vendida": resumen_venta.cantidad_vendida
                })
            fila["promedio_total_ventas"] = promedio_total_ventas // meses
            fila["promedio_cantidad_vendida"] = promedio_cantidad_vendida / meses
            # la proyeccion es el stock actual dividido el promedio de cantidad vendida por 3 meses
            fila["proyeccion"] = fila["stock_actual"] / fila["promedio_cantidad_vendida"] if fila["promedio_cantidad_vendida"] > 0 else "--"
            ret.append(fila)
            
        # se incorpora el mes actual a la lista de ventas
        ventas_actuales = OdooService.obtener_resumenes_ventas(productos=[p['id'] for p in productos_odoo], mes=mes_actual[0], anio=mes_actual[1])
        for fila in ret:
            venta_producto = [v for v in ventas_actuales if v['product_id'][0] == fila['producto_id']]
            resumen_venta_actual = OdooSyncManager.calcula_resumen_ventas(venta_producto)
            if resumen_venta_actual:
                fila["ventas"].insert(0, {
                    "anio": mes_actual[1],
                    "mes": mes_actual[0],
                    "total_ventas": resumen_venta_actual.get("total_ventas", 0),
                    "cantidad_vendida": resumen_venta_actual.get("cantidad_vendida", 0)
                })
            else:
                fila["ventas"].insert(0, {
                    "anio": mes_actual[1],
                    "mes": mes_actual[0],
                    "total_ventas": 0,
                    "cantidad_vendida": 0
                })

        return ret

    @staticmethod
    def genera_reporte_ventas_por_semana(hoja, page, fecha_desde, fecha_hasta) -> list:
        """
        Genera un resumen semanal de ventas (cantidad e importe total)
        para los productos asociados a una hoja/proveedor.
        """
        TablaBaseManager.leer_tabla_base([hoja])

        productos_tb_ids = list(
            TablaBase.objects.filter(hoja_seleccionada__hoja=hoja)
            .values_list('ref_interna', flat=True)
            .distinct()
        )

        if not productos_tb_ids:
            return []

        productos_odoo = OdooService.get_productos_odoo_by_refs(productos_tb_ids)
        productos_ids = [p['id'] for p in productos_odoo]

        if not productos_ids:
            return []

        ventas = OdooService.obtener_resumenes_ventas_rango(
            productos=productos_ids,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
        )

        semanas = {}

        for venta in ventas:
            fecha_venta_str = str(venta.get('create_date') or '')
            if not fecha_venta_str:
                continue

            try:
                fecha_venta = datetime.strptime(fecha_venta_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            anio_iso, semana_iso, _ = fecha_venta.isocalendar()
            clave = (anio_iso, semana_iso)

            if clave not in semanas:
                inicio_semana = datetime.fromisocalendar(anio_iso, semana_iso, 1).date()
                fin_semana = inicio_semana + timedelta(days=6)
                semanas[clave] = {
                    "anio": anio_iso,
                    "semana": semana_iso,
                    "fecha_inicio": inicio_semana,
                    "fecha_fin": fin_semana,
                    "cantidad_vendida": 0,
                    "total_ventas": 0,
                }

            semanas[clave]["cantidad_vendida"] += float(venta.get('product_uom_qty', 0) or 0)
            semanas[clave]["total_ventas"] += float(venta.get('price_subtotal', 0) or 0)

        return [
            semanas[key]
            for key in sorted(semanas.keys(), key=lambda item: (item[0], item[1]))
        ]

    @staticmethod
    def genera_reporte_ventas_dias_semana(page, fecha_referencia, hoja=None) -> dict:
        """
        Genera reporte de ventas por día para la semana de una fecha dada.
        Si `hoja` es None, considera todas las ventas.
        """
        fecha_inicio_semana = fecha_referencia - timedelta(days=fecha_referencia.weekday())
        fecha_fin_semana = fecha_inicio_semana + timedelta(days=6)

        productos_ids = None
        if hoja:
            TablaBaseManager.leer_tabla_base([hoja])
            productos_tb_ids = list(
                TablaBase.objects.filter(hoja_seleccionada__hoja=hoja)
                .values_list('ref_interna', flat=True)
                .distinct()
            )

            if not productos_tb_ids:
                return {
                    "anio": fecha_inicio_semana.isocalendar()[0],
                    "semana": fecha_inicio_semana.isocalendar()[1],
                    "fecha_inicio": fecha_inicio_semana,
                    "fecha_fin": fecha_fin_semana,
                    "dias": []
                }

            productos_odoo = OdooService.get_productos_odoo_by_refs(productos_tb_ids)
            productos_ids = [p['id'] for p in productos_odoo]

            if not productos_ids:
                return {
                    "anio": fecha_inicio_semana.isocalendar()[0],
                    "semana": fecha_inicio_semana.isocalendar()[1],
                    "fecha_inicio": fecha_inicio_semana,
                    "fecha_fin": fecha_fin_semana,
                    "dias": []
                }

        ventas = OdooService.obtener_resumenes_ventas_rango(
            productos=productos_ids,
            fecha_desde=fecha_inicio_semana,
            fecha_hasta=fecha_fin_semana,
        )

        nombres_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
        dias_map = {}
        for i in range(7):
            fecha_dia = fecha_inicio_semana + timedelta(days=i)
            dias_map[fecha_dia] = {
                "fecha": fecha_dia,
                "dia": nombres_dias[i],
                "cantidad_vendida": 0,
                "total_ventas": 0,
                "_ordenes_ids": set(),
            }

        for venta in ventas:
            fecha_venta_str = str(venta.get('create_date') or '')
            if not fecha_venta_str:
                continue

            try:
                fecha_venta = datetime.strptime(fecha_venta_str[:10], "%Y-%m-%d").date()
            except ValueError:
                continue

            if fecha_venta < fecha_inicio_semana or fecha_venta > fecha_fin_semana:
                continue

            order_info = venta.get('order_id')
            order_id = order_info[0] if isinstance(order_info, list) and order_info else None

            if order_id:
                if order_id not in dias_map[fecha_venta]["_ordenes_ids"]:
                    dias_map[fecha_venta]["_ordenes_ids"].add(order_id)
                    dias_map[fecha_venta]["cantidad_vendida"] += 1
            else:
                dias_map[fecha_venta]["cantidad_vendida"] += 1

            dias_map[fecha_venta]["total_ventas"] += float(venta.get('price_subtotal', 0) or 0)

        anio_iso, semana_iso, _ = fecha_inicio_semana.isocalendar()

        dias_limpios = []
        for i in range(7):
            dia_data = dict(dias_map[fecha_inicio_semana + timedelta(days=i)])
            dia_data.pop("_ordenes_ids", None)
            dias_limpios.append(dia_data)

        return {
            "anio": anio_iso,
            "semana": semana_iso,
            "fecha_inicio": fecha_inicio_semana,
            "fecha_fin": fecha_fin_semana,
            "dias": dias_limpios,
        }
        
        
    @staticmethod
    def obtiene_compras(hoja, page, fecha_desde: datetime.date, fecha_hasta: datetime.date) -> list:
        # def calcula_resumen_compras(data_odoo = None) -> dict:
        #     total_compras = 0
        #     cantidad_comprada = 0
        #     if data_odoo:
        #         for compra in data_odoo:
        #             total_compras += compra.get("price_unit", 0) * compra.get("product_qty", 0)
        #             cantidad_comprada += compra.get("product_qty", 0)

        #     return {"total_compras": total_compras, "cantidad_comprada": cantidad_comprada}
        """
        Obtiene el resumen de compras de los últimos meses para un proveedor específico

        Args:
            proveedor_id (int): ID del proveedor
            meses (int): Número de meses a considerar (por defecto 6)

        Returns:
            list: Lista con el resumen de ventas
        """
        ret = []
        from modules.servidor.odoo import OdooService
        
        # # 0 actualizar los productos de odoo para obtener el stock actual
        # DataManage.save_productos_odoo(products=OdooService.get_productos())
        # 1 obtener la tabla base con la hoja seleccionada
        TablaBaseManager.leer_tabla_base([hoja])
        
        # 2 obtener los productos
        productos = Comparativa.objects.all()
        
        # 3 calcular los meses en el rango de fechas especificado
        import datetime
        import calendar
        
        meses_list = []
        fecha_actual = fecha_desde.replace(day=1)  # Comenzar desde el primer día del mes
        fecha_fin = fecha_hasta.replace(day=1)     # Hasta el primer día del mes final
        
        while fecha_actual <= fecha_fin:
            meses_list.append((fecha_actual.year, fecha_actual.month))
            # Avanzar al siguiente mes
            if fecha_actual.month == 12:
                fecha_actual = fecha_actual.replace(year=fecha_actual.year + 1, month=1)
            else:
                fecha_actual = fecha_actual.replace(month=fecha_actual.month + 1)
        
        # Calcular cantidad de meses para promedios
        meses = len(meses_list)
        
        from .models import OdooProducto
        favoritos_map = {p.id: p.favorito for p in OdooProducto.objects.filter(id__in=[p.producto_id for p in productos])}
        
        for producto in productos:
            fila = {
                "producto_id": producto.producto_id, 
                "producto_name": producto.name,
                "stock_actual": producto.odoo_stock,
                "favorito": favoritos_map.get(producto.producto_id, False),
                "compras": []
            }
            promedio_total_compras = 0
            promedio_cantidad_comprada = 0
            promedio_precio_compra_promedio = 0
            for anio, mes in meses_list:
                registros = []
                # si es el mes acual y año actual, se eliminan los registros de la base de datos y se vuelven a obtener de odoo
                if anio == fecha_actual.year and mes == fecha_actual.month:
                    ResumenCompraProducto.objects.filter(producto=producto.producto_id).filter(anio=anio, mes=mes).delete()
                    compras_en_bd = ResumenCompraProducto.objects.none()  # Inicializar como queryset vacío
                else:
                    # revisamos si existe un registro de compra para ese producto en ese mes en ResumenCompraVentaProducto
                    compras_en_bd = ResumenCompraProducto.objects.filter(producto=producto.producto_id).filter(anio=anio, mes=mes)
                
                if not compras_en_bd.exists():
                    # si no existe la vamos a buscar a odoo
                    resumen_odoo = OdooService.obtener_compras(producto.producto_id, mes, anio)

                    # totales = calcula_resumen_compras(resumen_odoo)
                    if len(resumen_odoo) > 0:
                        for reg in resumen_odoo:
                            obj = ResumenCompraProducto(
                                producto=producto.producto_id,
                                anio=anio,
                                mes=mes,
                                total_compras=reg.get("price_unit", 0) * reg.get("product_qty", 0),
                                cantidad_comprada=reg.get("product_qty", 0),
                                precio_compra_promedio=reg.get("price_unit", 0),
                                proveedor=reg.get("partner_id", [0, ""])[1]
                            )
                            obj.save()
                    else:
                        obj = ResumenCompraProducto(
                            producto=producto.producto_id,
                            anio=anio,
                            mes=mes,
                            total_compras=0,
                            cantidad_comprada=0,
                            precio_compra_promedio=0,
                            proveedor="N/A"
                        )
                        obj.save()
                    compras_en_bd = ResumenCompraProducto.objects.filter(producto=producto.producto_id).filter(anio=anio, mes=mes)
                for compra in compras_en_bd:
                    registros.append({
                        "proveedor": compra.proveedor,
                        "total_compras": compra.total_compras,
                        "cantidad_comprada": compra.cantidad_comprada,
                        "precio_compra_promedio": compra.precio_compra_promedio
                    })
                    
                # promedio_total_compras += resumen.total_compras
                # promedio_cantidad_comprada += resumen.cantidad_comprada
                # promedio_precio_compra_promedio += resumen.precio_compra_promedio

                fila["compras"].append({
                    "anio": anio,
                    "mes": mes,
                    "registros": registros,
                    # "total_compras": resumen.total_compras,
                    # "cantidad_comprada": resumen.cantidad_comprada,
                    # "precio_compra_promedio": resumen.precio_compra_promedio
                })
            # fila["promedio_total_compras"] = promedio_total_compras // meses
            # fila["promedio_cantidad_comprada"] = promedio_cantidad_comprada // meses
            # fila["promedio_precio_compra_promedio"] = promedio_precio_compra_promedio // meses
            ret.append(fila)

        return ret
    
    @staticmethod
    def obtiene_ventas_mes_actual(page, productos_id: list) -> list:
        pass
    

class ReporteMovimientosProducto:
    """
    Clase para manejar reportes de movimientos de productos (compras, ventas, stock)
    Almacena datos en BD para evitar consultas repetidas a Odoo
    """
    
    @staticmethod
    def obtener_movimientos_mes(producto_id: int, mes: int, anio: int) -> dict:
        """
        Obtiene o calcula los movimientos de un producto para un mes específico
        
        Args:
            producto_id: ID del producto en Odoo
            mes: Mes (1-12)
            anio: Año
            
        Returns:
            dict: Movimientos procesados con compras, ventas y stock
        """
        # Verificar si ya existen datos calculados
        movimiento = MovimientoProductoMes.objects.filter(
            producto_id=producto_id,
            mes=mes,
            anio=anio
        ).first()
        
        if movimiento:
            return {
                "producto_id": movimiento.producto_id,
                "producto_nombre": movimiento.producto_nombre,
                "mes": movimiento.mes,
                "anio": movimiento.anio,
                "cantidad_comprada": movimiento.cantidad_comprada,
                "total_compras": movimiento.total_compras,
                "precio_compra_promedio": movimiento.precio_compra_promedio,
                "cantidad_vendida": movimiento.cantidad_vendida,
                "total_ventas": movimiento.total_ventas,
                "precio_venta_promedio": movimiento.precio_venta_promedio,
                "stock_cierre_mes": movimiento.stock_cierre_mes,
            }
        
        # Si no existe, calcular desde Odoo
        return ReporteMovimientosProducto._calcular_movimientos(
            producto_id, mes, anio
        )
    
    @staticmethod
    def _calcular_movimientos(producto_id: int, mes: int, anio: int) -> dict:
        """
        Calcula los movimientos desde Odoo sin almacenar en BD
        Incluye compras, ventas y ajustes de inventario
        """
        # Obtener compras
        compras = OdooService.obtener_compras(producto_id, mes, anio)
        cantidad_comprada = 0
        total_compras = 0
        
        if compras and not isinstance(compras, dict):
            for compra in compras:
                cantidad_comprada += compra.get("product_qty", 0)
                total_compras += compra.get("price_subtotal", 0)
        
        precio_compra_promedio = (
            total_compras / cantidad_comprada 
            if cantidad_comprada > 0 
            else 0
        )
        
        # Obtener ventas
        ventas = OdooService.obtener_ventas(producto_id, mes, anio)
        cantidad_vendida = 0
        total_ventas = 0
        
        if ventas and not isinstance(ventas, dict):
            for venta in ventas:
                cantidad_vendida += venta.get("product_uom_qty", 0)
                total_ventas += venta.get("price_subtotal", 0)
        
        precio_venta_promedio = (
            total_ventas / cantidad_vendida 
            if cantidad_vendida > 0 
            else 0
        )
        
        # Obtener ajustes de inventario
        ajustes = OdooService.obtener_ajustes_inventario(producto_id, mes, anio)
        cantidad_ajustada = 0
        
        if ajustes and isinstance(ajustes, list):
            for ajuste in ajustes:
                cantidad_ajustada += ajuste.get("cantidad", 0)
        
        # Stock de cierre: se calculará acumulativamente en el método principal
        stock_cierre_mes = 0
        
        return {
            "producto_id": producto_id,
            "mes": mes,
            "anio": anio,
            "cantidad_comprada": cantidad_comprada,
            "total_compras": total_compras,
            "precio_compra_promedio": precio_compra_promedio,
            "cantidad_vendida": cantidad_vendida,
            "total_ventas": total_ventas,
            "precio_venta_promedio": precio_venta_promedio,
            "cantidad_ajustada": cantidad_ajustada,  # Nuevo campo
            "stock_cierre_mes": stock_cierre_mes,
        }
    
    @staticmethod
    def guardar_movimiento(producto_id: int, producto_nombre: str, mes: int, anio: int,
                          cantidad_comprada: int = 0, total_compras: float = 0,
                          precio_compra_promedio: float = 0, cantidad_vendida: int = 0,
                          total_ventas: float = 0, precio_venta_promedio: float = 0,
                          cantidad_ajustada: int = 0, stock_cierre_mes: int = 0) -> MovimientoProductoMes:
        """
        Guarda o actualiza un movimiento de producto en la BD
        
        Returns:
            MovimientoProductoMes: Objeto guardado
        """
        movimiento, created = MovimientoProductoMes.objects.update_or_create(
            producto_id=producto_id,
            mes=mes,
            anio=anio,
            defaults={
                "producto_nombre": producto_nombre,
                "cantidad_comprada": cantidad_comprada,
                "total_compras": total_compras,
                "precio_compra_promedio": precio_compra_promedio,
                "cantidad_vendida": cantidad_vendida,
                "total_ventas": total_ventas,
                "precio_venta_promedio": precio_venta_promedio,
                "cantidad_ajustada": cantidad_ajustada,
                "stock_cierre_mes": stock_cierre_mes,
            }
        )
        return movimiento
    
    @staticmethod
    def obtener_reporte(hoja, page, fecha_desde: datetime.date, fecha_hasta: datetime.date) -> list:
        ret = []
        from modules.servidor.odoo import OdooService
        
        # # 0 actualizar los productos de odoo para obtener el stock actual
        # DataManage.save_productos_odoo(products=OdooService.get_productos())
        # 1 obtener la tabla base con la hoja seleccionada
        TablaBaseManager.leer_tabla_base([hoja])
        
        # 2 obtener los productos
        productos = Comparativa.objects.all()
        
        # 3 calcular los meses en el rango de fechas especificado
        import datetime
        import calendar
        
        meses_list = []
        fecha_actual = fecha_desde.replace(day=1)  # Comenzar desde el primer día del mes
        fecha_fin = fecha_hasta.replace(day=1)     # Hasta el primer día del mes final
        
        while fecha_actual <= fecha_fin:
            meses_list.append((fecha_actual.year, fecha_actual.month))
            # Avanzar al siguiente mes
            if fecha_actual.month == 12:
                fecha_actual = fecha_actual.replace(year=fecha_actual.year + 1, month=1)
            else:
                fecha_actual = fecha_actual.replace(month=fecha_actual.month + 1)
        
        for producto in productos:
            ret.append(ReporteMovimientosProducto.obtener_reporte_producto_y_rango_fechas(
                producto_id=producto.producto_id,
                fecha_desde=fecha_desde,
                fecha_hasta=fecha_hasta
            ))
        return ret
    
    @staticmethod
    def obtener_reporte_producto_y_rango_fechas(producto_id: int, fecha_desde: datetime, 
                                     fecha_hasta: datetime) -> list:
        """
        Obtiene un reporte completo de movimientos para un rango de fechas con cálculo acumulativo de stock
        
        Estrategia de cálculo de stock:
        1. Detecta el primer mes sin registros en BD
        2. Obtiene el stock actual de Odoo (hoy)
        3. Calcula HACIA ATRÁS desde hoy hasta el primer mes sin registro
        4. Guarda todos los meses históricos (excepto el mes actual)
        5. El mes actual SIEMPRE se calcula fresh (nunca se cachea)
        
        Args:
            producto_id: ID del producto
            fecha_desde: Fecha inicial (datetime.date)
            fecha_hasta: Fecha final (datetime.date)
            
        Returns:
            dict: Diccionario con información del producto y lista de movimientos
        """
        import datetime as dt
        
        # Obtener información del producto
        producto_odoo = OdooService.buscar_producto_odoo(producto_id)
        if not producto_odoo:
            return {
                "producto_id": producto_id,
                "producto_nombre": f"Producto {producto_id}",
                "stock_actual": 0,
                "favorito": False,
                "movimientos": []
            }
        
        producto_nombre = producto_odoo['name']
        stock_actual_odoo = producto_odoo.get('qty_available', 0)
        favorito = bool(producto_odoo.get('is_favorite', False))
        
        # Obtener mes y año actual
        hoy = datetime.now().date()
        mes_actual = hoy.month
        anio_actual = hoy.year
        
        # Calcular rango de meses solicitado
        meses_list = []
        fecha_actual = fecha_desde.replace(day=1)
        fecha_fin = fecha_hasta.replace(day=1)
        
        while fecha_actual <= fecha_fin:
            meses_list.append((fecha_actual.year, fecha_actual.month))
            if fecha_actual.month == 12:
                fecha_actual = fecha_actual.replace(year=fecha_actual.year + 1, month=1)
            else:
                fecha_actual = fecha_actual.replace(month=fecha_actual.month + 1)
        
        # Agregar mes anterior para obtener stock de apertura
        if meses_list:
            primer_mes_year, primer_mes_month = meses_list[0]
            if primer_mes_month == 1:
                mes_anterior = (primer_mes_year - 1, 12)
            else:
                mes_anterior = (primer_mes_year, primer_mes_month - 1)
            meses_list.insert(0, mes_anterior)
        
        # Identificar meses faltantes en el rango solicitado
        meses_faltantes = []
        for anio, mes in meses_list:
            if not MovimientoProductoMes.objects.filter(
                producto_id=producto_id,
                mes=mes,
                anio=anio
            ).exists():
                meses_faltantes.append((anio, mes))
        
        # Si hay meses faltantes, calcularlos hacia ATRÁS
        if meses_faltantes:
            # Obtener el último mes del rango solicitado
            ultimo_mes_rango = meses_list[-1]
            ultimo_anio, ultimo_mes = ultimo_mes_rango
            
            # Buscar el primer mes guardado DESPUÉS del último mes solicitado
            # para usarlo como punto de referencia
            mes_siguiente = ultimo_mes + 1 if ultimo_mes < 12 else 1
            anio_siguiente = ultimo_anio if ultimo_mes < 12 else ultimo_anio + 1
            
            registro_posterior = MovimientoProductoMes.objects.filter(
                producto_id=producto_id
            ).filter(
                Q(anio__gt=anio_siguiente) | Q(anio=anio_siguiente, mes__gte=mes_siguiente)
            ).order_by('anio', 'mes').first()
            
            # Determinar el stock de referencia y desde dónde calcular
            if registro_posterior:
                # Hay un mes guardado posterior, usar su stock de inicio
                # El stock de inicio de un mes = stock de cierre del mes anterior
                # Necesitamos calcular hacia atrás desde el mes anterior al registro
                if registro_posterior.mes == 1:
                    mes_ref = 12
                    anio_ref = registro_posterior.anio - 1
                else:
                    mes_ref = registro_posterior.mes - 1
                    anio_ref = registro_posterior.anio
                
                # Buscar el registro del mes anterior para obtener su stock de cierre
                registro_anterior = MovimientoProductoMes.objects.filter(
                    producto_id=producto_id,
                    mes=mes_ref,
                    anio=anio_ref
                ).first()
                
                if registro_anterior:
                    stock_referencia = registro_anterior.stock_cierre_mes
                    mes_inicio_calc = mes_ref
                    anio_inicio_calc = anio_ref
                else:
                    # Si no existe el mes anterior, calcular su stock basado en el posterior
                    # Esto requiere obtener movimientos de ese mes
                    mov_ref = ReporteMovimientosProducto._calcular_movimientos(
                        producto_id, registro_posterior.mes, registro_posterior.anio
                    )
                    # Stock Inicio Mes Posterior = Stock Cierre Mes Anterior
                    # Necesitamos el stock de cierre del mes anterior al posterior
                    # Por ahora, usar el stock actual como referencia
                    stock_referencia = stock_actual_odoo
                    mes_inicio_calc = anio_actual
                    anio_inicio_calc = mes_actual
            else:
                # No hay meses posteriores guardados, usar stock actual de Odoo
                stock_referencia = stock_actual_odoo
                mes_inicio_calc = mes_actual
                anio_inicio_calc = anio_actual
            
            # Crear lista de meses a calcular hacia ATRÁS
            # desde el mes de referencia hasta el primer mes del rango
            meses_a_calcular = []
            fecha_calc = dt.date(anio_inicio_calc, mes_inicio_calc, 1)
            fecha_inicio_rango = dt.date(meses_list[0][0], meses_list[0][1], 1)
            
            while fecha_calc >= fecha_inicio_rango:
                meses_a_calcular.append((fecha_calc.year, fecha_calc.month))
                if fecha_calc.month == 1:
                    fecha_calc = fecha_calc.replace(year=fecha_calc.year - 1, month=12)
                else:
                    fecha_calc = fecha_calc.replace(month=fecha_calc.month - 1)
            
            # Calcular hacia ATRÁS mes por mes
            movimientos_calculados = []
            stock_cierre_mes = stock_referencia
            
            for anio, mes in meses_a_calcular:
                # Calcular movimientos del mes
                movimiento_datos = ReporteMovimientosProducto._calcular_movimientos(
                    producto_id, mes, anio
                )
                
                # El stock de cierre de este mes es el que tenemos de referencia
                movimiento_datos['stock_cierre_mes'] = stock_cierre_mes
                
                movimientos_calculados.append((anio, mes, movimiento_datos))
                
                # Calcular stock de cierre del mes ANTERIOR (hacia atrás):
                # Stock Cierre Mes Anterior = Stock Cierre Mes Actual - Compras + Ventas - Ajustes
                stock_cierre_mes = (
                    stock_cierre_mes
                    - movimiento_datos['cantidad_comprada']
                    + movimiento_datos['cantidad_vendida']
                    - movimiento_datos.get('cantidad_ajustada', 0)
                )
            
            # Revertir para tener orden cronológico
            movimientos_calculados.reverse()
            
            # Guardar en BD los meses históricos (no el mes actual)
            for anio, mes, mov_datos in movimientos_calculados:
                # if not (anio == anio_actual and mes == mes_actual):
                    ReporteMovimientosProducto.guardar_movimiento(
                        producto_id=producto_id,
                        producto_nombre=producto_nombre,
                        mes=mes,
                        anio=anio,
                        cantidad_comprada=mov_datos['cantidad_comprada'],
                        total_compras=mov_datos['total_compras'],
                        precio_compra_promedio=mov_datos['precio_compra_promedio'],
                        cantidad_vendida=mov_datos['cantidad_vendida'],
                        total_ventas=mov_datos['total_ventas'],
                        precio_venta_promedio=mov_datos['precio_venta_promedio'],
                        cantidad_ajustada=mov_datos.get('cantidad_ajustada', 0),
                        stock_cierre_mes=mov_datos['stock_cierre_mes']
                    )
        
        # Obtener movimientos para el reporte (ahora todos están en BD o fueron calculados)
        reporte = []
        for anio, mes in meses_list:
            # Para meses históricos, usar BD
            registro = MovimientoProductoMes.objects.filter(
                producto_id=producto_id,
                mes=mes,
                anio=anio
            ).first()
            
            if registro:
                movimiento = {
                    "producto_id": registro.producto_id,
                    "producto_nombre": registro.producto_nombre,
                    "mes": registro.mes,
                    "anio": registro.anio,
                    "cantidad_comprada": registro.cantidad_comprada,
                    "total_compras": registro.total_compras,
                    "precio_compra_promedio": registro.precio_compra_promedio,
                    "cantidad_vendida": registro.cantidad_vendida,
                    "total_ventas": registro.total_ventas,
                    "precio_venta_promedio": registro.precio_venta_promedio,
                    "cantidad_ajustada": registro.cantidad_ajustada,
                    "stock_cierre_mes": registro.stock_cierre_mes,
                }
            else:
                # Si no está en BD, debe haber sido calculado en el bloque anterior
                # Esto solo debería pasar con el mes actual
                movimiento = ReporteMovimientosProducto._calcular_movimientos(
                    producto_id, mes, anio
                )
                # El stock de cierre del mes actual es el stock actual de Odoo
                movimiento['stock_cierre_mes'] = stock_actual_odoo
            
            movimiento['producto_nombre'] = producto_nombre
            reporte.append(movimiento)
        
        return {
            "producto_id": producto_id,
            "producto_nombre": producto_nombre,
            "stock_actual": stock_actual_odoo,
            "favorito": favorito,
            "movimientos": reporte
        }


