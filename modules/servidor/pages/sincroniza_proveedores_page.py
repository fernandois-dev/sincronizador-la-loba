from components.loading import Loading
from logger_config import get_logger
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager
from modules.servidor.models import Comparativa, OdooTarifa
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_unico
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from django.db.models import F, Max, Q
from django.db.models.functions import Trim, Upper

from utilities.conditions import Conditions

logger = get_logger(__name__)


def _codigo(valor):
    return (valor or "").strip().upper()


def proveedores_pendientes():
    """Filas de productos existentes cuya línea de proveedor falta o no coincide con la hoja."""
    return Comparativa.objects.filter(existe=True, tb_proveedor__isnull=False).annotate(
        codigo_tb=Upper(Trim("ref_interna")),
        codigo_odoo=Upper(Trim("odoo_codigo_proveedor")),
    ).filter(
        Q(tarifa_id__isnull=True)
        | ~Q(codigo_odoo=F("codigo_tb"))
        | (Q(tb_precio_compra__gt=0) & ~Q(tb_precio_compra=F("odoo_precio_compra")))
    )


class SincronizaProveedoresPage(GenericPage):
    """
    Registra en la pestaña Compra de Odoo (product.supplierinfo) el proveedor
    de cada hoja con la REF de la fila como "código del proveedor" y su precio
    de compra ($ Final). Esa línea es la que vincula cada hoja con el producto,
    también cuando el producto se compra a varios proveedores.
    """

    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Proveedores (pestaña Compra de Odoo)"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "tb_proveedor", "odoo_codigo_proveedor",
                          "tb_precio_compra", "odoo_precio_compra"],
            fields_conditions_display={
                "odoo_codigo_proveedor": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER}
                    if not obj.tarifa_id or _codigo(obj.odoo_codigo_proveedor) != _codigo(obj.ref_interna)
                    else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "tb_precio_compra": lambda obj: self._color_precio(obj),
                "odoo_precio_compra": lambda obj: self._color_precio(obj),
            },
        )
        self.custom_actions = self.build_custom_actions()

        self.page.update()
        self.build_page()
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))

    @staticmethod
    def _precio_distinto(obj):
        return (obj.tb_precio_compra or 0) > 0 and obj.tb_precio_compra != obj.odoo_precio_compra

    def _color_precio(self, obj):
        distinto = not obj.tarifa_id or self._precio_distinto(obj)
        return {"bgcolor": ft.Colors.ERROR_CONTAINER if distinto else ft.Colors.PRIMARY_CONTAINER}

    def build_page(self):
        super().build_page()
        self.page.update()

    def get_filtered_queryset(self):
        return proveedores_pendientes()

    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Proveedores',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e),
            },
        ]

    def gestor_sincronizacion(self, lista_de_productos):
        self.loading.show("Obteniendo productos...")
        try:
            if self.all_records_selected:
                lista_de_productos = list(self.paginator.object_list) if self.paginator else []

            filas_a_actualizar = [
                obj for obj in lista_de_productos
                if obj.existe and obj.tb_proveedor_id and (
                    not obj.tarifa_id
                    or _codigo(obj.odoo_codigo_proveedor) != _codigo(obj.ref_interna)
                    or self._precio_distinto(obj))
            ]
            self.loading.hide()
            if filas_a_actualizar:
                logger.info("Iniciando sincronización de proveedores. Filas: %d", len(filas_a_actualizar))
                abrir_unico(self.page, DlgConfirmacionSincronizacion(
                    page=self.page,
                    filas_a_actualizar=filas_a_actualizar,
                    fields=["producto", "tb_proveedor", "ref_interna", "odoo_codigo_proveedor",
                            "tb_precio_compra", "odoo_precio_compra"],
                    fn_sincronizar=lambda fila: self.sincronizacion_proveedor(fila),
                    fn_continuar=self.update_filtered_view,
                ))
            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("Todas las filas tienen su proveedor registrado en Odoo.")))
        except Exception as e:
            self.loading.hide()
            logger.error("Error al preparar sincronización de proveedores.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def sincronizacion_proveedor(self, fila):
        """Crea o completa la línea de proveedor de la hoja en el producto de Odoo."""
        codigo = (fila.ref_interna or "").strip()
        tarifa = OdooTarifa.objects.filter(id=fila.tarifa_id).first() if fila.tarifa_id else None
        if tarifa:
            secuencia = tarifa.sequence
        else:
            secuencia = (OdooTarifa.objects.filter(product_tmpl_id=fila.producto_id)
                         .aggregate(m=Max("sequence"))["m"] or 0) + 1
        precio = fila.tb_precio_compra if (fila.tb_precio_compra or 0) > 0 else None

        resultado = OdooService.set_tarifas({
            "id": tarifa.id if tarifa else None,
            "product_tmpl_id": fila.producto_id,
            "partner_id": fila.tb_proveedor_id,
            "price": precio if (precio or tarifa) else 0,
            "sequence": secuencia,
            "product_code": codigo,
        })
        if resultado.get("state") != "S":
            logger.warning("Fallo al registrar proveedor de '%s': %s", fila.producto, resultado.get("msg"))
            return resultado

        tarifa_id = resultado.get("id") or (tarifa.id if tarifa else None)
        defaults = {
            "partner_id": fila.tb_proveedor_id,
            "partner": str(fila.tb_proveedor).strip(),
            "product_tmpl_id": fila.producto_id,
            "product_tmpl": f"[{fila.ref_interna}] {fila.odoo_producto or fila.producto}",
            "sequence": secuencia,
            "product_code": codigo,
        }
        if precio is not None:
            defaults["price"] = precio
        OdooTarifa.objects.update_or_create(id=tarifa_id, defaults=defaults)
        precio_odoo = precio if precio is not None else (tarifa.price if tarifa else 0)
        Comparativa.objects.filter(id=fila.id).update(
            tarifa_id=tarifa_id, odoo_codigo_proveedor=codigo, odoo_precio_compra=precio_odoo,
            odoo_proveedor_id=fila.tb_proveedor_id,
        )

        antes = f" (antes código '{tarifa.product_code}')" if tarifa and tarifa.product_code and _codigo(tarifa.product_code) != _codigo(codigo) else ""
        accion = "actualizada" if tarifa else "creada"
        return {"state": "S", "msg": f"Línea de {str(fila.tb_proveedor).strip()} {accion}: código {codigo}{antes}, "
                                     f"precio compra {precio_odoo}"}

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
                tooltip="Filtrar filas con proveedor faltante o distinto",
            )
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
            update_view_callback=self.update_filtered_view
        )

    def recargar_tabla_base(self):
        self.cancel_selection()
        return TablaBaseManager.cargar_tabla_base(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def update_filtered_view(self):
        self.table.clear_cache()
        if self.is_filtered:
            self.set_custom_queryset(self.get_filtered_queryset())
        else:
            self.set_custom_queryset(Comparativa.objects.filter(existe=True))

    def carga_odoo(self):
        self.cancel_selection()
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def toggle_filter(self):
        if self.is_filtered:
            self.set_custom_queryset(Comparativa.objects.filter(existe=True))
            self.is_filtered = False
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando todos los productos existentes")))
        else:
            self.set_custom_queryset(self.get_filtered_queryset())
            self.is_filtered = True
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando solo filas con proveedor faltante o distinto")))

    def eliminar_chip(self, hoja):
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        self.component_chips.remove_chip(hoja)
        self.cancel_selection()
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def limpiar_tablas(self):
        self.cancel_selection()
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
