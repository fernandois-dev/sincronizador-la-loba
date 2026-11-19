import asyncio

import csv

from components.custom_buttons import CustomButtonCupertino, CustomIconButton, boton_cargar_odoo, boton_exportar
from components.estilos import BOTON_EXITO
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager
from modules.servidor.models import CompraOdoo
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
from datetime import datetime
from components.custom_dialogs import DlgAlert, DlgConfirm

import flet as ft

from utilities.flet_compat import abrir_dialogo, abrir_unico, cerrar_dialogo, guardar_archivo
from utilities.conditions import Conditions



class ListaOrdenesCompraPage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=CompraOdoo):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Lista de OC"
        self.custom_queryset = None
        self.build_ui()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = True
        self.display_btn_delete = False
        self.display_btn_new = False
        self.is_chk_column_enabled = False
        # self.display_search = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = False
        self.table_handle_on_long_press = self.handle_on_long_press
        self.conditions = Conditions(
            fields_order=["name", "fecha", "proveedor", "neto", "iva", "total"],
        )
        # self.custom_actions = self.build_custom_actions()
        self.custom_queryset = CompraOdoo.objects.filter(estado='purchase')

        self.page.update()


        self.build_page()
        self.page.update()
        
    def did_mount(self):
        """Recarga órdenes si viene con flag de reload en la ruta."""
        reload_flag = self.params.get("reload") if isinstance(self.params, dict) else None
        if reload_flag in ("1", "true", "True", True, 1):
            self.carga_oc()

    def build_btn_editar(self):
        return CustomButtonCupertino(
            text="Ver Detalle",
            icon=ft.Icons.INFO,
            on_click=lambda e: self.display_form(e) if self.display_btn_edit else None
        )

    def build_menu_table(self):
        self.btn_eliminar_oc = CustomButtonCupertino(
            text="Eliminar OC",
            icon=ft.Icons.DELETE_FOREVER,
            bgcolor=ft.Colors.RED_700,
            color=ft.Colors.WHITE,
            visible=False,
            on_click=lambda e: None,
        )
        return ft.Row(
            controls=[
                self.component_left_buttons,
                self.component_search if self.display_search else ft.Container(),
                self.btn_editar,
                self.btn_eliminar_oc,
                self.component_seleccionados,
                self.component_actions,
            ],
            alignment=ft.MainAxisAlignment.START,
            spacing=10,
        )

    def set_actions_menu(self, list_objs):
        if len(list_objs) == 1 and self.display_btn_edit:
            obj = list_objs[0]
            self.btn_editar.on_click = lambda e: self.display_form(obj)
            self.btn_editar.visible = True
            self.btn_eliminar_oc.on_click = lambda e: self._confirmar_eliminar_oc(obj)
            self.btn_eliminar_oc.visible = True
        else:
            self.btn_editar.visible = False
            self.btn_eliminar_oc.visible = False

        count = len(list_objs)
        self.component_seleccionados.manage_selection_display(count)
        self.component_left_buttons.visible = True
        self.component_search.visible = False
        self.component_actions.visible = False
        self.component_pagination.visible = True
        self.menu_table.update()
        self.component_seleccionados.update()

    def display_main(self):
        super().display_main()
        if hasattr(self, 'btn_eliminar_oc'):
            self.btn_eliminar_oc.visible = False

    def set_search_menu(self):
        super().set_search_menu()
        if hasattr(self, 'btn_eliminar_oc'):
            self.btn_eliminar_oc.visible = False
            self.menu_table.update()

    def _confirmar_eliminar_oc(self, obj):
        DlgConfirm(
            page=self.page,
            title=f"¿Cancelar y eliminar Compra {obj.id} - {obj.proveedor}?",
            content=ft.Text("Esta acción cancelará y eliminará la orden en Odoo y no se puede deshacer.", size=13),
            fn_yes=lambda: self._eliminar_oc(obj),
        )

    def _eliminar_oc(self, obj):
        abrir_dialogo(self.page, ft.SnackBar(
            content=ft.Text("Eliminando orden en Odoo..."),
            bgcolor=ft.Colors.BLUE_700,
        ))

        async def _do_delete():
            result = await asyncio.to_thread(OdooService.cancelar_y_eliminar_orden_compra_odoo, obj.id)
            if result.get("state") == "S":
                try:
                    obj.delete()
                except Exception:
                    pass
                abrir_dialogo(self.page, ft.SnackBar(
                    content=ft.Text("Orden cancelada y eliminada correctamente."),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                self.set_search_menu()
                self.update_filtered_view()
            else:
                msg_odoo = result.get("msg", "Error desconocido")
                self._ofrecer_opciones_con_recepciones(obj, msg_odoo)

        self.page.run_task(_do_delete)

    def _ofrecer_opciones_con_recepciones(self, obj, msg_odoo: str):
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Row(controls=[
                ft.Icon(ft.Icons.WARNING_AMBER_ROUNDED, color=ft.Colors.ORANGE_700),
                ft.Text("OC con recepciones completadas", size=14, weight=ft.FontWeight.BOLD),
            ], spacing=8),
            content=ft.Container(
                width=500,
                content=ft.Column(controls=[
                    ft.Text(msg_odoo, size=12, color=ft.Colors.RED_700),
                    ft.Divider(height=12),
                    ft.Text(
                        "La orden tiene recepciones validadas. Puedes:",
                        size=13, weight=ft.FontWeight.W_500,
                    ),
                    ft.Text(
                        "• Devolver y bloquear: regresa el stock a Odoo y bloquea la OC "
                        "(Odoo no permite eliminar una orden con recepciones validadas).",
                        size=12,
                    ),
                ], spacing=6, tight=True),
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dlg)),
                ft.FilledButton(
                    "Devolver y bloquear",
                    icon=ft.Icons.UNDO,
                    on_click=lambda e: self._devolver_y_bloquear_oc(obj, dlg),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        abrir_dialogo(self.page, dlg)

    def _devolver_y_bloquear_oc(self, obj, dlg):
        cerrar_dialogo(self.page, dlg)
        abrir_dialogo(self.page, ft.SnackBar(
            content=ft.Text("Devolviendo stock y bloqueando OC en Odoo..."),
            bgcolor=ft.Colors.BLUE_700,
        ))

        async def _do():
            result = await asyncio.to_thread(OdooService.devolver_y_bloquear_orden_compra_odoo, obj.id)
            if result.get("state") == "S":
                try:
                    obj.delete()
                except Exception:
                    pass
                abrir_dialogo(self.page, ft.SnackBar(
                    content=ft.Text("Stock devuelto y OC bloqueada correctamente."),
                    bgcolor=ft.Colors.GREEN_700,
                ))
                self.set_search_menu()
                self.update_filtered_view()
            else:
                abrir_dialogo(self.page, ft.SnackBar(
                    content=ft.Text(f"Error: {result.get('msg', 'Error desconocido')}"),
                    bgcolor=ft.Colors.RED_700,
                ))

        self.page.run_task(_do)

    def display_form(self, obj):
        content_dialog = self.build_content_dialog(obj)
        DlgAlert(self.page, title="Detalle de Compra", content=content_dialog)

    def handle_on_long_press(self, row):
        content_dialog = self.build_content_dialog(row)
        DlgAlert(self.page, title="Detalle de Compra", content=content_dialog)

    def build_content_dialog(self, rows):
        # crea tabla con detalle de la compra
        detalle = OdooService.obtiene_detalle_compra_odoo(rows.id)
        if detalle["state"] == "E":
            return ft.Column(controls=[
                ft.Text(f"Error: {detalle['msg']}")
            ])

        self._current_detail = detalle["detalle"]
        self._current_detail_row = rows

        # Agregar fila a la tabla
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Column(
                        controls=[
                            ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text("Producto")),
                                    ft.DataColumn(ft.Text("Cantidad")),
                                    ft.DataColumn(ft.Text("Precio Unitario")),
                                    ft.DataColumn(ft.Text("Total")),
                                ],
                                rows=[
                                    ft.DataRow(cells=[
                                        ft.DataCell(ft.Text(item["product_id"][1] if item["product_id"] else "Sin Producto")),
                                        ft.DataCell(ft.Text(str(item["product_qty"]))),
                                        ft.DataCell(ft.Text(self.formato_chileno(item["price_unit"]))),
                                        ft.DataCell(ft.Text(self.formato_chileno(item["product_qty"] * item["price_unit"]))),
                                    ])
                                    for item in detalle["detalle"]
                                ]
                            ),
                        ],
                        scroll=ft.ScrollMode.AUTO,
                        expand=True,
                    ),
                    ft.Divider(),
                    ft.Row(
                        alignment=ft.MainAxisAlignment.END,
                        controls=[
                            boton_exportar(lambda e: self.exportar_detalle_csv(), text="Exportar a CSV"),
                        ]
                    ),
                ],
                spacing=10,
                expand=True,
            ),
            height=500,
            width=700,
        )
    def formato_chileno(self, valor):
        # Asegura dos decimales, separador de miles punto y decimal coma
        return "${:,.0f}".format(valor).replace(",", "X").replace(".", ",").replace("X", ".")

    def exportar_detalle_csv(self):
        """Exporta el detalle de la compra actual a un archivo CSV usando FilePicker."""
        if not hasattr(self, '_current_detail') or not self._current_detail:
            abrir_unico(self.page, ft.SnackBar(ft.Text("No hay detalle para exportar.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        oc_name = getattr(self._current_detail_row, 'name', 'detalle_oc')
        # Sanitize filename
        safe_name = str(oc_name).replace("/", "_").replace("\\", "_")

        def on_save_result(e: ft.FilePickerResultEvent):
            if not e.path:
                return
            try:
                with open(e.path, 'w', newline='', encoding='utf-8-sig') as f:
                    writer = csv.writer(f, delimiter=';')
                    writer.writerow(["Producto", "Cantidad", "Precio Unitario", "Total"])
                    for item in self._current_detail:
                        producto = item["product_id"][1] if item["product_id"] else "Sin Producto"
                        cantidad = item["product_qty"]
                        precio = item["price_unit"]
                        total = cantidad * precio
                        writer.writerow([producto, cantidad, precio, total])
                abrir_unico(self.page, ft.SnackBar(ft.Text(f"Archivo exportado: {e.path}", color=ft.Colors.ON_PRIMARY), bgcolor=ft.Colors.PRIMARY))
            except Exception as ex:
                abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al exportar: {str(ex)}", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))

        guardar_archivo(self.page, on_save_result, 
            dialog_title="Guardar detalle de compra",
            file_name=f"{safe_name}.csv",
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["csv"],
        )

    def build_search(self):
        return ft.Container()
    
    def build_custom_actions(self):
        return [
            {
                'text': 'Sincronizar Precios',
                'icon': ft.Icons.SYNC,
                'function': lambda e: None
            },
        ]
        
    def build_ui(self):
        self.fecha_inicio_picker = ft.DatePicker(
            on_change=self.on_filtro_cambio
        )
        self.txt_fecha_inicio = ft.TextField(
            label="Fecha inicio",
            on_change=self.on_filtro_cambio,
            read_only=True,
            width=120,
        )
        self.btn_fecha_inicio_picker = CustomIconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            on_click=lambda e: abrir_dialogo(self.page, 
                self.fecha_inicio_picker
            ),
        )
        self.fecha_fin_picker = ft.DatePicker(
            on_change=self.on_filtro_cambio
        )
        self.txt_fecha_fin = ft.TextField(
            label="Fecha fin",
            on_change=self.on_filtro_cambio,
            read_only=True,
            width=120,
        )
        self.btn_fecha_fin_picker = CustomIconButton(
            icon=ft.Icons.CALENDAR_MONTH,
            on_click=lambda e: abrir_dialogo(self.page, 
                self.fecha_fin_picker
            ),
        )
        self.txt_proveedor = ft.TextField(
            label="Proveedor",
            on_change=self.on_filtro_cambio,
            width=150,
        )
        self.filtros_row = ft.ExpansionTile(
            title=ft.Text("Filtros", size=14),
            leading=ft.Icon(ft.Icons.FILTER_LIST, size=20),
            expanded=False,
            collapsed_text_color=ft.Colors.ON_SURFACE_VARIANT,
            controls=[
                ft.Container(
                    content=ft.Row(
                        controls=[
                            self.txt_fecha_inicio,
                            self.btn_fecha_inicio_picker,
                            self.txt_fecha_fin,
                            self.btn_fecha_fin_picker,
                            self.txt_proveedor,
                            CustomIconButton(
                                icon=ft.Icons.SEARCH,
                                on_click=lambda e: self.search_oc()
                            ),
                        ],
                        spacing=5,
                        alignment=ft.MainAxisAlignment.START,
                    ),
                    padding=ft.Padding.only(left=10, bottom=10),
                )
            ],
        )
        
    def on_filtro_cambio(self, e=None):
        if self.fecha_inicio_picker.value:
            self.fecha_inicio = str(self.fecha_inicio_picker.value)
            fecha_obj = datetime.strptime(self.fecha_inicio, "%Y-%m-%d %H:%M:%S")
            self.fecha_inicio = fecha_obj.strftime("%d/%m/%y")
            self.txt_fecha_inicio.value = str(self.fecha_inicio)

        if self.fecha_fin_picker.value:
            self.fecha_fin = str(self.fecha_fin_picker.value)
            fecha_obj = datetime.strptime(self.fecha_fin, "%Y-%m-%d %H:%M:%S")
            self.fecha_fin = fecha_obj.strftime("%d/%m/%y")
            self.txt_fecha_fin.value = str(self.fecha_fin)
        self.page.update()
        
    def build_controls(self):
        base_controls = super().build_controls()
        # Insert the collapsible filters row after the menu row (index 0)
        base_controls.insert(1, ft.Container(
            content=self.filtros_row,
            margin=ft.Margin.only(left=10, right=10),
        ))
        return base_controls

    def build_page(self):
        super().build_page()
        self.page.update()
        
    def get_filtered_queryset(self):
        """
        Retorna el queryset filtrado por fecha de inicio, fecha de fin y proveedor (like).
        """
        queryset = CompraOdoo.objects.filter(estado='purchase')

        # Filtrar por fecha de inicio
        if getattr(self, "fecha_inicio", None):
            try:
                fecha_inicio = datetime.strptime(self.fecha_inicio, "%d/%m/%y").date()
                queryset = queryset.filter(fecha__date__gte=fecha_inicio)
            except Exception:
                pass

        # Filtrar por fecha de fin
        if getattr(self, "fecha_fin", None):
            try:
                fecha_fin = datetime.strptime(self.fecha_fin, "%d/%m/%y").date()
                queryset = queryset.filter(fecha__date__lte=fecha_fin)
            except Exception:
                pass

        # Filtrar por proveedor (like)
        proveedor = getattr(self, "txt_proveedor", None)
        if proveedor and proveedor.value:
            queryset = queryset.filter(proveedor__icontains=proveedor.value.strip())

        return queryset
    
    def sincronizacion_odoo_stocks(self, fila):
        return OdooService.set_inventario(fila.producto_id, fila.new_stock)

    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            boton_cargar_odoo(lambda e: self.carga_oc(), text="OC",
                              tooltip="Cargar órdenes de compra desde Odoo"),
            {
                'text': 'Nueva Compra',
                'icon': ft.Icons.ADD_SHOPPING_CART,
                'function': lambda: self.ir_a_nueva_compra(),
                'bgcolor': BOTON_EXITO[0],
                'color': BOTON_EXITO[1]
            },
        ]
        
    def search_oc(self):
        self.is_filtered = True
        self.set_custom_queryset(self.get_filtered_queryset())
    
    def ir_a_nueva_compra(self):
        """Navega a la página de nueva compra"""
        self.page.custom_go("/compras/orden_compra?return_to=/compras/orden_compra")
        
    def update_filtered_view(self):
        """Actualiza la vista con el queryset filtrado después de cambios en los datos"""
        self.table.clear_cache()
        # Aplicar el queryset según el estado actual del filtro
        if self.is_filtered:
            # Mantener el filtro activo
            self.set_custom_queryset(self.get_filtered_queryset())
        else:
            # Mantener mostrando todos
            self.set_custom_queryset(CompraOdoo.objects.filter(estado='purchase'))

    def carga_oc(self):
        """Carga datos de Odoo usando el manager de lógica de negocio"""
        return OdooSyncManager.cargar_oc_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )