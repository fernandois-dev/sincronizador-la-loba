import asyncio
import datetime
from components.custom_input import DisplayMode
from components.loading import Loading
from modules.servidor.business_logic import ConteoManager, OdooSyncManager, TablaBaseManager
from modules.servidor.components.dlg_confirmacion_carga_conteo import DlgConfirmacionCargaConteo
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
from components.custom_buttons import CustomButtonCupertino
from components.custom_dialogs import DlgConfirm
from logger_config import get_logger
import flet as ft
from utilities.flet_compat import abrir_unico, tarea_async
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb

from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions

logger = get_logger(__name__)


class NuevoStockPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=Comparativa):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Ingreso Nuevo Stock"
        self.custom_queryset = None
        self.btn_cargar_conteo = CustomButtonCupertino(
            text='Conteo',
            icon=ft.Icons.UPLOAD_FILE,
            on_click=lambda e: self.abrir_carga_conteo(),
            bgcolor=ft.Colors.SECONDARY,
            color=ft.Colors.ON_SECONDARY,
            visible=False,
        )
        self.chip_filtro_conteo = ft.Chip(
            label=ft.Text(""),
            on_delete=lambda e: self.quitar_filtro_conteo(),
            visible=False,
        )
        self._hoja_conteo_actual = None
        self._ids_conteo = set()  # productos cuyo nuevo stock vino del último conteo cargado
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = False
        self.conditions = Conditions(
            fields_order=["ref_interna", "producto", "existe", "desc_ok", "odoo_stock", "new_stock"],
            fields_descriptions={"new_stock": "Nuevo Stock"},
            overrides_display_mode={"new_stock": DisplayMode.EDIT},
        )
        
        self.custom_actions = self.build_custom_actions()

        self.page.update()
        self.build_page()
        
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        self.actualizar_visibilidad_btn_conteo()

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
        resultado = OdooService.set_inventario(fila.producto_id, fila.new_stock, ajuste=False, motivo="Nuevo Stock desde Gestor La Loba")
        if resultado.get("state") == "S":
            OdooSyncManager.actualizar_stock_producto_local(fila.producto_id, fila.new_stock)
        return resultado

    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base)),
            boton_recargar_tb(lambda e: self.recargar_tabla_base()),
            boton_cargar_odoo(lambda e: self.carga_odoo()),
            self.btn_cargar_conteo,
        ]

    def actualizar_visibilidad_btn_conteo(self):
        """Muestra el botón 'Conteo' solo si hay una única hoja de tabla base cargada."""
        self.btn_cargar_conteo.visible = ConteoManager.obtener_hoja_actual() is not None
        try:
            if self.btn_cargar_conteo.page is not None:
                self.btn_cargar_conteo.update()
        except (AssertionError, AttributeError, RuntimeError):
            pass

    @tarea_async
    async def abrir_carga_conteo(self):
        """Busca la hoja de conteo correspondiente a la hoja de tabla base cargada y muestra el diálogo de confirmación."""
        nombre_hoja_tb = ConteoManager.obtener_hoja_actual()
        if not nombre_hoja_tb:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Selecciona una única hoja de tabla base para cargar el conteo.")))
            return

        self.loading.show("Buscando hoja de conteo...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
        try:
            hoja, filas = await asyncio.to_thread(ConteoManager.cargar_conteo_proveedor, nombre_hoja_tb)
        except Exception as e:
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al leer la hoja de conteo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            return
        self.loading.hide()

        if not hoja:
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"No se encontró hoja de conteo para '{nombre_hoja_tb}'.", bgcolor=ft.Colors.ERROR)))
            return
        if not filas:
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"La hoja '{hoja}' no tiene productos con nuevo registro de stock.")))
            return

        self._hoja_conteo_actual = hoja
        dlg = DlgConfirmacionCargaConteo(page=self.page, hoja=hoja, filas=filas, fn_aceptar=self.aplicar_conteo)
        abrir_unico(self.page, dlg)

    def aplicar_conteo(self, filas):
        """
        Guarda el nuevo stock contado en cada producto, filtra la tabla a solo esos
        productos y los deja seleccionados para poder usar 'Actualizar Stock' directo.
        """
        ids_actualizados = set()
        for obj, nuevo_valor in filas:
            obj.new_stock = nuevo_valor
            obj.save(update_fields=["new_stock"])
            ids_actualizados.add(obj.id)
        self._ids_conteo = ids_actualizados

        self.table.clear_cache()
        self.set_custom_queryset(Comparativa.objects.filter(id__in=ids_actualizados))
        self.seleccionar_filas_por_id(ids_actualizados)
        self.mostrar_filtro_conteo()
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"{len(filas)} productos actualizados y seleccionados. Usa 'Actualizar Stock' para aplicarlos en Odoo.")))

    def mostrar_filtro_conteo(self):
        """Muestra el chip indicador (junto a los chips de hojas, después de 'TODOS')."""
        self.chip_filtro_conteo.label.value = f"Filtrado: Conteo ({self._hoja_conteo_actual})"
        self.chip_filtro_conteo.visible = True
        if self.chip_filtro_conteo not in self.component_chips.controls:
            self.component_chips.controls.append(self.chip_filtro_conteo)
        self.component_chips.visible = True
        try:
            if self.component_chips.page is not None:
                self.component_chips.update()
        except (AssertionError, AttributeError, RuntimeError):
            pass

    def quitar_filtro_conteo(self):
        """Quita el filtro del conteo y vuelve a mostrar todos los productos."""
        self.chip_filtro_conteo.visible = False
        if self.chip_filtro_conteo in self.component_chips.controls:
            self.component_chips.controls.remove(self.chip_filtro_conteo)
        try:
            if self.component_chips.page is not None:
                self.component_chips.update()
        except (AssertionError, AttributeError, RuntimeError):
            pass
        self.update_filtered_view()

    def seleccionar_filas_por_id(self, ids):
        """Marca el checkbox solo de las filas visibles cuyo id esté en `ids`."""
        for row in self.table.component_body.controls:
            row.set_value_chk_row(getattr(row.obj, 'id', None) in ids)
        lista_seleccionados = self.table.list_rows_selected()
        if self.table.on_row_selected:
            self.table.on_row_selected(lista_seleccionados)
        self.table.header.manage_chk_header(len(lista_seleccionados), len(self.table.component_body.controls))
        self.page.update()

    def build_custom_actions(self):
        return [
            {
                'text': 'Actualizar Stock',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.gestor_sincronizacion(e)
            },
        ]
        
        
    def gestor_sincronizacion(self, lista_de_productos):
        """Gestor para sincronizar precios de productos"""
        self.loading.show("Obteniendo productos...")
        
        try:
            if self.all_records_selected:
                # Si todos los registros están seleccionados, obtener todos los productos
                lista_de_productos = list(self.paginator.object_list) if self.paginator else []
            filas_a_actualizar = [obj for obj in lista_de_productos if obj.existe]
            self.loading.hide()
            if filas_a_actualizar:
                en_cero = [f for f in filas_a_actualizar if not f.new_stock and f.odoo_stock]
                del_conteo = sum(1 for f in filas_a_actualizar if f.id in self._ids_conteo)
                detalle = (
                    f"Selección: {'todos los registros' if self.all_records_selected else 'filas marcadas'} "
                    f"({len(filas_a_actualizar)}) | Del conteo: {del_conteo}"
                    f"{f' (hoja {self._hoja_conteo_actual})' if self._ids_conteo else ' (sin conteo cargado)'}"
                    f" | Quedan en 0: {len(en_cero)}"
                    f"{' (alerta aceptada)' if en_cero else ''}"
                )
                aviso = (
                    f"⚠ {len(en_cero)} de {len(filas_a_actualizar)} productos tienen Nuevo Stock en 0 "
                    f"y quedarán en 0 en Odoo."
                ) if en_cero else None
                # Mostrar información de cuántas filas se van a modificar
                dlg = DlgConfirmacionSincronizacion(
                    page=self.page,
                    filas_a_actualizar=filas_a_actualizar,
                    fields=["producto", "odoo_stock", "new_stock"],
                    fn_sincronizar=lambda fila: self.sincronizacion_odoo_stocks(fila),
                    fn_continuar=self.update_filtered_view,
                    aviso=aviso,
                    detalle=detalle,
                )
                if en_cero:
                    self.alerta_stock_cero(en_cero, len(filas_a_actualizar), lambda: abrir_unico(self.page, dlg))
                else:
                    abrir_unico(self.page, dlg)

            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con stock modificado para modificar.")))
        except Exception as e:
            # Ocultar loading en caso de error
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al sincronizar stock: {str(e)}", bgcolor=ft.Colors.ERROR)))
        
    def alerta_stock_cero(self, en_cero, total, fn_continuar):
        """Alerta previa a la confirmación cuando hay productos con stock en Odoo que quedarían en 0."""
        logger.warning("Alerta de stock 0: %d de %d productos quedarían en 0.", len(en_cero), total)
        todos = len(en_cero) == total
        contenido = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(
                        f"{len(en_cero)} de {total} productos tienen Nuevo Stock en 0 "
                        f"y su stock en Odoo quedará en 0.",
                        weight=ft.FontWeight.BOLD,
                    ),
                    *([ft.Text("Todos los productos seleccionados van en 0. ¿Se cargó el conteo?",
                               color=ft.Colors.ERROR, weight=ft.FontWeight.BOLD)] if todos else []),
                    ft.Column(
                        controls=[
                            ft.Text(f"• {f.producto}  (Odoo: {f.odoo_stock} → 0)", size=12, selectable=True)
                            for f in en_cero
                        ],
                        scroll=ft.ScrollMode.ALWAYS,
                        expand=True,
                    ),
                    ft.Text("¿Continuar de todos modos?"),
                ],
                expand=True,
            ),
            width=550,
            height=350,
        )
        DlgConfirm(
            page=self.page,
            title="⚠ Atención: productos quedarán con stock 0",
            content=contenido,
            fn_yes=fn_continuar,
            fn_no=lambda: logger.info("Alerta de stock 0: el usuario canceló la actualización."),
        )

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
                for modified_obj in self.table.get_all_objects():
                    # Verificar si el stock fue modificado y es diferente de 0
                    # if hasattr(modified_obj, 'new_stock') and \
                    #     modified_obj.new_stock != 0 and \
                    #     isinstance(modified_obj.new_stock, (int, float)) and \
                    #     modified_obj.new_stock != modified_obj.odoo_stock and \
                    #     modified_obj.existe:
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
                # Mostrar información de cuántas filas se van a modificar
                dlg = DlgConfirmacionSincronizacion(
                    page=self.page,
                    filas_a_actualizar=filas_a_actualizar,
                    fields=["producto", "odoo_stock", "new_stock"],
                    fn_sincronizar=lambda fila: self.sincronizacion_odoo_stocks(fila),
                    fn_continuar=self.update_filtered_view
                )
                abrir_unico(self.page, dlg)

            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con stock modificado para modificar.")))

        except Exception as e:
            # Ocultar loading en caso de error
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al modificar stock: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        # Corregir el lambda para capturar la variable hoja correctamente
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        self.cancel_selection()
        self._ids_conteo = set()

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
        self._ids_conteo = set()
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
        print("Vista actualizada con filtro:", self.is_filtered)
        self.actualizar_visibilidad_btn_conteo()
        if self.chip_filtro_conteo.visible:
            self.chip_filtro_conteo.visible = False
            if self.chip_filtro_conteo in self.component_chips.controls:
                self.component_chips.controls.remove(self.chip_filtro_conteo)
            try:
                if self.component_chips.page is not None:
                    self.component_chips.update()
            except (AssertionError, AttributeError, RuntimeError):
                pass

    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        self.cancel_selection()
        self._ids_conteo = set()
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def carga_odoo(self):
        """Carga datos de Odoo usando el manager de lógica de negocio"""
        self.cancel_selection()
        self._ids_conteo = set()
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
        self.cancel_selection()
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

