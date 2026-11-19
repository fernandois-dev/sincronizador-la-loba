from typing import Callable
import flet as ft

from utilities.flet_compat import PaginaFija, abrir_unico, cerrar_dialogo
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import HojasSeleccionadas


class DlgSeleccionaHojaGoogle(PaginaFija, ft.AlertDialog):
    def __init__(self, page: ft.Page,title: str = "Selecciona las hojas para carga", fn_yes: Callable = None, fn_no: Callable = None, content = None, open=True) -> None:
        super().__init__()
        self.modal=True
        self.page = page
        self.title=ft.Text(title)
        self.hojas = self.page.hojas
        self.lista_hojas = self.build_lista_hojas()
        self.txt_busqueda = self.build_txt_busqueda()
        
        self.content = self.build_layout_dlg()
        self.actions_alignment=ft.MainAxisAlignment.END
        self.actions=[
            ft.TextButton("Cancelar", on_click= lambda e : self.handle_no()),
            ft.TextButton("Continuar", on_click= lambda e : self.handle_yes()),
        ]
        self.fn_yes = fn_yes
        self.fn_no = fn_no
        self.on_dismiss=lambda e: self.handle_no()
        self.actualizar_lista()
        if open:
            self.set_open()
            
    def buscar_hojas(self, e):
        self.actualizar_lista(e.control.value)

    def build_txt_busqueda(self):
        return ft.TextField(
            label="Buscar hoja",
            on_change=lambda e: self.buscar_hojas(e),
            on_submit=lambda e: self.handle_yes(),
            autofocus=True,
        )

    def build_layout_dlg(self):
        """
        Construye el layout del diálogo modal.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[self.txt_busqueda, self.lista_hojas]
                    ),
                    width=500,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.ALWAYS,
            height=400,
        )
        
    def build_lista_hojas(self):
        return ft.DataTable(
        columns=[
            ft.DataColumn(label=ft.Text("Nombre"))
        ],
        rows=[],
        show_checkbox_column=True,
    )

    
        
    def actualizar_lista(self, txt_busqueda: str = ""):
        def chk_selecciona_hoja(e):
            """
            Función para manejar la selección de una hoja en la lista.
            """
            e.control.selected = not e.control.selected
            e.control.update()
        
        self.lista_hojas.rows.clear()
        hojas = HojasSeleccionadas.objects.all()
        
        for hoja in self.hojas:
            if txt_busqueda.lower() in hoja.lower():
                self.lista_hojas.rows.append(
                    ft.DataRow(
                        cells=[
                            ft.DataCell(ft.Text(hoja)),
                        ],
                        data=hoja,
                    selected=hoja in hojas.values_list('hoja', flat=True),
                    on_select_change=lambda e, hoja=hoja: chk_selecciona_hoja(e)
                )
            )
        # Si la búsqueda deja una sola hoja, se marca sola: así basta Enter para cargarla.
        if txt_busqueda and len(self.lista_hojas.rows) == 1:
            self.lista_hojas.rows[0].selected = True
        self.page.update()
        
    def set_open(self):
        abrir_unico(self.page, self)
        
    def handle_no(self):
        if self.fn_no:
            self.fn_no()
        cerrar_dialogo(self.page, self)
        
    def handle_yes(self):
        """
        Función para agregar una nueva hoja a la tabla base.
        """
        hojas_seleccionadas_from_tabla = [hoja.data for hoja in self.lista_hojas.rows if hoja.selected]

        if len(hojas_seleccionadas_from_tabla) == 0:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Debe seleccionar al menos una hoja.")))
            return
        
        cerrar_dialogo(self.page, self)
        self.page.update()
        self.fn_yes(hojas_seleccionadas_from_tabla)
        