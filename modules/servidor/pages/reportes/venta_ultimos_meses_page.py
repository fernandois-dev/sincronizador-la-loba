import asyncio

import flet as ft
from utilities.flet_compat import PaginaFija, abrir_unico
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager
from modules.servidor.odoo import OdooService
import datetime
from components.custom_buttons import boton_buscar
from components.generic_inputs import GenericSearchField

class VentaUltimosMesesPage(PaginaFija, ft.Column):
    titulo = "Ventas de los Últimos Meses"
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.id_hoja = None
        self._generando = False
        self.build_ui()
        self.notifications = []
        self.loading = Loading(self.page, open=False)
        self.row_height = 30
        self.column_proyeccion_color = ft.Colors.RED_100
        self.column_promedio_color = ft.Colors.BLUE_100


    def build_ui(self):
        self.tabla = self.build_table()
        self.search_button = self.build_search_button()
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
                self.search_button
            ]),
            ft.Divider(),
            ft.Column(controls=[self.tabla], scroll=ft.ScrollMode.AUTO, expand=True)
        ]
        # self.update_tabla()

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

    def obtener_resumen(self, e=None):
        if self._generando:
            return
        if not self.id_hoja:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Debe seleccionar una hoja")))
            return
        self._generando = True
        self.search_button.disabled = True
        self.search_button.update()
        self.loading.show("Generando Reporte...")
        self.page.run_task(self._generar_reporte_worker)

    async def _generar_reporte_worker(self):
        try:
            data = await asyncio.to_thread(
                OdooSyncManager.genera_reporte_ventas_ultimos_meses,
                hoja=self.id_hoja['id'],
                page=self.page,
                meses=3
            )
            rows, columns = self._construir_tabla(data)
            self.tabla.rows = rows
            self.tabla.columns = columns
            self.tabla.update()
            self.page.update()
        except Exception as ex:
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al generar el reporte: {ex}")))
        finally:
            self.loading.hide()
            self._generando = False
            self.search_button.disabled = self.id_hoja is None
            self.search_button.update()

    def _construir_tabla(self, data):
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
            for index, venta in enumerate(fila["ventas"][::-1]):
                if not is_columns_updated:
                    # verificamos si es el ultimo registro para agregar las columnas
                    col_label = f"{venta['anio']}-{venta['mes']:02d}"
                    if index == len(fila["ventas"]) -1:
                        col_label = f"Mes Actual"
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
                cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Text(self.formato_chileno(venta['cantidad_vendida']), theme_style=ft.TextThemeStyle.LABEL_SMALL),
                                    ft.Text(self.formato_chileno(venta['total_ventas']), theme_style=ft.TextThemeStyle.LABEL_SMALL)
                                ],
                                expand=True,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
                            margin=ft.Margin.all(0),
                            alignment=ft.Alignment.CENTER
                        )
                    )
                )
            cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Text(self.formato_chileno(fila['promedio_cantidad_vendida'], 1), theme_style=ft.TextThemeStyle.LABEL_SMALL),
                                    ft.Text(self.formato_chileno(fila['promedio_total_ventas']), theme_style=ft.TextThemeStyle.LABEL_SMALL)
                                ],
                                expand=True,
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
                            ),
                            height=self.row_height,
                            margin=ft.Margin.only(top=-15, bottom=0, left=-6, right=-6),
                            padding=ft.Padding.only(top=0, bottom=0, left=5, right=5),
                            alignment=ft.Alignment.CENTER,
                            bgcolor=self.column_promedio_color
                        )
                    )
                )
            cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Text(self.formato_chileno(fila['stock_actual']), theme_style=ft.TextThemeStyle.LABEL_SMALL)
                                ],
                                expand=True,
                                alignment=ft.MainAxisAlignment.END
                            ),
                            padding=ft.Padding.only(top=-10, bottom=0, left=5, right=5),
                            margin=ft.Margin.all(0),
                            alignment=ft.Alignment.CENTER,
                            width=50
                        )
                    )
                )
            cells.append(
                    ft.DataCell(
                        ft.Container(
                            content=ft.Row(
                                controls=[
                                    ft.Text(fila['proyeccion'], theme_style=ft.TextThemeStyle.LABEL_SMALL)
                                ],
                                expand=True,
                                alignment=ft.MainAxisAlignment.CENTER
                            ),
                            margin=ft.Margin.only(top=-15, bottom=0, left=-6, right=-6),
                            alignment=ft.Alignment.CENTER,
                            width=80,
                            bgcolor=self.column_proyeccion_color,
                            height=self.row_height
                        )
                    )
                )
            row.append(ft.DataRow(cells=cells))
            is_columns_updated = True
            
        columns.append(
            ft.DataColumn(
                label=ft.Column(
                    controls=[
                        ft.Text("Promedio"),
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
        columns.append(ft.DataColumn(label=ft.Text("Stock")))
        columns.append(ft.DataColumn(label=ft.Text("Proyección")))

        return row, columns
