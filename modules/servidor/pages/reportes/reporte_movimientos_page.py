import asyncio
import flet as ft
import flet_charts as fch
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo, tarea_async
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager, ReporteMovimientosProducto
from modules.servidor.odoo import OdooService
import datetime
from components.custom_buttons import CustomButtonCupertino
from components.generic_inputs import GenericSearchField

class ReporteMovimientosPage(PaginaFija, ft.Column):
    titulo = "Reporte de Movimientos"
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.id_hoja = None
        self.build_ui()
        self.notifications = []
        self.loading = Loading(self.page, open=False)
        self.row_height = 30
        self.column_proyeccion_color = ft.Colors.RED_100
        self.column_promedio_color = ft.Colors.BLUE_100
        self.selected_row_index = None  # Para trackear la fila seleccionada
        
    def handle_change(self, e):
        # Determinar cuál campo está siendo actualizado basado en el campo activo
        if hasattr(self, 'campo_fecha_activo') and self.campo_fecha_activo:
            fecha_seleccionada = e.control.value.strftime('%d/%m/%Y')
            self.campo_fecha_activo.value = fecha_seleccionada
            self.campo_fecha_activo.update()
            print(f"Fecha actualizada en {self.campo_fecha_activo}: {fecha_seleccionada}")

    def handle_dismissal(self, e):
        # Limpiar referencia al campo activo cuando se cierra el picker
        self.campo_fecha_activo = None

    def build_ui(self):
        self.tabla = self.build_table()
        self.search_button = self.build_search_button()
        
        # Campos de fecha
        # Calcular 3 meses atrás del mes actual y tomar el primer día
        hoy = datetime.date.today()
        año_tres_meses_atras = hoy.year
        mes_tres_meses_atras = hoy.month - 3
        
        # Ajustar año si el mes resulta negativo
        if mes_tres_meses_atras <= 0:
            año_tres_meses_atras -= 1
            mes_tres_meses_atras += 12
            
        fecha_desde_defecto = datetime.date(año_tres_meses_atras, mes_tres_meses_atras, 1)
        
        self.txt_fecha_desde = ft.TextField(
            value=fecha_desde_defecto.strftime('%d/%m/%Y'), 
            width=120,
            height=35,
            text_size=12,
            label="Fecha Desde",
            read_only=True
        )
        self.txt_fecha_hasta = ft.TextField(
            value=datetime.date.today().strftime('%d/%m/%Y'), 
            width=120,
            height=35,
            text_size=12,
            label="Fecha Hasta",
            read_only=True
        )
        
        # Referencia para saber qué campo está activo
        self.campo_fecha_activo = None
        
        # DatePicker compartido
        self.date_picker = ft.DatePicker(
            first_date=datetime.datetime(year=2000, month=1, day=1),
            last_date=datetime.datetime(year=datetime.date.today().year + 1, month=12, day=31),
            on_change=self.handle_change,
            on_dismiss=self.handle_dismissal,
        )
        
        # Agregar el DatePicker a la página para que esté disponible
        self.page.overlay.append(self.date_picker)
        self.chk_comprado = ft.Checkbox(label="Comprados", value=True, on_change=lambda e: self.filtrar_datos(), height=35, scale=0.9)
        self.chk_vendido = ft.Checkbox(label="Vendidos", value=True, on_change=lambda e: self.filtrar_datos(), height=35, scale=0.9)
        self.chk_stock = ft.Checkbox(label="Stock", value=False, on_change=lambda e: self.filtrar_datos(), height=35, scale=0.9)
        self.chk_ajuste_stock = ft.Checkbox(label="Ajuste de stock", value=False, on_change=lambda e: self.filtrar_datos(), height=35, scale=0.9)
        self.btn_ver_grafica = CustomButtonCupertino(
            text="Ver Gráfica",
            icon=ft.Icons.SHOW_CHART,
            bgcolor=ft.Colors.INDIGO_500,
            color=ft.Colors.ON_SECONDARY,
            on_click=self.mostrar_grafica,
            disabled=True
        )
        
        self.chk_list = ft.Row(controls=[
            self.chk_comprado,
            self.chk_vendido,
            self.chk_stock,
            self.chk_ajuste_stock,
            ft.VerticalDivider(width=20),
            self.btn_ver_grafica
        ], height=35)
        
        
        
        self.search_button.disabled = True
        
        self.controls = [
            ft.Row([
                GenericSearchField(
                    name="proveedor",
                    page=self.page,
                    label="Proveedor",
                    width=300,
                    on_change=self.handle_on_change,
                    handle_search=lambda val: self.buscar_hoja(val)
                ),
                self.txt_fecha_desde,
                ft.TextButton(
                    content=ft.Row([ft.Icon(icon=ft.Icons.DATE_RANGE, size=20)]),
                    width=32,
                    height=32,
                    style=ft.ButtonStyle(
                        padding=ft.Padding.all(3),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        shape=ft.RoundedRectangleBorder(radius=3),
                    ),
                    on_click=lambda e: self.abrir_date_picker(self.txt_fecha_desde),
                    tooltip="Seleccionar fecha desde"
                ),
                self.txt_fecha_hasta,
                ft.TextButton(
                    content=ft.Row([ft.Icon(icon=ft.Icons.DATE_RANGE, size=20)]),
                    width=32,
                    height=32,
                    style=ft.ButtonStyle(
                        padding=ft.Padding.all(3),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        shape=ft.RoundedRectangleBorder(radius=3),
                    ),
                    on_click=lambda e: self.abrir_date_picker(self.txt_fecha_hasta),
                    tooltip="Seleccionar fecha hasta"
                ),
                self.search_button
            ]),
            ft.Divider(height=2),
            self.chk_list,
            ft.Divider(height=2),
            ft.Column(controls=[self.tabla], scroll=ft.ScrollMode.AUTO, expand=True, spacing=0)
        ]
        # self.update_tabla()
    
    def abrir_date_picker(self, campo_destino):
        """
        Abre el DatePicker y establece cuál campo recibirá la fecha seleccionada.
        
        Args:
            campo_destino: El TextField que recibirá la fecha seleccionada
        """
        self.campo_fecha_activo = campo_destino
        
        # Intentar establecer la fecha actual del campo como fecha inicial del picker
        try:
            if campo_destino.value:
                fecha_actual = datetime.datetime.strptime(campo_destino.value, '%d/%m/%Y').date()
                self.date_picker.value = fecha_actual
        except (ValueError, TypeError):
            # Si no se puede parsear, usar fecha actual
            self.date_picker.value = datetime.date.today()
        
        # Abrir el DatePicker
        self.date_picker.open = True
        self.page.update()
        
    def filtrar_datos(self):
        self.generar_tabla(self.data_resumen)

    def build_search_button(self):
        return CustomButtonCupertino(
                    text="Buscar",
                    icon=ft.Icons.SEARCH,
                    bgcolor=ft.Colors.PRIMARY,
                    color=ft.Colors.ON_PRIMARY,
                    on_click=self.handle_on_click_generar_reporte
                )
        
    def build_table(self):
        return ft.DataTable(
            columns=[
                ft.DataColumn(
                    ft.Text("Column 1"),
                    on_sort=lambda e: print(f"{e.column_index}, {e.ascending}"),
                ),
            ],
            rows=[
                ft.DataRow(
                    [ft.DataCell(ft.Text("A"))],
                    selected=True,
                    on_select_change=lambda e: print(f"row select changed: {e.data}"),
                ),
            ],
            vertical_lines=ft.BorderSide(1, ft.Colors.BLUE),
            horizontal_lines=ft.BorderSide(1, ft.Colors.BLUE),
            column_spacing=15,
            # show_checkbox_column=True,
            data_row_max_height=30,
            horizontal_margin=0,
            divider_thickness=0,
            data_row_color={ft.ControlState.HOVERED: ft.Colors.BLUE_GREY_100},
            
        )
        
    def formato_chileno(self, valor, cant_decimales=0):
        # Convertir y validar el valor
        try:
            valor_float = float(valor) if valor is not None else 0.0
        except (ValueError, TypeError):
            valor_float = 0.0
        
        # Crear el formato dinámicamente
        if cant_decimales == 0:
            return "{:,.0f}".format(valor_float).replace(",", "X").replace(".", ",").replace("X", ".")
        else:
            formato = "{:,." + str(cant_decimales) + "f}"
            return formato.format(valor_float).replace(",", "X").replace(".", ",").replace("X", ".")

    def buscar_hoja(self, text_busqueda):
        # estructura retorno [{"id": id, "name": name}, ...]
        ret = []
        for hoja in self.page.hojas:
            if text_busqueda.lower() in hoja.lower():
                ret.append({"id": hoja, "name": hoja})
        return ret
    
    # def obtener_resumen(self):
    #     resumen = OdooService.obtener_resumen_existencias()
    #     return resumen

    def handle_on_change(self, e=None, value=None):
        if value:
            self.id_hoja = value
            self.search_button.disabled = False
            self.search_button.update()
            return
        if e:
            self.id_hoja = e.control.data
            self.search_button.disabled = False
            self.search_button.update()
            return
        self.id_hoja = None
        self.search_button.disabled = True
        self.search_button.update()

    def obtener_columnas_movimientos(self):
        # funcion que arma las columnas de movimientos dinamicamente en funcion de los chk que esten seleccionados
        ret = []
        if self.chk_comprado.value:
            ret.append(ft.Text("C"))
        if self.chk_vendido.value:
            ret.append(ft.Text("V"))
        if self.chk_stock.value:
            ret.append(ft.Text("S"))
        if self.chk_ajuste_stock.value:
            ret.append(ft.Text("A"))
        return ret
    
    def toggle_row_selection(self, index_fila):
        """Cambia el estado de selección de una fila"""
        if self.selected_row_index == index_fila:
            # Si ya está seleccionada, deseleccionar
            self.selected_row_index = None
            self.btn_ver_grafica.disabled = True
        else:
            # Seleccionar la nueva fila
            self.selected_row_index = index_fila
            self.btn_ver_grafica.disabled = False
        
        # Actualizar botón
        self.btn_ver_grafica.update()
        
        # Regenerar la tabla con los nuevos colores
        self.generar_tabla(self.data_resumen)
    
    def get_row_color(self, index_fila):
        """Determina el color de una fila basado en si está seleccionada"""
        if self.selected_row_index == index_fila:
            return ft.Colors.LIGHT_BLUE_200  # Color cuando está seleccionada
        elif index_fila % 2 == 0:
            return ft.Colors.LIGHT_BLUE_50  # Color alternado par
        else:
            return ft.Colors.TRANSPARENT  # Color alternado impar
    
    def mostrar_grafica(self, e=None):
        """Muestra un modal con la gráfica de barras del producto seleccionado"""
        if self.selected_row_index is None:
            return
        
        # Obtener los datos de la fila seleccionada
        fila_seleccionada = self.data_resumen[self.selected_row_index]
        producto_nombre = fila_seleccionada['producto_nombre']
        movimientos = fila_seleccionada['movimientos']
        
        # Preparar datos para la gráfica
        grupos_barras = []
        etiquetas_meses = []
        
        for mov in movimientos:
            mes_label = f"{mov['anio']}-{mov['mes']:02d}"
            etiquetas_meses.append(mes_label)
            
            # Crear grupo de barras para este mes
            barras = []
            
            if self.chk_comprado.value:
                barras.append(fch.BarChartRod(
                    from_y=0,
                    to_y=mov['cantidad_comprada'],
                    width=15,
                    color=ft.Colors.GREEN_400,
                    tooltip=f"Compras: {self.formato_chileno(mov['cantidad_comprada'])}",
                    border_radius=2,
                ))
            
            if self.chk_vendido.value:
                barras.append(fch.BarChartRod(
                    from_y=0,
                    to_y=mov['cantidad_vendida'],
                    width=15,
                    color=ft.Colors.RED_400,
                    tooltip=f"Ventas: {self.formato_chileno(mov['cantidad_vendida'])}",
                    border_radius=2,
                ))
            
            if self.chk_stock.value:
                barras.append(fch.BarChartRod(
                    from_y=0,
                    to_y=mov['stock_cierre_mes'],
                    width=15,
                    color=ft.Colors.BLUE_400,
                    tooltip=f"Stock: {self.formato_chileno(mov['stock_cierre_mes'])}",
                    border_radius=2,
                ))
            
            if self.chk_ajuste_stock.value:
                barras.append(fch.BarChartRod(
                    from_y=0,
                    to_y=abs(mov['cantidad_ajustada']),
                    width=15,
                    color=ft.Colors.ORANGE_400 if mov['cantidad_ajustada'] >= 0 else ft.Colors.PURPLE_400,
                    tooltip=f"Ajustes: {self.formato_chileno(mov['cantidad_ajustada'])}",
                    border_radius=2,
                ))
            
            grupos_barras.append(fch.BarChartGroup(
                x=len(grupos_barras),
                rods=barras,
            ))
        
        # Crear la gráfica
        grafica = fch.BarChart(
            groups=grupos_barras,
            border=ft.Border.all(1, ft.Colors.GREY_400),
            left_axis=fch.ChartAxis(
                label_size=40,
                title=ft.Text("Cantidad"),
                title_size=40,
            ),
            bottom_axis=fch.ChartAxis(
                labels=[fch.ChartAxisLabel(
                    value=i,
                    label=ft.Container(
                        ft.Text(etiquetas_meses[i], size=10),
                        padding=5,
                    )
                ) for i in range(len(etiquetas_meses))],
                label_size=60,
            ),
            horizontal_grid_lines=fch.ChartGridLines(
                color=ft.Colors.GREY_300,
                width=1,
                dash_pattern=[3, 3],
            ),
            tooltip=fch.BarChartTooltip(bgcolor=ft.Colors.with_opacity(0.8, ft.Colors.GREY_800)),
            max_y=None,  # Auto ajustar
            interactive=True,
            expand=True,
        )
        
        # Crear leyenda
        leyenda_items = []
        if self.chk_comprado.value:
            leyenda_items.append(ft.Row([
                ft.Container(width=15, height=15, bgcolor=ft.Colors.GREEN_400),
                ft.Text("Compras", size=12)
            ], spacing=5))
        if self.chk_vendido.value:
            leyenda_items.append(ft.Row([
                ft.Container(width=15, height=15, bgcolor=ft.Colors.RED_400),
                ft.Text("Ventas", size=12)
            ], spacing=5))
        if self.chk_stock.value:
            leyenda_items.append(ft.Row([
                ft.Container(width=15, height=15, bgcolor=ft.Colors.BLUE_400),
                ft.Text("Stock", size=12)
            ], spacing=5))
        if self.chk_ajuste_stock.value:
            leyenda_items.append(ft.Row([
                ft.Container(width=15, height=15, bgcolor=ft.Colors.ORANGE_400),
                ft.Text("Ajustes", size=12)
            ], spacing=5))
        
        # Crear el modal
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Gráfica de Movimientos - {producto_nombre}"),
            content=ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=grafica,
                        height=400,
                        expand=True,
                    ),
                    ft.Divider(height=10),
                    ft.Row(
                        controls=leyenda_items,
                        alignment=ft.MainAxisAlignment.CENTER,
                        wrap=True,
                        spacing=20,
                    )
                ], spacing=10),
                width=800,
                height=500,
            ),
            actions=[
                ft.TextButton("Cerrar", on_click=lambda e: self.cerrar_dialog(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        
        abrir_dialogo(self.page, dialog)
        self.page.update()
    
    def cerrar_dialog(self, dialog):
        """Cierra el dialog y lo remueve del overlay"""
        cerrar_dialogo(self.page, dialog)
        self.page.update()
    
    @tarea_async
    async def handle_on_click_generar_reporte(self, e=None):
        try:
            # Esperar el reporte antes de armar la tabla.
            await self.obtener_resumen.ahora(self)
            self.generar_tabla(self.data_resumen)
        except Exception as e:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error al generar el reporte: {e}")))
    
    @tarea_async
    async def obtener_resumen(self, e=None):
        self.loading.show("Generando Reporte...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
        if not self.id_hoja:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("Debe seleccionar una hoja")))
            self.loading.hide()
            return
            
        # Validar fechas
        fecha_desde, fecha_hasta = self.obtener_fechas_validadas()
        if not fecha_desde or not fecha_hasta:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("Fechas inválidas. Verifique el formato.")))
            self.loading.hide()
            return
            
        if fecha_desde > fecha_hasta:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("La fecha desde no puede ser mayor a la fecha hasta.")))
            self.loading.hide()
            return



        self.data_resumen = await asyncio.to_thread(ReporteMovimientosProducto.obtener_reporte, 
            hoja=self.id_hoja['id'],
            page=self.page,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta
        )
    
    def generar_tabla(self, data):
        
        # Resto del código para generar la tabla...
        row = []
        columns = []
        columns.append(
            ft.DataColumn(
                label=ft.Column([ft.Text("Producto")],
                                   alignment=ft.MainAxisAlignment.CENTER)
            )
        )
        is_columns_updated = False
        for index_fila, fila in enumerate(data):
            cells = []
            # Nombre del producto con estrella si es favorito
            nombre_producto = str(fila.get('producto_nombre', ""))
            if fila.get("favorito"):
                content_producto = ft.Row([
                    ft.Icon(ft.Icons.STAR, color=ft.Colors.YELLOW_700, size=16),
                    ft.Text(nombre_producto, theme_style=ft.TextThemeStyle.LABEL_SMALL)
                ], spacing=5, alignment=ft.MainAxisAlignment.START)
            else:
                content_producto = ft.Text(nombre_producto, theme_style=ft.TextThemeStyle.LABEL_SMALL)

            cells.append(
                ft.DataCell(
                    ft.Container(
                        content=content_producto,
                        padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
                    )
                )
            )
            for index, movimiento in enumerate(fila["movimientos"]):
                if not is_columns_updated:
                    # verificamos si es el ultimo registro para agregar las columnas
                    col_label = f"{movimiento['anio']}-{movimiento['mes']:02d}"
                    columns.append(
                        ft.DataColumn(
                            label=ft.Column(
                                controls=[
                                    ft.Text(col_label),
                                    ft.Row(
                                        controls=self.obtener_columnas_movimientos(),
                                        expand=True,
                                        alignment=ft.MainAxisAlignment.SPACE_EVENLY
                                    )
                                ],
                                alignment=ft.MainAxisAlignment.CENTER,
                                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                                expand=True,
                                width=100
                            )
                        ),
                    )
                row_content = []
                if self.chk_comprado.value:
                    row_content.append(ft.Text(self.formato_chileno(movimiento["cantidad_comprada"]), theme_style=ft.TextThemeStyle.LABEL_SMALL))
                if self.chk_vendido.value:
                    row_content.append(ft.Text(self.formato_chileno(movimiento["cantidad_vendida"]), theme_style=ft.TextThemeStyle.LABEL_SMALL))
                if self.chk_stock.value:
                    row_content.append(ft.Text(self.formato_chileno(movimiento["stock_cierre_mes"]), theme_style=ft.TextThemeStyle.LABEL_SMALL))
                if self.chk_ajuste_stock.value:
                    row_content.append(ft.Text(self.formato_chileno(movimiento["cantidad_ajustada"]), theme_style=ft.TextThemeStyle.LABEL_SMALL))
                cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=row_content,
                                expand=True,
                                alignment=ft.MainAxisAlignment.SPACE_EVENLY
                            ),
                            padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
                            margin=ft.Margin.all(0),
                            alignment=ft.Alignment.CENTER
                        )
                    )
                )
                
            # alterna colores en base al index y resalta si está seleccionada
            row.append(ft.DataRow(
                cells=cells, 
                color=self.get_row_color(index_fila),
                on_select_change=lambda e, idx=index_fila: self.toggle_row_selection(idx)
                ))
            is_columns_updated = True
            
        
        self.tabla.rows = row
        self.tabla.columns = columns
        self.tabla.update()
        self.page.update()
        self.loading.hide()

    def obtener_fechas_validadas(self):
        """
        Obtiene y valida las fechas desde y hasta.
        
        Returns:
            tuple: (fecha_desde, fecha_hasta) como objetos date, o (None, None) si hay errores
        """
        try:
            fecha_desde_str = self.txt_fecha_desde.value
            fecha_hasta_str = self.txt_fecha_hasta.value
            
            if not fecha_desde_str or not fecha_hasta_str:
                return None, None
                
            fecha_desde = datetime.datetime.strptime(fecha_desde_str, '%d/%m/%Y').date()
            fecha_hasta = datetime.datetime.strptime(fecha_hasta_str, '%d/%m/%Y').date()
            
            return fecha_desde, fecha_hasta
            
        except (ValueError, TypeError) as e:
            print(f"Error validando fechas: {e}")
            return None, None
    
    def get_fecha_desde(self):
        """Obtiene la fecha desde como objeto date"""
        try:
            return datetime.datetime.strptime(self.txt_fecha_desde.value, '%d/%m/%Y').date()
        except (ValueError, TypeError):
            return None
    
    def get_fecha_hasta(self):
        """Obtiene la fecha hasta como objeto date"""
        try:
            return datetime.datetime.strptime(self.txt_fecha_hasta.value, '%d/%m/%Y').date()
        except (ValueError, TypeError):
            return None
