import flet as ft


from utilities.flet_compat import PaginaFija, cerrar_dialogo
class DlgConfirmacionCargaConteo(PaginaFija, ft.AlertDialog):
    """
    Diálogo que muestra los productos con nuevo registro de stock detectados
    en la hoja de conteo de un proveedor, antes de aplicarlos a la tabla.
    """

    def __init__(self, page: ft.Page, hoja: str, filas: list, fn_aceptar: callable):
        super().__init__()
        self.modal = True
        self.title = ft.Text(f"Conteo detectado: {hoja}")
        self.page = page
        self.filas = filas
        self.fn_aceptar = fn_aceptar

        tabla = ft.DataTable(
            columns=[
                ft.DataColumn(ft.Text("Ref. Interna")),
                ft.DataColumn(ft.Text("Producto")),
                ft.DataColumn(ft.Text("Stock Odoo")),
                ft.DataColumn(ft.Text("Nuevo Conteo")),
            ],
            rows=[
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(obj.ref_interna or "")),
                    ft.DataCell(ft.Text(obj.producto or "")),
                    ft.DataCell(ft.Text(str(obj.odoo_stock))),
                    ft.DataCell(ft.Text(str(nuevo_valor))),
                ]) for obj, nuevo_valor in filas
            ],
        )

        self.content = ft.Container(
            content=ft.Column(
                controls=[
                    ft.Text(f"Se encontraron {len(filas)} productos con nuevo registro de stock."),
                    ft.Column(controls=[tabla], scroll=ft.ScrollMode.ALWAYS, expand=True),
                ],
                expand=True,
            ),
            width=600,
            height=400,
            expand=True,
        )
        self.actions = [
            ft.TextButton("Cancelar", on_click=lambda e: self.cerrar()),
            ft.TextButton("Aceptar", on_click=lambda e: self.aceptar()),
        ]
        self.actions_alignment = ft.MainAxisAlignment.END

    def cerrar(self):
        cerrar_dialogo(self.page, self)
        self.page.update()

    def aceptar(self):
        cerrar_dialogo(self.page, self)
        self.fn_aceptar(self.filas)
        self.page.update()
