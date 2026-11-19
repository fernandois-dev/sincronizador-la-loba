import asyncio
import datetime
import re
from components.loading import Loading
from logger_config import get_logger
from modules.servidor.business_logic import OdooSyncManager, TablaBaseManager

logger = get_logger(__name__)
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_resolucion_duplicados import DlgUnificarDuplicados
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

from django.db.models import F, Q
from django.db.models.functions import Lower, Trim
from django.db import transaction

from utilities.conditions import Conditions



class SincronizaBarcodePage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Comparativa Codigos de Barra"
        self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = True
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "existe", "desc_ok", "tb_barcode", "odoo_barcode"],
            fields_conditions_display={
                "tb_barcode": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if self.normalize_barcode(obj.tb_barcode) != self.normalize_barcode(obj.odoo_barcode) else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
                "odoo_barcode": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if self.normalize_barcode(obj.tb_barcode) != self.normalize_barcode(obj.odoo_barcode) else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
            }
        )
        self.custom_actions = self.build_custom_actions()

        self.page.update()
        self.build_page()
        
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))

    def normalize_barcode(self, barcode):
        """
        Normaliza un código de barras para comparación consistente
        eliminando caracteres problemáticos del escáner
        """
        if not barcode:
            return None
        
        # Convertir a string y eliminar espacios
        barcode = str(barcode).strip()
        
        # Eliminar caracteres no alfanuméricos comunes que pueden introducir los escáneres
        # barcode = re.sub(r'[^\w\-]', '', barcode)
        
        # Eliminar caracteres de control y caracteres especiales problemáticos
        barcode = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', barcode)
        
        # Convertir a mayúsculas para consistencia
        barcode = barcode.upper()
        
        # Validar longitud mínima
        if len(barcode) < 3:
            return None
            
        return barcode if barcode else None

    def build_page(self):
        super().build_page()
        self.page.update()
        
    def get_filtered_queryset(self):
        """Retorna el queryset filtrado para mostrar solo productos con códigos de barras distintos (case-insensitive y sin espacios)"""
        from django.db.models.functions import Lower, Trim
        
        return Comparativa.objects.filter(existe=True).exclude(
            Q(tb_barcode__isnull=True) | Q(odoo_barcode__isnull=True)
        ).annotate(
            tb_barcode_clean=Lower(Trim('tb_barcode')),
            odoo_barcode_clean=Lower(Trim('odoo_barcode'))
        ).exclude(
            tb_barcode_clean=F('odoo_barcode_clean')
        )

    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Codigos de Barra',
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

    @tarea_async
    async def gestor_sincronizacion(self, lista_de_productos):
        """Gestor para sincronizar códigos de barras de productos con normalización robusta"""
        self.loading.show("Obteniendo productos...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar

        try:
            if self.all_records_selected:
                lista_de_productos = list(self.paginator.object_list) if self.paginator else []
            filas_a_actualizar = [
                obj for obj in lista_de_productos
                if self.normalize_barcode(obj.tb_barcode) != self.normalize_barcode(obj.odoo_barcode) and obj.existe
            ]
            if not filas_a_actualizar:
                self.loading.hide()
                logger.info("Sincronización de barcodes: no hay productos con códigos distintos.")
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con códigos de barras distintos para sincronizar.")))
                return

            logger.info("Iniciando sincronización de barcodes. Productos con diferencia: %d", len(filas_a_actualizar))
            self.loading.show("Buscando códigos que ya usa otro producto...")
            await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
            conflictos, limpias = await asyncio.to_thread(DuplicadosManager.detectar_conflictos_barcode, filas_a_actualizar)
            self.loading.hide()
            if conflictos:
                abrir_unico(self.page, DlgUnificarDuplicados(
                    page=self.page,
                    conflictos=conflictos,
                    cantidad_limpias=len(limpias),
                    fn_continuar=lambda: self.confirmar_sincronizacion(limpias),
                    fn_cancelar=self.update_filtered_view,
                ))
            else:
                self.confirmar_sincronizacion(limpias)
        except Exception as e:
            self.loading.hide()
            logger.error("Error al preparar sincronización de barcodes.", exc_info=True)
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar códigos de barras: {str(e)}", bgcolor=ft.Colors.ERROR)))


    def confirmar_sincronizacion(self, filas_a_actualizar):
        """Abre la confirmación para las filas cuyo código no usa otro producto."""
        if not filas_a_actualizar:
            # Puede venir de unificar duplicados: la vista ya cambió.
            self.update_filtered_view()
            return
        abrir_unico(self.page, DlgConfirmacionSincronizacion(
            page=self.page,
            filas_a_actualizar=filas_a_actualizar,
            fields=["producto", "tb_barcode", "odoo_barcode"],
            fn_sincronizar=lambda fila: self.sincronizacion_odoo_barcode(fila),
            fn_continuar=self.update_filtered_view
        ))

    def sincronizacion_odoo_barcode(self, fila):
        logger.debug("Sincronizando barcode: '%s' | TB=%s → Odoo", fila.producto, fila.tb_barcode)
        resultado = OdooService.set_productos({"id": fila.producto_id, "barcode": fila.tb_barcode})
        if resultado.get("state") == "S":
            OdooSyncManager.actualizar_barcode_producto_local(fila.producto_id, fila.tb_barcode)
            logger.debug("Barcode actualizado OK: '%s'", fila.producto)
        else:
            logger.warning("Fallo al actualizar barcode de '%s': %s", fila.producto, resultado.get("msg"))
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

    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        self.cancel_selection()
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
        Alterna entre mostrar todos los productos o solo los que tienen códigos de barras distintos
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
            abrir_unico(self.page, ft.SnackBar(ft.Text("Mostrando solo productos con códigos de barras distintos")))
            
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
