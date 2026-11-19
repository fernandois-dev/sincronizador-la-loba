import datetime
from components.loading import Loading
from logger_config import get_logger
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager

logger = get_logger(__name__)
from modules.servidor.data_manage import DataManage
from modules.servidor.components.dlg_productos_compartidos import sincronizar_con_consulta
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_unico
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from django.db.models import F, Q

from utilities.conditions import Conditions



class SincronizaAbastecimientoPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Comparativa Abastecimiento"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "existe", "desc_ok", "tb_min", "odoo_min", "tb_max", "odoo_max"],
            fields_conditions_display={
                "tb_min": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_min != obj.odoo_min else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "odoo_min": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_min != obj.odoo_min else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "tb_max": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_max != obj.odoo_max else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "odoo_max": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_max != obj.odoo_max else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
            }
        )
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
        """Retorna el queryset filtrado para mostrar solo productos con cantidades mínimas o máximas distintas"""
        return Comparativa.objects.filter(
            existe=True  # Solo productos que existen
        ).filter(
            ~Q(tb_min=F('odoo_min')) | ~Q(tb_max=F('odoo_max'))
        )
    
    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar R. Abastecimiento',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e)
            },
            {
                'text': 'Corregir Descripciones',
                'icon': ft.Icons.CLEANING_SERVICES,
                'function': lambda e: self.gestor_sincronizacion_descripciones(e)
            }
        ]
    
    def _ejecutar_carga_odoo_abastecimiento(self):
        """Carga rutas de abastecimiento de Odoo usando el manager de lógica de negocio"""
        return OdooSyncManager.cargar_rutas_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def gestor_sincronizacion(self, lista_de_productos):
        """Gestor para sincronizar rutas de abastecimiento"""
        if self.all_records_selected:
            lista_de_productos = list(self.paginator.object_list) if self.paginator else []

        filas_a_actualizar = [obj for obj in lista_de_productos if (obj.tb_min != obj.odoo_min or obj.tb_max != obj.odoo_max) and obj.existe]
        try:
            logger.info("Iniciando sincronización de abastecimiento. Productos con diferencia: %d", len(filas_a_actualizar))
            sincronizar_con_consulta(
                self, filas_a_actualizar, ["min", "max"], "mínimo y máximo",
                fields=["producto", "tb_min", "odoo_min", "tb_max", "odoo_max"],
                fn_a_odoo=self.sincronizacion_odoo,
                fn_continuar=self._ejecutar_carga_odoo_abastecimiento,
            )
        except Exception as e:
            self.loading.hide()
            logger.error("Error al preparar sincronización de abastecimiento.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar cantidades: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def gestor_sincronizacion_descripciones(self, lista_de_productos):
        """Gestor para sincronizar descripciones de productos"""
        if self.all_records_selected:
            # Si todos los registros están seleccionados, obtener todos los productos
            lista_de_productos = list(self.paginator.object_list) if self.paginator else []
            
        filas_a_actualizar = [obj for obj in lista_de_productos if (obj.tb_min != obj.odoo_min or obj.tb_max != obj.odoo_max) and obj.existe]
        dlg = DlgConfirmacionSincronizacion(
            page=self.page,
            filas_a_actualizar=filas_a_actualizar,
            fields=["producto"],
            fn_sincronizar=lambda fila: self.cambiar_descripcion_producto(fila),
            fn_continuar=self._ejecutar_carga_odoo_abastecimiento
        )
        try:
            if filas_a_actualizar:
                abrir_unico(self.page, dlg)
            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con cantidades distintas para sincronizar.")))
                return
        except Exception as e:
            # Ocultar loading en caso de error
            try: dlg.close()
            except: pass
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar cantidades: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def cambiar_descripcion_producto(self, fila):
        """Cambia la descripción del producto en Odoo"""
        return OdooService.set_descripcion_producto_odoo(
            product_id=fila.producto_id,
            nueva_descripcion=fila.desc_ok
        )
    
    def sincronizacion_odoo(self, fila):
        logger.debug("Sincronizando abastecimiento: '%s' | min=%s→%s max=%s→%s", fila.producto, fila.odoo_min, fila.tb_min, fila.odoo_max, fila.tb_max)
        resultado = OdooService.set_rutas(
            {"id": fila.ruta_id,
             "product_id": fila.producto_id,
             "product_min_qty": fila.tb_min,
             "product_max_qty": fila.tb_max,
             "location_id": 8})
        if resultado.get("state") == "S":
            self.propagador.registrar(fila.producto_id, {"min": fila.tb_min, "max": fila.tb_max})
            logger.debug("Abastecimiento actualizado OK: '%s'", fila.producto)
        else:
            logger.warning("Fallo al actualizar abastecimiento de '%s': %s", fila.producto, resultado.get("msg"))
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
        
    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        """Carga la tabla base usando el manager de lógica de negocio"""
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        self.cancel_selection()

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

    def gestiona_hojas_seleccionadas(self, hojas_seleccionadas):
        """ Guarda las hojas seleccionadas en la base de datos
        """
        HojasSeleccionadas.objects.all().delete()
        listo_obj = [
            HojasSeleccionadas(hoja=hoja)
            for hoja in hojas_seleccionadas
        ]
        # Guardamos todas las reglas de una vez
        HojasSeleccionadas.objects.bulk_create(listo_obj)

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
        self.cancel_selection()
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def toggle_price_filter(self):
        """
        Alterna entre mostrar todos los productos o solo los que tienen precios distintos<
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