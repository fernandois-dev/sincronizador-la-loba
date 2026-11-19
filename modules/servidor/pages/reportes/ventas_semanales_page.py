import asyncio
import datetime
import flet as ft
import flet_charts as fch
from utilities.flet_compat import PaginaFija, abrir_dialogo, tarea_async
from components.loading import Loading
from components.custom_buttons import boton_buscar
from components.generic_inputs import GenericSearchField
from modules.servidor.business_logic import OdooSyncManager


class VentasSemanalesPage(PaginaFija, ft.Column):
    titulo = "Ventas por Semana"
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.id_hoja = None
        self.data_resumen = {}
        self.loading = Loading(self.page, open=False)
        self.scroll = ft.ScrollMode.AUTO
        self.expand = True
        self.build_ui()

    def build_ui(self):
        hoy = datetime.date.today()
        self.txt_semana = ft.TextField(
            value=hoy.strftime('%d/%m/%Y'),
            width=120,
            height=35,
            text_size=12,
            label="Semana",
            read_only=True,
        )

        self.campo_fecha_activo = None
        self.date_picker = ft.DatePicker(
            first_date=datetime.datetime(year=2000, month=1, day=1),
            last_date=datetime.datetime(year=hoy.year + 1, month=12, day=31),
            on_change=self.handle_change,
            on_dismiss=self.handle_dismissal,
        )
        self.page.overlay.append(self.date_picker)

        self.search_button = boton_buscar(self.handle_buscar)

        self.chart_container = ft.Container(
            content=ft.Text("Seleccione la semana para ver ventas por día."),
            height=380,
            alignment=ft.Alignment.CENTER,
            border=ft.Border.all(1, ft.Colors.OUTLINE_VARIANT),
            border_radius=8,
            padding=10,
        )

        self.tabla = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Día")),
                ft.DataColumn(ft.Text("Fecha")),
                ft.DataColumn(ft.Text("Cantidad Ventas")),
                ft.DataColumn(ft.Text("Total Ventas")),
            ],
            rows=[],
            heading_row_color=ft.Colors.BLUE_GREY_100,
            heading_text_style=ft.TextStyle(weight=ft.FontWeight.W_600),
            vertical_lines=ft.BorderSide(1, ft.Colors.BLUE_GREY_100),
            horizontal_lines=ft.BorderSide(1, ft.Colors.BLUE_GREY_100),
            column_spacing=18,
            horizontal_margin=0,
            divider_thickness=0,
        )

        self.table_container = ft.Container(
            content=ft.Column([self.tabla], scroll=ft.ScrollMode.AUTO, expand=True),
            border=ft.Border.all(1, ft.Colors.BLUE_GREY_100),
            border_radius=10,
            padding=8,
            bgcolor=ft.Colors.SURFACE,
            expand=True,
        )

        self.controls = [
            ft.Row([
                GenericSearchField(
                    name="proveedor",
                    page=self.page,
                    label="Proveedor",
                    width=300,
                    on_change=self.handle_on_change,
                    handle_search=lambda val: self.buscar_hoja(val),
                ),
                self.txt_semana,
                ft.TextButton(
                    content=ft.Row([ft.Icon(icon=ft.Icons.DATE_RANGE, size=20)]),
                    width=32,
                    height=32,
                    style=ft.ButtonStyle(
                        padding=ft.Padding.all(3),
                        bgcolor=ft.Colors.PRIMARY_CONTAINER,
                        shape=ft.RoundedRectangleBorder(radius=3),
                    ),
                    on_click=lambda e: self.abrir_date_picker(self.txt_semana),
                    tooltip="Seleccionar una fecha dentro de la semana",
                ),
                self.search_button,
            ]),
            ft.Divider(),
            self.chart_container,
            ft.Divider(height=8),
            self.table_container,
        ]

    def buscar_hoja(self, text_busqueda):
        ret = []
        for hoja in self.page.hojas:
            if text_busqueda.lower() in hoja.lower():
                ret.append({"id": hoja, "name": hoja})
        return ret

    def handle_on_change(self, e=None, value=None):
        if value:
            self.id_hoja = value
            return
        if e:
            self.id_hoja = e.control.data
            return
        self.id_hoja = None

    def abrir_date_picker(self, campo_destino):
        self.campo_fecha_activo = campo_destino
        try:
            if campo_destino.value:
                fecha_actual = datetime.datetime.strptime(campo_destino.value, '%d/%m/%Y').date()
                self.date_picker.value = fecha_actual
        except (ValueError, TypeError):
            self.date_picker.value = datetime.date.today()
        self.date_picker.open = True
        self.page.update()

    def handle_change(self, e):
        if self.campo_fecha_activo:
            fecha_seleccionada = e.control.value.strftime('%d/%m/%Y')
            self.campo_fecha_activo.value = fecha_seleccionada
            self.campo_fecha_activo.update()

    def handle_dismissal(self, e):
        self.campo_fecha_activo = None

    def formato_chileno(self, valor, cant_decimales=0):
        try:
            valor_float = float(valor) if valor is not None else 0.0
        except (ValueError, TypeError):
            valor_float = 0.0

        if cant_decimales == 0:
            return "{:,.0f}".format(valor_float).replace(",", "X").replace(".", ",").replace("X", ".")

        formato = "{:,." + str(cant_decimales) + "f}"
        return formato.format(valor_float).replace(",", "X").replace(".", ",").replace("X", ".")

    def obtener_fechas_validadas(self):
        try:
            fecha_semana = datetime.datetime.strptime(self.txt_semana.value, '%d/%m/%Y').date()
            return fecha_semana
        except (ValueError, TypeError):
            return None

    @tarea_async
    async def handle_buscar(self, e=None):
        fecha_semana = self.obtener_fechas_validadas()
        if not fecha_semana:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("Debe seleccionar una semana válida."), bgcolor=ft.Colors.ERROR))
            return

        self.loading.show("Generando reporte semanal...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
        try:
            hoja = self.id_hoja['id'] if isinstance(self.id_hoja, dict) else None
            self.data_resumen = await asyncio.to_thread(OdooSyncManager.genera_reporte_ventas_dias_semana, 
                page=self.page,
                fecha_referencia=fecha_semana,
                hoja=hoja,
            )
            self.actualizar_grafica()
            self.actualizar_tabla()
        except Exception as ex:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error generando reporte: {str(ex)}"), bgcolor=ft.Colors.ERROR))
        finally:
            self.loading.hide()
            self.page.update()

    def actualizar_grafica(self):
        dias = self.data_resumen.get("dias", []) if isinstance(self.data_resumen, dict) else []
        if not dias:
            self.chart_container.content = ft.Text("No hay ventas en la semana seleccionada.")
            self.chart_container.update()
            return

        bar_groups = []
        labels = []
        for index, item in enumerate(dias):
            labels.append(fch.ChartAxisLabel(
                value=index,
                label=ft.Container(
                    ft.Text(item['dia'][:3], size=10),
                    padding=4,
                )
            ))
            bar_groups.append(
                fch.BarChartGroup(
                    x=index,
                    rods=[
                        fch.BarChartRod(
                            from_y=0,
                            to_y=float(item['total_ventas']),
                            width=30,
                            color=ft.Colors.BLUE_500,
                            tooltip=f"{item['dia']}: ${self.formato_chileno(item['total_ventas'])}",
                            border_radius=3,
                        )
                    ],
                )
            )

        grafica = fch.BarChart(
            groups=bar_groups,
            border=ft.Border.all(1, ft.Colors.GREY_400),
            left_axis=fch.ChartAxis(
                label_size=42,
                title=ft.Text("Ventas ($)"),
                title_size=34,
            ),
            bottom_axis=fch.ChartAxis(labels=labels, label_size=48),
            horizontal_grid_lines=fch.ChartGridLines(
                color=ft.Colors.GREY_300,
                width=1,
                dash_pattern=[3, 3],
            ),
            tooltip=fch.BarChartTooltip(bgcolor=ft.Colors.with_opacity(0.85, ft.Colors.GREY_800)),
            interactive=True,
            expand=True,
        )

        semana_txt = f"Semana {self.data_resumen.get('semana', '--')} ({self.data_resumen.get('fecha_inicio').strftime('%d/%m')} - {self.data_resumen.get('fecha_fin').strftime('%d/%m')})"

        self.chart_container.content = ft.Column([
            ft.Text(semana_txt, weight=ft.FontWeight.W_600),
            ft.Container(content=grafica, expand=True),
        ], expand=True)
        self.chart_container.update()

    def actualizar_tabla(self):
        rows = []
        dias = self.data_resumen.get("dias", []) if isinstance(self.data_resumen, dict) else []
        for index, item in enumerate(dias):
            row_bgcolor = ft.Colors.BLUE_GREY_50 if index % 2 == 0 else ft.Colors.SURFACE_CONTAINER_LOWEST
            rows.append(
                ft.DataRow(cells=[
                    ft.DataCell(ft.Container(content=ft.Text(item['dia']), bgcolor=row_bgcolor, padding=8, border_radius=4)),
                    ft.DataCell(ft.Container(content=ft.Text(item['fecha'].strftime('%d/%m/%Y')), bgcolor=row_bgcolor, padding=8, border_radius=4)),
                    ft.DataCell(ft.Container(content=ft.Text(self.formato_chileno(item['cantidad_vendida'])), bgcolor=row_bgcolor, padding=8, border_radius=4)),
                    ft.DataCell(ft.Container(content=ft.Text(f"$ {self.formato_chileno(item['total_ventas'])}"), bgcolor=row_bgcolor, padding=8, border_radius=4)),
                ])
            )

        self.tabla.rows = rows
        self.tabla.update()
