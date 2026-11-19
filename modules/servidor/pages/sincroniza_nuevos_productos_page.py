import asyncio
import datetime
from components.custom_input import DisplayMode, SearchField
from components.loading import Loading
from logger_config import get_logger
from modules.servidor.business_logic import OdooSyncManager, TablaBaseManager

logger = get_logger(__name__)
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_resolucion_duplicados import DlgResolucionDuplicados
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.data_manage import DataManage
from modules.servidor.duplicados import DuplicadosManager
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_unico, tarea_async
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions



class SincronizaNuevosProductosPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Nuevos Productos"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "tb_precio", "tb_activo", "tb_barcode", "tb_proveedor", "tb_precio_compra",  "tb_min", "tb_max"],
            # overrides_display_mode={ "tb_proveedor": DisplayMode.EDIT},
            overrides_input_type={"tb_proveedor": SearchField},
            fields_conditions_display={
                "tb_min": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.tb_min > 0 else {"bgcolor": ft.Colors.ERROR_CONTAINER},
                "tb_max": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.tb_max > 0 else {"bgcolor": ft.Colors.ERROR_CONTAINER},
                "tb_precio_compra": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.tb_precio_compra > 0 else {"bgcolor": ft.Colors.ERROR_CONTAINER},
                "tb_precio": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.tb_precio > 0 else {"bgcolor": ft.Colors.ERROR_CONTAINER},
                "ref_interna": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.ref_interna != "" else {"bgcolor": ft.Colors.ERROR_CONTAINER},
                "tb_barcode": lambda obj: {"bgcolor": ft.Colors.TRANSPARENT} if obj.tb_barcode != "" else {"bgcolor": ft.Colors.ERROR_CONTAINER},
            }
        )
        self.is_chk_column_enabled = True
        self.custom_actions = self.build_custom_actions()

        self.page.update()
        self.build_page()
        
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        
    def build_page(self):
        super().build_page()
        self.page.update()
        
    def get_filtered_queryset(self):
        """Retorna el queryset filtrado para mostrar solo productos con stock distintos"""
        return Comparativa.objects.exclude(existe=True)
    
    def _ejecutar_carga_odoo_products(self):
        """Carga productos de Odoo usando el manager de lógica de negocio"""
        return OdooSyncManager.cargar_productos_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
    
    def sincronizacion_odoo_stocks(self, fila):
        resultado = OdooService.set_inventario(fila.producto_id, fila.new_stock)
        if resultado.get("state") == "S":
            OdooSyncManager.actualizar_stock_producto_local(fila.producto_id, fila.new_stock)
        return resultado

    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base)),
            boton_recargar_tb(lambda e: self.recargar_tabla_base()),
            boton_cargar_odoo(lambda e: self.carga_odoo()),
            ft.Switch(
                value=True,
                on_change=lambda e: self.toggle_price_filter(),
                label_position=ft.LabelPosition.LEFT,
                thumb_icon=ft.Icons.FILTER_ALT,
                tooltip="Filtrar productos",
            )
        ]
        
    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Productos',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e)
            },
        ]
        
    @tarea_async
    async def gestor_sincronizacion(self, lista_de_productos):
        """Gestor para sincronizar precios de productos"""
        self.loading.show("Obteniendo productos...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar

        try:
            if self.all_records_selected:
                lista_de_productos = list(self.paginator.object_list) if self.paginator else []

            filas_a_actualizar = [obj for obj in lista_de_productos if obj.tb_precio > 0
                                  and obj.ref_interna != ""
                                  and obj.tb_proveedor != None
                                  and not obj.existe]
            if not filas_a_actualizar:
                self.loading.hide()
                logger.info("Nuevos productos: no hay candidatos que cumplan las condiciones.")
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos que cumplan las condiciones para sincronizar.")))
                return

            logger.info("Iniciando creación de nuevos productos en Odoo. Candidatos: %d", len(filas_a_actualizar))
            self.loading.show("Buscando productos que ya existen en Odoo...")
            await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
            conflictos, limpias = await asyncio.to_thread(DuplicadosManager.detectar_conflictos, filas_a_actualizar)
            self.loading.hide()
            if conflictos:
                abrir_unico(self.page, DlgResolucionDuplicados(
                    page=self.page,
                    conflictos=conflictos,
                    fn_continuar=lambda: self.confirmar_creacion(limpias),
                ))
            else:
                self.confirmar_creacion(limpias)
        except Exception as e:
            self.loading.hide()
            logger.error("Error al preparar sincronización de nuevos productos.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar : {str(e)}", bgcolor=ft.Colors.ERROR)))

    def confirmar_creacion(self, filas_a_actualizar):
        """Abre la confirmación de creación para las filas sin código duplicado."""
        if not filas_a_actualizar:
            self.update_filtered_view()
            return
        abrir_unico(self.page, DlgConfirmacionSincronizacion(
            page=self.page,
            filas_a_actualizar=filas_a_actualizar,
            fields=["producto", "tb_precio"],
            fn_sincronizar=lambda fila: self.sincronizacion_odoo(fila),
            fn_continuar=self.update_filtered_view
        ))

    def sincronizacion_odoo(self, fila):
        logger.debug("Creando producto en Odoo: '%s' | ref=%s | precio=%s", fila.producto, fila.ref_interna, fila.tb_precio)
        msj = OdooService.set_productos({"name": fila.producto, "list_price": fila.tb_precio, "barcode": fila.tb_barcode, "categ_id": "All / Ferreteria", "default_code": fila.ref_interna})
        if msj.get("state") == "S":
            id = msj.get("id")
            logger.debug("Producto '%s' creado en Odoo con id=%s. Creando rutas y tarifas...", fila.producto, id)
            msj_rutas = OdooService.set_rutas({"id": None,
             "product_id": id,
             "product_min_qty": fila.tb_min,
             "product_max_qty": fila.tb_max,
             "location_id": 8})
            # Línea de proveedor (pestaña Compra): precio de COMPRA y la REF de la
            # hoja como código del proveedor, que es lo que vincula la fila al producto.
            msj_tarifas = OdooService.set_tarifas({"id": None,
             "product_tmpl_id": id,
             "price": fila.tb_precio_compra or 0,
             "partner_id": fila.tb_proveedor_id,
             "product_code": (fila.ref_interna or "").strip(),
             "delay": 0,
             "sequence": 1})

            if msj_rutas.get("state") == "S" and msj_tarifas.get("state") == "S":
                local_ok = OdooSyncManager.crear_producto_nuevo_local(
                    fila=fila,
                    producto_odoo_id=id,
                    ruta_id=msj_rutas.get("id"),
                    tarifa_id=msj_tarifas.get("id")
                )
                if local_ok:
                    logger.debug("Producto '%s' creado completamente (Odoo + local).", fila.producto)
                    return msj
                logger.warning("Producto '%s' creado en Odoo pero falló la actualización local.", fila.producto)
                return {
                    "state": "W",
                    "msg": f"Producto {fila.producto} creado en Odoo, pero falló la actualización local automática."
                }
            else:
                errores = ", ".join(filter(None, [
                    "rutas de abastecimiento" if msj_rutas.get("state") == "E" else "",
                    "tarifas" if msj_tarifas.get("state") == "E" else "",
                ]))
                logger.warning("Producto '%s' creado en Odoo pero con errores en: %s", fila.producto, errores)
                return {"state": "E", "msg": f"Producto creado con errores al crear {errores}."}
        else:
            logger.warning("Fallo al crear producto '%s' en Odoo: %s", fila.producto, msj.get("msg"))
            return msj

    def get_modified_stock(self):
        """
        Función para sincronizar el stock entre la tabla base y Odoo.
        """
        # Mostrar loading
       
        
        try:
            filas_a_actualizar = []
            
            # Obtener todos los objetos modificados del cache de la tabla
            if hasattr(self.table, '_modified_objects'):
                # Obtener todos los objetos modificados del cache
                for obj_id, modified_obj in self.table._modified_objects.items():
                    # Verificar si el stock fue modificado y es diferente de 0
                    if hasattr(modified_obj, 'new_stock') and \
                        modified_obj.new_stock != 0 and \
                        isinstance(modified_obj.new_stock, (int, float)) and \
                        modified_obj.existe:
                        filas_a_actualizar.append(modified_obj)
                        # Verificar si realmente cambió comparando con el original
                        # try:
                        #     # Buscar el objeto original en la base de datos
                        #     original_obj = Comparativa.objects.get(id=modified_obj.id)
                        #     if original_obj.tb_stock != modified_obj.tb_stock:
                        #         filas_a_actualizar.append(modified_obj)
                        # except Comparativa.DoesNotExist:
                        #     # Si es un objeto nuevo, también incluirlo
                        #     filas_a_actualizar.append(modified_obj)
            
            # También verificar las filas actualmente visibles que no estén en cache
            if hasattr(self.table, 'component_body'):
                for row in self.table.component_body.controls:
                    if hasattr(row, 'obj') and hasattr(row.obj, 'new_stock') and row.obj.existe:
                        obj_id = getattr(row.obj, 'id', id(row.obj))
                        # Solo procesar si no está ya en el cache de modificados
                        if obj_id not in self.table._modified_objects:
                            if row.obj.new_stock != 0:
                                # Verificar si cambió respecto al original
                                filas_a_actualizar.append(row.obj)
     

            if filas_a_actualizar:
                # Mostrar información de cuántas filas se van a sincronizar
                dlg = DlgConfirmacionSincronizacion(
                    page=self.page,
                    filas_a_actualizar=filas_a_actualizar,
                    fields=["producto", "odoo_stock", "new_stock"],
                    fn_sincronizar=lambda fila: self.sincronizacion_odoo_stocks(fila),
                    fn_continuar=self.update_filtered_view
                )
                abrir_unico(self.page, dlg)

            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con stock modificado para sincronizar.")))

        except Exception as e:
            # Ocultar loading en caso de error
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar stock: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        # Corregir el lambda para capturar la variable hoja correctamente
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        self.cancel_selection()

        """Carga la tabla base usando el manager de lógica de negocio"""
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def recargar_tabla_base(self):
        """Recarga la tabla base usando el manager de lógica de negocio"""
        self.cancel_selection()
        return TablaBaseManager.cargar_tabla_base(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    # def gestiona_hojas_seleccionadas(self, hojas_seleccionadas):
    #     """ Guarda las hojas seleccionadas en la base de datos
    #     """
    #     HojasSeleccionadas.objects.all().delete()
    #     listo_obj = [
    #         HojasSeleccionadas(hoja=hoja)
    #         for hoja in hojas_seleccionadas
    #     ]
    #     # Guardamos todas las reglas de una vez
    #     HojasSeleccionadas.objects.bulk_create(listo_obj)

    def update_filtered_view(self):
        """Actualiza la vista con el queryset filtrado después de cambios en los datos"""
        self.table.clear_cache()
        # Aplicar el queryset según el estado actual del filtro
        if self.is_filtered:
            # Mantener el filtro activo
            self.set_custom_queryset(self.get_filtered_queryset())
        else:
            # Mantener mostrando todos
            self.set_custom_queryset(Comparativa.objects.all())

    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def carga_odoo(self):
        """Carga datos de Odoo usando el manager de lógica de negocio"""
        self.cancel_selection()
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
            
    def toggle_price_filter(self):
        """
        Alterna entre mostrar todos los productos o solo los que tienen precios distintos
        """
        
        if self.is_filtered:
            # Actualmente filtrado, mostrar todos
            self.set_custom_queryset(Comparativa.objects.all())
            self.is_filtered = False
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando todos los productos")))
        else:
            # Actualmente mostrando todos, aplicar filtro
            filtered_queryset = self.get_filtered_queryset()
            self.set_custom_queryset(filtered_queryset)
            self.is_filtered = True
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando productos filtrados")))

    def eliminar_chip(self, hoja):
        """Elimina una hoja de la lista de chips y actualiza la base de datos"""
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        
        # Obtener hojas actuales excepto la que se va a eliminar
        # hojas_restantes = [h.data for h in self.chips if h.data != hoja]
        self.component_chips.remove_chip(hoja)
        self.cancel_selection()
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        self.cancel_selection()
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
