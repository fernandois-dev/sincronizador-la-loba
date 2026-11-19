import flet as ft

from utilities.flet_compat import PaginaFija, abrir_unico, cerrar_dialogo
class Loading(PaginaFija, ft.AlertDialog):
    def __init__(self, page: ft.Page, message="Cargando...", open=True) -> None:
        super().__init__()
        self.page = page
        self.modal = True
        self.title = "Procesando"
        self.txt_message = ft.Text(message, text_align=ft.TextAlign.CENTER)
        self.content = ft.Column(
            controls=[
                ft.ProgressRing(),
                self.txt_message
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            height=100,
            width=200
        )
        if open:
            self.show()

    def show(self, message=None):
        if message:
            self.txt_message.value = message
        abrir_unico(self.page, self)
        self.page.update()
        
    def hide(self):
        cerrar_dialogo(self.page, self)
        self.page.update()