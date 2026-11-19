import datetime
from components.custom_input import DisplayMode
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager, TablaBaseManager
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_unico
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions



class AjusteStockPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Ajuste de Stock"
        self.custom_queryset = None
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = False
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "existe", "desc_ok", "odoo_stock", "new_stock"],
            overrides_display_mode={"new_stock": DisplayMode.EDIT},
        )
        self.is_chk_column_enabled = False  # Deshabilitar la columna de selección por defecto

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
        return Comparativa.objects.exclude(tb_stock=F('odoo_stock'))
    
    def _ejecutar_carga_odoo_products(self):
        """Carga productos de Odoo usando el manager de lógica de negocio"""
        return OdooSyncManager.cargar_productos_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
    
    def sincronizacion_odoo_stocks(self, fila):
        resultado = OdooService.set_inventario(fila.producto_id, fila.new_stock, ajuste=True, motivo="Ajuste de Stock desde Gestor La Loba")
        if resultado.get("state") == "S":
            OdooSyncManager.actualizar_stock_producto_local(fila.producto_id, fila.new_stock)
        return resultado

    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base)),
            boton_recargar_tb(lambda e: self.recargar_tabla_base()),
            boton_cargar_odoo(lambda e: self.carga_odoo()),
            {
                'text': 'Sync Stock',
                'icon': ft.Icons.SYNC,
                'function': lambda: self.get_modified_stock(),
                'bgcolor': ft.Colors.SECONDARY,
                'color': ft.Colors.ON_SECONDARY
            }
        ]

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
                    fn_continuar=self.update_filtered_view,
                    detalle=f"Ajuste (suma) de {len(filas_a_actualizar)} filas con valor distinto de 0",
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
        
        """Carga la tabla base usando el manager de lógica de negocio"""
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def recargar_tabla_base(self):
        """Recarga la tabla base usando el manager de lógica de negocio"""
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
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
            
    def eliminar_chip(self, hoja):
        """Elimina una hoja de la lista de chips y actualiza la base de datos"""
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        
        # Obtener hojas actuales excepto la que se va a eliminar
        # hojas_restantes = [h.data for h in self.chips if h.data != hoja]
        self.component_chips.remove_chip(hoja)
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

