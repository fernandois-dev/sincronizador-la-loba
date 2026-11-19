import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo, tarea_async
from components.generic_inputs import GenericSearchField
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager
from modules.servidor.data_manage import DataManage
from components.custom_buttons import CustomIconButton, boton_cargar_datos, boton_cargar_odoo
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import HojasSeleccionadas, OdooProveedor
from modules.servidor.odoo import OdooService

_LOCATION_ALIASES = {
    "virtual": "Virtual",
    "customers": "Cliente",
    "suppliers": "Proveedor",
    "inventory": "Inventario",
    "transit": "Tránsito",
    "stock": "Stock",
}

def _short_location(loc) -> str:
    if not loc:
        return "—"
    name = loc[1] if isinstance(loc, (list, tuple)) and len(loc) > 1 else str(loc)
    low = name.lower()
    for key, alias in _LOCATION_ALIASES.items():
        if key in low:
            return alias
    parts = name.split("/")
    return parts[-1].strip() if parts else name

class ReporteStockPage(PaginaFija, ft.Column):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.row_height = 35
        self.loading = Loading(self.page, open=False)
        self.data_original = []
        self.data_filtrada = []
        self.proveedor_id = None
        self.data_proveedores: list[OdooProveedor] = []
        self.estado_seleccionado = None
        self.selected_ids = set()
        self.editing_id = None # ID del producto que se está editando
        self.get_proveedores()
        self.build_ui()
        
        # Colores para los estados de riesgo
        self.colores_riesgo = {
            "CRITICO": ft.Colors.RED_400,
            "SOLICITAR": ft.Colors.ORANGE_400,
            "OK": ft.Colors.GREEN_400
        }
        
        # Control de ordenamiento
        self.orden_actual = {"campo": "riesgo", "direccion": "asc"}

    def did_mount(self):
        # verificamos si hay alguna hoja seleccionada en la tabla HojasSeleccionadas
        proveedor = None
        try:
            hojas = HojasSeleccionadas.objects.all()
            if hojas.exists() and hojas.count() == 1:
                hoja = hojas.first()
                # obtengo el id desde la hoja
                sheet_proveedor = GoogleService.get_proveedor(hoja.hoja)
                proveedor = OdooProveedor.objects.filter(id=sheet_proveedor["id"]).first()
            # self.page.update()
        except Exception as e:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error al cargar configuración de hoja: {e}"))) 
        finally:
            pass
        if proveedor:
            # se deja none en favoritos
            self.tgl_favoritos.value = None
            self.filtro_proveedor.set_initial_value(value=proveedor.name, data={"id": proveedor.id, "name": proveedor.name})
            self.filtro_proveedor.update()
    
    def get_proveedores(self):
        """Obtiene la lista de proveedores desde Odoo"""
        try:
            self.data_proveedores = DataManage.get_proveedores_con_productos()
        except Exception as e:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error al obtener proveedores: {e}")))
            self.data_proveedores = []
    
    
    def build_ui(self):
        # Filtros
        self.filtro_proveedor = GenericSearchField(
            name="proveedor",
            page=self.page,
            label="Proveedor",
            width=400,
            on_change=self.handle_on_change,
            handle_search=lambda val: self.buscar_proveedor(val)
        )
        
        self.filtro_estado = ft.Dropdown(
            label="Estado",
            width=150,
            text_size=12,
            text_style=ft.TextStyle(size=10),
            options=[
                ft.DropdownOption("TODOS", "TODOS"),
                ft.DropdownOption("CRITICO", "CRITICO"),
                ft.DropdownOption("URGENTE", "URGENTE"),
                ft.DropdownOption("ATENCION", "ATENCION"),
                ft.DropdownOption("OK", "OK")
            ],
            value="TODOS"
        )
        
        self.filtro_producto = ft.TextField(
            label="Buscar Producto",
            width=250,
            height=35,
            text_size=12,
            on_submit=lambda e: self.cargar_datos()
        )
        
        self.btn_cargar_odoo = boton_cargar_odoo(self._ejecutar_carga_odoo_products, height=35)

        self.tgl_favoritos = ft.Switch(label="", value=True, thumb_icon=ft.Icons.STAR, active_color=ft.Colors.YELLOW_700)
        
        self.btn_cargar = boton_cargar_datos(self.cargar_datos, height=35)
        
        
        # Contenedor de filtros
        self.filtros_container = ft.Row(
            [
                ft.Row(
                    controls=[
                        self.filtro_proveedor,
                        self.filtro_producto,
                        self.tgl_favoritos,
                        self.btn_cargar,
                    ]
                ),
            ],
            spacing=10,
            wrap=True
        )
        
        # Tabla
        self.tabla = self.build_table()
        
        # Estadísticas
        self.stats_container = ft.Row(
            [],
            spacing=15,
            wrap=True
        )
        
        # Layout principal
        self.spacing = 0
        self.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Row([
                        ft.Text("Reporte de Stock la Loba", size=24, weight=ft.FontWeight.BOLD),
                        self.btn_cargar_odoo,
                        ], alignment=ft.MainAxisAlignment.START),
                    ft.Divider(height=2, color=ft.Colors.BLUE_700)
                ]),
                padding=10
            ),
            ft.Container(
                content=self.filtros_container,
                padding=10,
                # bgcolor=ft.Colors.SURFACE_CONTAINER,
                # border_radius=10
            ),
            ft.Divider(),
            ft.Container(
                content=self.stats_container,
                padding=10
            ),
            ft.Column(
                controls=[self.tabla],
                expand=True,
                scroll=ft.ScrollMode.AUTO
            )
        ]
        
    def buscar_proveedor(self, text_busqueda):
        # estructura retorno [{"id": id, "name": name}, ...]
        ret = []
        for proveedor in self.data_proveedores:
            if text_busqueda.lower() in proveedor.name.lower():
                ret.append({"id": proveedor.id, "name": proveedor.name})
        if len(ret) == 1:
            self.tgl_favoritos.value = None
        return ret
        
    def handle_on_change(self, e=None, value=None):
        if value:
            self.proveedor_id = value
            self.cargar_datos()
            return
        if e:
            self.proveedor_id = e.control.data
            # deja favorito como none
            self.tgl_favoritos.value = None
            self.cargar_datos()
            return
        self.proveedor_id = None
        
    @tarea_async
    async def _ejecutar_carga_odoo_products(self, e=None):
        """Carga productos de Odoo usando el manager de lógica de negocio"""

        # Una carga después de la otra (las dos recalculan la comparativa).
        await OdooSyncManager.cargar_rutas_odoo.ahora(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=None
        )

        return await OdooSyncManager.cargar_productos_odoo.ahora(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def update_filtered_view(self):
       # limpia filtros y datos de la tabla
        self.filtro_proveedor.value = ""
        self.filtro_producto.value = ""
        self.filtro_estado.value = "TODOS"
        self.proveedor_id = None
        self.data_original = []
        self.data_filtrada = []
        self.actualizar_tabla()
        self.actualizar_estadisticas()
        
    def build_table(self):
        return ft.DataTable(
            columns=[
                ft.DataColumn(
                    label=ft.GestureDetector(
                        content=ft.Row([
                            ft.Text("Producto", size=13, weight=ft.FontWeight.BOLD),
                            ft.Icon(ft.Icons.ARROW_DOWNWARD, size=12, visible=False)
                        ], spacing=5),
                        on_tap=lambda e: self.ordenar_por("producto")
                    )
                ),
                ft.DataColumn(
                    ft.Text("Proveedor", size=13, weight=ft.FontWeight.BOLD)
                ),
                ft.DataColumn(
                    ft.Text("Precio", size=13, weight=ft.FontWeight.BOLD),
                    numeric=True
                ),
                ft.DataColumn(
                    ft.Text("Stock", size=13, weight=ft.FontWeight.BOLD),
                    numeric=True
                ),
                ft.DataColumn(
                    ft.Text("_Mín_", size=13, weight=ft.FontWeight.BOLD),
                    numeric=True
                ),
                ft.DataColumn(
                    ft.Text("_Máx_", size=13, weight=ft.FontWeight.BOLD),
                    numeric=True
                ),
                ft.DataColumn(
                    label=ft.GestureDetector(
                        content=ft.Row([
                            ft.Text("Estado", size=13, weight=ft.FontWeight.BOLD),
                            ft.Icon(ft.Icons.ARROW_DOWNWARD, size=12, visible=True)
                        ], spacing=5),
                        on_tap=lambda e: self.ordenar_por("riesgo")
                    )
                ),
            ],
            rows=[],
            border=ft.Border.all(1, ft.Colors.GREY_400),
            border_radius=10,
            vertical_lines=ft.BorderSide(1, ft.Colors.GREY_300),
            horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_300),
            heading_row_color=ft.Colors.BLUE_GREY_100,
            heading_row_height=40,
            data_row_min_height=40,
            # data_row_max_height=self.row_height,
            column_spacing=10,
            show_checkbox_column=False,
        )
        
    @tarea_async
    async def cargar_datos(self, e=None, show_loading=True):
        try:
            if show_loading:
                self.loading.show("Generando reporte de stock...")
                await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
            self.estado_seleccionado = None
            self.filtro_estado.value = "TODOS"
            self.selected_ids.clear()
            # self.filtro_estado.update()
            
            proveedor_id = self.proveedor_id["id"] if self.proveedor_id else None
            riesgo = self.filtro_estado.value if self.filtro_estado.value != "TODOS" else None
            producto = self.filtro_producto.value.strip() if self.filtro_producto.value.strip() else None
            favorito = self.tgl_favoritos.value if self.tgl_favoritos.value else None
            # Obtener datos del reporte
            self.data_original = await asyncio.to_thread(DataManage.reporte_stock, proveedor_id, producto, riesgo, favorito=favorito)

            # Limitar resultados a 1000 registros para evitar sobrecarga en la UI
            MAX_RECORDS = 1000
            if isinstance(self.data_original, list) and len(self.data_original) > MAX_RECORDS:
                abrir_dialogo(self.page, 
                    ft.SnackBar(
                        content=ft.Text(f"Se limitaron los resultados a {MAX_RECORDS} registros para mejorar el rendimiento."),
                        bgcolor=ft.Colors.ORANGE_700
                    )
                )
                self.data_original = self.data_original[:MAX_RECORDS]
            
            if not self.data_original:
                abrir_dialogo(self.page, 
                    ft.SnackBar(
                        content=ft.Text("No se encontraron datos"),
                        bgcolor=ft.Colors.ORANGE_700
                    )
                )
                # return
            
            # Extraer proveedores únicos para el filtro
            proveedores = set()
            for item in self.data_original:
                if item.get("partner"):
                    proveedores.add(item["partner"])
            
            # Actualizar opciones del dropdown de proveedores
            self.filtro_proveedor.options = [ft.DropdownOption("TODOS", "TODOS")]
            for proveedor in sorted(proveedores):
                self.filtro_proveedor.options.append(
                    ft.DropdownOption(proveedor, proveedor)
                )
            self.filtro_proveedor.update()
            
            # Aplicar filtros y mostrar datos
            self.data_filtrada = self.data_original.copy()
            # Ordenar por defecto por estado
            self.orden_actual = {"campo": "riesgo", "direccion": "asc"}
            self.ordenar_datos()
            self.actualizar_tabla()
            self.actualizar_estadisticas()
            
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Se cargaron {len(self.data_original)} registros"),
                    bgcolor=ft.Colors.GREEN_700
                )
            )
            
        except Exception as ex:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Error al cargar datos: {str(ex)}"),
                    bgcolor=ft.Colors.RED_700
                )
            )
        finally:
            if show_loading:
                self.loading.hide()
            
    def aplicar_filtros(self, e=None):
        if not self.data_original:
            return
            
        self.data_filtrada = []
        
        proveedor_filtro = self.filtro_proveedor.value
        estado_filtro = self.filtro_estado.value
        producto_filtro = self.filtro_producto.value.upper().strip()
        
        for item in self.data_original:
            # # Filtro por proveedor
            # if proveedor_filtro != "TODOS" and item.get("proveedor_id") != proveedor_filtro:
            #     continue
                
            # Filtro por estado
            if estado_filtro == "TODOS" or item.get("riesgo") == estado_filtro:
                self.data_filtrada.append(item)
        
        self.actualizar_tabla()
        self.actualizar_estadisticas()
        
    def handle_row_click(self, item):
        """Maneja el click en una fila para entrar en modo edición"""
        if self.editing_id == item.get("id"):
            return
            
        self.editing_id = item.get("id")
        self.edit_min = ft.TextField(
            value=str(int(item.get("stock_min", 0))),
            width=120,
            height=40,
            text_size=12,
            content_padding=5,
            keyboard_type=ft.KeyboardType.NUMBER
        )
        self.edit_max = ft.TextField(
            value=str(int(item.get("stock_max", 0))),
            width=120,
            height=40,
            text_size=12,
            content_padding=5,
            keyboard_type=ft.KeyboardType.NUMBER
        )
        self.actualizar_tabla()

    def guardar_cambios(self, e):
        """Guarda los cambios de stock mínimo y máximo"""
        try:
            min_val = float(self.edit_min.value)
            max_val = float(self.edit_max.value)
            
            if DataManage.update_stock_limits(self.editing_id, min_val, max_val):
                abrir_dialogo(self.page, ft.SnackBar(ft.Text("Límites actualizados correctamente"), bgcolor=ft.Colors.GREEN_700))
                # Actualizar el item en la data local para no recargar todo si es posible, 
                # pero para mantener consistencia con los cálculos de riesgo, recargamos.
                id_editado = self.editing_id
                self.editing_id = None
                self.cargar_datos()
            else:
                abrir_dialogo(self.page, ft.SnackBar(ft.Text("Error al actualizar límites"), bgcolor=ft.Colors.RED_700))
        except ValueError:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("Valores inválidos"), bgcolor=ft.Colors.RED_700))

    def cancelar_edicion(self, e):
        """Cancela la edición actual"""
        self.editing_id = None
        self.actualizar_tabla()


    def ordenar_por(self, campo):
        if not self.data_filtrada:
            return
            
        # Toggle dirección si es el mismo campo
        if self.orden_actual["campo"] == campo:
            self.orden_actual["direccion"] = "desc" if self.orden_actual["direccion"] == "asc" else "asc"
        else:
            self.orden_actual["campo"] = campo
            self.orden_actual["direccion"] = "asc"
            
        self.ordenar_datos()
        self.actualizar_tabla()
        
    def ordenar_datos(self):
        """Ordena data_filtrada según orden_actual"""
        if not self.data_filtrada:
            return
            
        campo = self.orden_actual["campo"]
        direccion = self.orden_actual["direccion"]
        reverso = (direccion == "desc")
        
        if campo == "riesgo":
            # Orden personalizado para riesgo
            orden_riesgo = {"CRITICO": 0, "SOLICITAR": 1, "OK": 2}
            self.data_filtrada.sort(
                key=lambda x: orden_riesgo.get(x.get("riesgo", "OK"), 4),
                reverse=reverso
            )
        else:
            # Ordenar por descripción de producto
            self.data_filtrada.sort(
                key=lambda x: (x.get(campo, "") or "").upper(),
                reverse=reverso
            )
        
    def actualizar_tabla(self):
        self.tabla.rows.clear()
        
        # Actualizar indicadores de ordenamiento en columnas
        # Solo las columnas 0 (Producto) y 6 (Estado) tienen iconos de ordenamiento
        columnas_ordenables = {
            0: "producto",  # Columna Producto
            6: "riesgo"     # Columna Estado
        }
        
        for idx, campo in columnas_ordenables.items():
            col = self.tabla.columns[idx]
            # El label es un GestureDetector que contiene un Row
            if hasattr(col.label, 'content') and isinstance(col.label.content, ft.Row):
                row = col.label.content
                if len(row.controls) > 1:
                    icon_widget = row.controls[1]  # El Icon
                    
                    if campo == self.orden_actual["campo"]:
                        icon_widget.visible = True
                        icon_widget.icon = ft.Icons.ARROW_UPWARD if self.orden_actual["direccion"] == "desc" else ft.Icons.ARROW_DOWNWARD
                    else:
                        icon_widget.visible = False
        
        for item in self.data_filtrada:
            riesgo = item.get("riesgo", "OK")
            color_riesgo = self.colores_riesgo.get(riesgo, ft.Colors.GREY_400)
            item_id = item.get("id")
            
            is_editing = item_id == self.editing_id
            
            if is_editing:
                celda_min = self.edit_min
                celda_max = self.edit_max
            else:
                # Botones con área de clic ampliada para activar la edición en min/max
                celda_min = ft.Container(
                    content=ft.Text(f"{item.get('stock_min', 0):.0f}", size=12, color=ft.Colors.BLUE_700, weight=ft.FontWeight.BOLD),
                    on_click=lambda e, it=item: self.handle_row_click(it),
                    tooltip="Click para editar límites",
                    padding=ft.Padding.symmetric(vertical=8, horizontal=15),
                    alignment=ft.Alignment.CENTER,
                    bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE_700),
                    border_radius=8,
                    ink=True,
                )
                celda_max = ft.Container(
                    content=ft.Text(f"{item.get('stock_max', 0):.0f}", size=12, color=ft.Colors.BLUE_700, weight=ft.FontWeight.BOLD),
                    on_click=lambda e, it=item: self.handle_row_click(it),
                    tooltip="Click para editar límites",
                    padding=ft.Padding.symmetric(vertical=8, horizontal=15),
                    alignment=ft.Alignment.CENTER,
                    bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.BLUE_700),
                    border_radius=8,
                    ink=True,
                )
            
            # Nombre del producto con estrella si es favorito + botón movimientos
            nombre_producto = item.get("producto", "")
            btn_movimientos = ft.Container(
                content=ft.Icon(ft.Icons.SWAP_VERT, size=14, color=ft.Colors.BLUE_400),
                on_click=lambda e, p=nombre_producto: self._show_movimientos_modal(p),
                tooltip="Ver movimientos",
                padding=ft.Padding.all(3),
                border_radius=4,
                ink=True,
            )
            if item.get("favorito"):
                content_producto = ft.Row([
                    ft.Icon(ft.Icons.STAR, color=ft.Colors.YELLOW_700, size=16),
                    ft.Text(nombre_producto, size=12, max_lines=2, expand=True),
                    btn_movimientos,
                ], spacing=5, alignment=ft.MainAxisAlignment.START)
            else:
                content_producto = ft.Row([
                    ft.Text(nombre_producto, size=12, max_lines=2, expand=True),
                    btn_movimientos,
                ], spacing=5, alignment=ft.MainAxisAlignment.START)

            # Celda de estado o botones de edición
            if is_editing:
                celda_estado = ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.CHECK_CIRCLE,
                        icon_color=ft.Colors.GREEN_700,
                        tooltip="Guardar",
                        on_click=self.guardar_cambios,
                        icon_size=20
                    ),
                    ft.IconButton(
                        icon=ft.Icons.CANCEL,
                        icon_color=ft.Colors.RED_700,
                        tooltip="Cancelar",
                        on_click=self.cancelar_edicion,
                        icon_size=20
                    )
                ], spacing=0, alignment=ft.MainAxisAlignment.CENTER)
            else:
                celda_estado = ft.Container(
                    content=ft.Text(riesgo, size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    bgcolor=color_riesgo,
                    padding=5,
                    border_radius=5,
                    alignment=ft.Alignment.CENTER
                )

            row = ft.DataRow(
                cells=[
                    ft.DataCell(content_producto),
                    ft.DataCell(ft.Text(item.get("proveedor", ""), size=12)),
                    ft.DataCell(ft.Text(f"${item.get('precio', 0):,.0f}".replace(",", "."), size=12)),
                    ft.DataCell(ft.Text(f"{item.get('stock', 0):.0f}", size=12)),
                    ft.DataCell(celda_min),
                    ft.DataCell(celda_max),
                    ft.DataCell(celda_estado),
                ],
                selected=item_id in self.selected_ids,
                on_select_change=lambda e, i_id=item_id: self.handle_selection_change(e, i_id),
            )
            self.tabla.rows.append(row)
            
        self.tabla.update()

    def handle_selection_change(self, e, item_id):
        is_selected = str(e.data).lower() == "true"
        if is_selected:
            self.selected_ids.add(item_id)
        else:
            self.selected_ids.discard(item_id)

        e.control.selected = is_selected
        e.control.update()

    def actualizar_estadisticas(self):
        if not self.data_original:
            self.stats_container.controls.clear()
            self.stats_container.update()
            return
            
        # Contar por estado
        conteo = {"CRITICO": 0, "SOLICITAR": 0, "OK": 0}
        for item in self.data_original:
            estado = item.get("riesgo", "OK")
            conteo[estado] += 1
                
        # Crear tarjetas de estadísticas
        self.stats_container.controls.clear()
        
        for estado, cantidad in conteo.items():
            color = self.colores_riesgo.get(estado, ft.Colors.GREY_400)
            # Resaltar tarjeta si está seleccionada
            border_style = ft.Border.all(2, ft.Colors.BLACK) if self.estado_seleccionado == estado else None
            card = ft.Container(
                content=ft.Column([
                    ft.Text(estado, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Text(str(cantidad), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                bgcolor=color,
                padding=15,
                border_radius=10,
                width=120,
                height=80,
                border=border_style,
                on_click=lambda e, est=estado: self._filtrar_por_riesgo(est)
            )
            self.stats_container.controls.append(card)
            
        # Agregar total
        total_card = ft.Container(
            content=ft.Column([
                ft.Text("TOTAL", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text(str(len(self.data_original)), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
            bgcolor=ft.Colors.BLUE_700,
            padding=15,
            border_radius=10,
            width=120,
            height=80
        )
        # Click en TOTAL limpia el filtro por estado
        total_card.on_click = lambda e: self._filtrar_por_riesgo(None)
        self.stats_container.controls.append(total_card)
        
        self.stats_container.update()

    def _filtrar_por_riesgo(self, estado):
        """Filtra la tabla por el estado de riesgo al hacer click en una tarjeta.

        Si `estado` es None limpia el filtro (TODOS).
        """
        # Toggle: si se hace click en la misma tarjeta, deselecciona
        if estado is None:
            self.estado_seleccionado = None
            self.filtro_estado.value = "TODOS"
        else:
            if self.estado_seleccionado == estado:
                self.estado_seleccionado = None
                self.filtro_estado.value = "TODOS"
            else:
                self.estado_seleccionado = estado
                self.filtro_estado.value = estado

        # Aplicar filtros y refrescar UI
        # self.filtro_estado.update()
        self.aplicar_filtros()
        
    def _show_movimientos_modal(self, producto_nombre):
        content_col = ft.Column(
            controls=[
                ft.Row(
                    controls=[ft.ProgressRing(width=20, height=20, stroke_width=2), ft.Text("Consultando Odoo...", size=12)],
                    spacing=8,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SWAP_VERT, color=ft.Colors.ORANGE_700),
                    ft.Text(f"Movimientos: {producto_nombre[:60]}", size=14, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            ),
            content=ft.Container(content=content_col, width=560, height=360),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)

        async def _fetch():
            try:
                moves = await asyncio.to_thread(OdooService.get_movimientos_producto, producto_nombre)
                if not moves:
                    rows = [ft.DataRow(cells=[
                        ft.DataCell(ft.Text("Sin movimientos", color=ft.Colors.GREY_500, italic=True)),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                    ])]
                else:
                    rows = [
                        ft.DataRow(cells=[
                            ft.DataCell(ft.Text(str(m.get("date", ""))[:10], size=11)),
                            ft.DataCell(ft.Text(
                                str(m.get("origin") or "—"),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                color=ft.Colors.BLUE_700,
                            )),
                            ft.DataCell(ft.Text(
                                _short_location(m.get("location_id")),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            )),
                            ft.DataCell(ft.Text(
                                _short_location(m.get("location_dest_id")),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            )),
                            ft.DataCell(ft.Text(
                                f"{m.get('qty_done', 0):g}",
                                size=12, weight=ft.FontWeight.W_500,
                                color=ft.Colors.GREEN_700 if m.get("qty_done", 0) > 0 else ft.Colors.RED_700,
                            )),
                        ])
                        for m in moves
                    ]
                tabla = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Fecha", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Referencia", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Desde", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Hacia", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Cant.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                    ],
                    rows=rows,
                    column_spacing=12,
                    heading_row_height=32,
                    data_row_min_height=28,
                    data_row_max_height=32,
                )
                content_col.controls = [ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO)]
            except Exception as ex:
                content_col.controls = [ft.Text(f"Error: {ex}", color=ft.Colors.RED_500, size=12)]
            content_col.update()

        self.page.run_task(_fetch)
