from components.loading import Loading
from logger_config import get_logger
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager
from modules.servidor.components.dlg_productos_compartidos import sincronizar_con_consulta
from modules.servidor.models import Comparativa
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_unico
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from utilities.conditions import Conditions

logger = get_logger(__name__)


class SincronizaDescripcionPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Sincronización de Descripciones"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "existe", "desc_ok", "producto", "odoo_producto"],
            fields_conditions_display={
                "producto": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if not obj.desc_ok else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "odoo_producto": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if not obj.desc_ok else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
            },
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
        """Productos existentes y activos cuya descripción difiere entre TB y Odoo."""
        return Comparativa.objects.filter(existe=True, odoo_activo=True, desc_ok=False)

    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Descripciones',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e),
            },
        ]

    def gestor_sincronizacion(self, lista_de_productos):
        self.loading.show("Obteniendo productos...")
        try:
            if self.all_records_selected:
                lista_de_productos = list(self.paginator.object_list) if self.paginator else []

            filas_a_actualizar = [obj for obj in lista_de_productos if not obj.desc_ok and obj.existe]
            self.loading.hide()
            logger.info("Iniciando sincronización de descripciones. Productos con diferencia: %d", len(filas_a_actualizar))
            sincronizar_con_consulta(
                self, filas_a_actualizar, ["producto"], "descripción",
                fields=["producto", "odoo_producto"],
                fn_a_odoo=self.sincronizacion_odoo_descripcion,
                fn_continuar=self.update_filtered_view,
            )
        except Exception as e:
            self.loading.hide()
            logger.error("Error al preparar sincronización de descripciones.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def sincronizacion_odoo_descripcion(self, fila):
        logger.debug("Sincronizando descripción: id=%s TB='%s' → Odoo", fila.producto_id, fila.producto)
        resultado = OdooService.set_nombre_producto(fila.producto_id, fila.producto)
        if resultado.get("state") == "S":
            OdooSyncManager.actualizar_nombre_producto_local(fila.producto_id, fila.producto)
            self.propagador.registrar(fila.producto_id, {"producto": fila.producto})
            logger.debug("Descripción actualizada OK: '%s'", fila.producto)
        else:
            logger.warning("Fallo al actualizar descripción de '%s': %s", fila.producto, resultado.get("msg"))
        return resultado

    def build_custom_buttons(self):
        return [
            boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base)),
            boton_recargar_tb(lambda e: self.recargar_tabla_base()),
            boton_cargar_odoo(lambda e: self.carga_odoo()),
            ft.Switch(
                value=True,
                on_change=lambda e: self.toggle_filter(),
                label_position=ft.LabelPosition.LEFT,
                thumb_icon=ft.Icons.FILTER_ALT,
                tooltip="Filtrar productos con descripciones distintas",
            ),
        ]

    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        self.cancel_selection()
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def recargar_tabla_base(self):
        self.cancel_selection()
        return TablaBaseManager.cargar_tabla_base(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def update_filtered_view(self):
        self.table.clear_cache()
        if self.is_filtered:
            self.set_custom_queryset(self.get_filtered_queryset())
        else:
            self.set_custom_queryset(Comparativa.objects.filter(odoo_activo=True))

    def carga_odoo(self):
        self.cancel_selection()
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def toggle_filter(self):
        if self.is_filtered:
            self.set_custom_queryset(Comparativa.objects.filter(odoo_activo=True))
            self.is_filtered = False
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando todos los productos activos")))
        else:
            self.set_custom_queryset(self.get_filtered_queryset())
            self.is_filtered = True
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando solo productos con descripciones distintas")))

    def eliminar_chip(self, hoja):
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        self.component_chips.remove_chip(hoja)
        self.cancel_selection()
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def limpiar_tablas(self):
        self.cancel_selection()
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )
