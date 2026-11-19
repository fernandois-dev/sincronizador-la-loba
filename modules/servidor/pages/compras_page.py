import datetime
from components.custom_input import SearchField
from components.loading import Loading
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasTablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft

from utilities.flet_compat import abrir_unico
from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions



class ComprasPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Compras"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "existe", "desc_ok", "tb_precio", "odoo_precio"],
            fields_conditions_display={
                "tb_precio": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_precio !=  obj.odoo_precio else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "odoo_precio": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_precio !=  obj.odoo_precio else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
            }
        )
        self.custom_actions = self.build_custom_actions()

        self.page.update()
        self.build_page()
        # Corregir el lambda para capturar la variable hoja correctamente
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))

    def build_page(self):
        super().build_page()
        self.page.update()
        
    def get_filtered_queryset(self):
        """Retorna el queryset filtrado para mostrar solo productos con precios distintos que existan"""
        return Comparativa.objects.filter(existe=True).exclude(tb_precio=F('odoo_precio'))
    
    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Precios',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e)
            },
        ]
    
    def _ejecutar_carga_odoo_products(self):
        """Carga productos de Odoo usando el manager de lógica de negocio"""
        return OdooSyncManager.cargar_productos_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def gestor_sincronizacion(self, lista_de_productos):
        """Gestor para sincronizar precios de productos"""
        self.loading.show("Obteniendo productos...")
        
        try:
            filas_a_actualizar = [obj for obj in lista_de_productos if obj.tb_precio != obj.odoo_precio and obj.existe]
            self.loading.hide()
            if filas_a_actualizar:
                dlg = DlgConfirmacionSincronizacion(
                    page=self.page,
                    filas_a_actualizar=filas_a_actualizar,
                    fields=["producto", "tb_precio", "odoo_precio"],
                    fn_sincronizar=lambda fila: self.sincronizacion_odoo_precios(fila),
                    fn_continuar=self._ejecutar_carga_odoo_products
                )
                abrir_unico(self.page, dlg)
            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con precios distintos para sincronizar.")))
                return
        except Exception as e:
            # Ocultar loading en caso de error
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar precios: {str(e)}", bgcolor=ft.Colors.ERROR)))

    
    def sincronizacion_odoo_precios(self, fila):
        return OdooService.set_productos({"id": fila.producto_id, "list_price": fila.tb_precio})
    
    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            SearchField(
                on_search=lambda e: self.buscar_producto(e.control.value)
            )

        ]
        
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

    def carga_odoo(self):
        """Carga datos de Odoo usando el manager de lógica de negocio"""
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
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando solo productos con precios distintos")))
            
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
        
    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )