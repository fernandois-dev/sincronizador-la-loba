from typing import Callable
import flet as ft


    
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo
class DlgConfirm(PaginaFija, ft.AlertDialog):
    def __init__(self, page: ft.Page,title: str = "", fn_yes: Callable = None, fn_no: Callable = None, content = None, open=True) -> None:
        super().__init__()
        self.modal=True
        self.page = page
        self.title=ft.Text(title)
        self.content = content
        self.actions_alignment=ft.MainAxisAlignment.END
        self.actions=[
            ft.TextButton("Cancelar", on_click= lambda e : self.handle_no()),
            ft.TextButton("Continuar", on_click= lambda e : self.handle_yes()),
        ]
        self.fn_yes = fn_yes
        self.fn_no = fn_no
        self.on_dismiss=lambda e: self.handle_no()
        if open:
            self.set_open()
        
    
    def set_open(self):
        abrir_dialogo(self.page, self)
        
    def handle_no(self):
        if self.fn_no:
            self.fn_no()
        cerrar_dialogo(self.page, self)
        
    def handle_yes(self):
        self.fn_yes()
        cerrar_dialogo(self.page, self)
        
class DlgAlert(PaginaFija, ft.AlertDialog):
    def __init__(self, page: ft.Page,title: str = "", content = None) -> None:
        super().__init__()
        self.page = page
        self.title=ft.Text(title)
        self.content = content
        abrir_dialogo(self.page, self)