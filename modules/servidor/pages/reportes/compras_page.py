import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, tarea_async
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager
from modules.servidor.odoo import OdooService
import datetime
from components.custom_buttons import boton_buscar
from components.generic_inputs import GenericSearchField

class ComprasPage(PaginaFija, ft.Column):
    titulo = "Reporte de Compras"
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
            ft.Divider(),
            ft.Column(controls=[self.tabla], scroll=ft.ScrollMode.AUTO, expand=True)
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

    def build_search_button(self):
        return boton_buscar(self.obtener_resumen)
        
    def build_table(self):
        return ft.DataTable(
            # columns=[
            #     ft.DataColumn(
            #         label=ft.Column(
            #             controls=[
            #                 ft.Text("Producto"),
            #                 ft.Row(
            #                     controls=[ft.Text("#"), ft.Text("|"),ft.Text("$")],
            #                     expand=True,
            #                     alignment=ft.MainAxisAlignment.SPACE_EVENLY
            #                 )
            #             ],
            #             alignment=ft.MainAxisAlignment.CENTER,
            #             horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            #             expand=True,
            #             width=120
            #         )
            #     ),
            #     ft.DataColumn(label=ft.Text("# Promedio Ventas")),
            #     ft.DataColumn(label=ft.Text("Stock Actual")),
            # ],
            columns=[ft.DataColumn(label=ft.Text("")),],
            # rows de ejemplo
            # rows=[
            #     ft.DataRow(cells=[
            #         ft.DataCell(
            #             ft.Text("Ejemplo Producto", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #         ft.DataCell(
            #             ft.Text("5", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #         ft.DataCell(
            #             ft.Text("$100.000", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #     ]),
            #     ft.DataRow(cells=[
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Text("Ejemplo Producto", theme_style=ft.TextThemeStyle.LABEL_SMALL),
            #                 padding=ft.Padding.only(top=0, bottom=0, left=5, right=5),
            #                 margin=ft.Margin.all(0),
            #                 alignment=ft.Alignment.CENTER_LEFT
            #             )
            #         ),
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Text("5555", theme_style=ft.TextThemeStyle.LABEL_SMALL),
            #                 # padding=ft.Padding.only(top=0, bottom=0, left=0, right=0),
            #                 margin=ft.Margin.only(top=-15, bottom=0, left=-6, right=-6),
            #                 alignment=ft.Alignment.CENTER,
            #                 bgcolor=ft.Colors.YELLOW_100,
            #                 height=30
            #             )
            #         ),
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Text("$100.000", theme_style=ft.TextThemeStyle.LABEL_SMALL),
            #                 padding=ft.Padding.only(top=0, bottom=0, left=5, right=5),
            #                 margin=ft.Margin.all(0),
            #                 alignment=ft.Alignment.CENTER
            #             )
            #         ),
            #     ]),
            #     ft.DataRow(cells=[
            #         ft.DataCell(
            #             ft.Text("Ejemplo Producto", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #         ft.DataCell(
            #             ft.Text("5", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #         ft.DataCell(
            #             ft.Text("$100.000", theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #         ),
            #     ]),
            # ],
            rows = [],
            vertical_lines=ft.BorderSide(1, ft.Colors.BLUE),
            horizontal_lines=ft.BorderSide(1, ft.Colors.BLUE),
            column_spacing=15,
            data_row_max_height=30,
            horizontal_margin=0,
            divider_thickness=0,
            
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

        data = await asyncio.to_thread(OdooSyncManager.obtiene_compras, 
            hoja=self.id_hoja['id'],
            page=self.page,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta
        )
        
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
        for fila in data:
            cells = []
            # Nombre del producto con estrella si es favorito
            nombre_producto = str(fila.get('producto_name', ""))
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
            for index, compra in enumerate(fila["compras"]):
                if not is_columns_updated:
                    # verificamos si es el ultimo registro para agregar las columnas
                    col_label = f"{compra['anio']}-{compra['mes']:02d}"
                    columns.append(
                        ft.DataColumn(
                            label=ft.Column(
                                controls=[
                                    ft.Text(col_label),
                                    ft.Row(
                                        controls=[ft.Text("#"), ft.Text("|"),ft.Text("$")],
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
                registros = []
                for reg in compra["registros"]:
                    registros.append(ft.Text(self.formato_chileno(reg["cantidad_comprada"]), theme_style=ft.TextThemeStyle.LABEL_SMALL))
                cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=registros,
                                expand=True,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
                            margin=ft.Margin.all(0),
                            alignment=ft.Alignment.CENTER
                        )
                    )
                )
            # cells.append(
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Row(
            #                     controls=[
            #                         ft.Text(self.formato_chileno(fila['promedio_cantidad_vendida'], 1), theme_style=ft.TextThemeStyle.LABEL_SMALL),
            #                         ft.Text(self.formato_chileno(fila['promedio_total_ventas']), theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #                     ],
            #                     expand=True,
            #                     alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            #                 ),
            #                 height=self.row_height,
            #                 margin=ft.Margin.only(top=-15, bottom=0, left=-6, right=-6),
            #                 padding=ft.Padding.only(top=0, bottom=0, left=5, right=5),
            #                 alignment=ft.Alignment.CENTER,
            #                 bgcolor=self.column_promedio_color
            #             )
            #         )
            #     )
            # cells.append(
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Row(
            #                     controls=[
            #                         ft.Text(self.formato_chileno(fila['stock_actual']), theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #                     ],
            #                     expand=True,
            #                     alignment=ft.MainAxisAlignment.END
            #                 ),
            #                 padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
            #                 margin=ft.Margin.all(0),
            #                 alignment=ft.Alignment.CENTER,
            #                 width=50
            #             )
            #         )
            #     )
            # cells.append(
            #         ft.DataCell(
            #             ft.Container(
            #                 content=ft.Row(
            #                     controls=[
            #                         ft.Text(fila['proyeccion'], theme_style=ft.TextThemeStyle.LABEL_SMALL)
            #                     ],
            #                     expand=True,
            #                     alignment=ft.MainAxisAlignment.CENTER
            #                 ),
            #                 margin=ft.Margin.only(top=-15, bottom=0, left=-6, right=-6),
            #                 alignment=ft.Alignment.CENTER,
            #                 width=80,
            #                 bgcolor=self.column_proyeccion_color,
            #                 height=self.row_height
            #             )
            #         )
            #     )
            row.append(ft.DataRow(cells=cells))
            is_columns_updated = True
            
        # columns.append(
        #     ft.DataColumn(
        #         label=ft.Column(
        #             controls=[
        #                 ft.Text("Promedio"),
        #                 ft.Row(
        #                     controls=[ft.Text("#"), ft.Text("|"),ft.Text("$")],
        #                     expand=True,
        #                     alignment=ft.MainAxisAlignment.SPACE_EVENLY
        #                 )
        #             ],
        #             alignment=ft.MainAxisAlignment.CENTER,
        #             horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        #             expand=True,
        #             width=100
        #         )
        #     ),
        # )  
        # columns.append(ft.DataColumn(label=ft.Text("Stock")))
        # columns.append(ft.DataColumn(label=ft.Text("Proyección")))
        
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
