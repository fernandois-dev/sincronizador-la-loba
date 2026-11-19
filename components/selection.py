import flet as ft
from utilities.flet_compat import PaginaFija

class Selection(PaginaFija, ft.Container):
    """Componente de selección de filas en una tabla"""

    def __init__(self, fn_cancel_selection, fn_seleccion_todos, total_records, pagination_limit, **kwargs):
        super().__init__(**kwargs)
        self.fn_cancel_selection = fn_cancel_selection
        self.fn_seleccion_todos = fn_seleccion_todos
        self.total_records = total_records
        self.pagination_limit = pagination_limit
        
        # Inicializar la tabla y controles
        self.txt_seleccionados = ft.Text("0 seleccionados")
        self.txt_seleccionados_todos = ft.Text("0 seleccionados")  # Texto separado para todos
        self.contenedor_selecionados = self.build_contenedor_selecionados()
        self.contenedor_selecionados_todos = self.build_contenedor_selecionados_todos()
        
        self.content = ft.Column(controls=[
            self.contenedor_selecionados,
            self.contenedor_selecionados_todos
        ])
        
    def set_pagination_limit(self, limit: int):
        """Establece el límite de paginación"""
        self.pagination_limit = limit
        
    def set_total_records(self, total: int):
        """Establece el total de registros"""
        self.total_records = total
        self.txt_total_records.value = f"{self.total_records}"
        
    def manage_selection_display(self, selected_count: int):
        """Gestiona la visualización según el estado de selección"""
        self.contenedor_selecionados.bgcolor = ft.Colors.PRIMARY_CONTAINER
        if selected_count == 0:
            # Sin selección
            self.contenedor_selecionados.visible = False
            self.contenedor_selecionados_todos.visible = False
        elif selected_count < self.pagination_limit:
            # Selección parcial
            self.txt_seleccionados.value = f"{selected_count} seleccionados"
            self.contenedor_selecionados.visible = True
            self.contenedor_selecionados_todos.visible = False
        elif selected_count == self.total_records:
            # Selección de página completa
            self.txt_seleccionados.value = f"{selected_count} seleccionados"
            self.contenedor_selecionados.visible = True
            self.contenedor_selecionados.bgcolor = ft.Colors.GREEN_100
            self.contenedor_selecionados_todos.visible = False
        else:
            # Todos seleccionados
            self.txt_seleccionados_todos.value = f"{selected_count} selec"
            self.contenedor_selecionados.visible = False
            self.contenedor_selecionados_todos.visible = True
        
        # Actualizar la visualización
        try:
            # Actualizar tanto el texto individual como los contenedores
            self.txt_seleccionados.update()
            self.txt_seleccionados_todos.update()
            self.contenedor_selecionados.update()
            self.contenedor_selecionados_todos.update()
            
            if hasattr(self, 'page') and self.page is not None:
                self.update()
        except (AssertionError, AttributeError, RuntimeError):
            # El control aún no está agregado a la página
            pass
    
    def btn_seleccion_todos(self): 
        self.txt_seleccionados.value = f"{self.total_records} seleccionados"
        self.contenedor_selecionados.visible = True
        self.contenedor_selecionados.bgcolor = ft.Colors.GREEN_100
        self.contenedor_selecionados_todos.visible = False
        # Actualizar la visualización
        try:
            # Actualizar tanto el texto individual como los contenedores
            self.txt_seleccionados.update()
            self.contenedor_selecionados.update()
            self.contenedor_selecionados_todos.update()
            
        except (AssertionError, AttributeError, RuntimeError):
            # El control aún no está agregado a la página
            pass
        
        self.fn_seleccion_todos()
        
    def build_principal_ui(self):
        """Construye la UI principal de selección"""
        return ft.Column(controls=self.controls) 
    
    def build_contenedor_selecionados(self):
        
        return ft.Container(
                content=ft.Row(controls=[
                    self.txt_seleccionados,
                     ft.TextButton(
                        icon=ft.Icons.CANCEL,
                        width=30,
                        style=ft.ButtonStyle(padding=ft.Padding.all(5)),
                        on_click= lambda e: self.fn_cancel_selection()
                    ),
                    ],
                    expand=True,
                    alignment=ft.MainAxisAlignment.END
                                ),
                alignment=ft.Alignment.CENTER_RIGHT,
                width=180,
                height=40,
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                border_radius=ft.BorderRadius.all(3),
                border=ft.Border.all(1, ft.Colors.ON_SECONDARY_CONTAINER),
                
        )
        
    def build_contenedor_selecionados_todos(self):
        
        self.txt_total_records = ft.Text(f"{self.total_records}", color=ft.Colors.ON_PRIMARY, size=14)
        self.btn_seleccionados_todos = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.CHEVRON_RIGHT, color=ft.Colors.ON_PRIMARY, size=18),
                    self.txt_total_records
                ],
            ),
            height=35,
            width=60,
            bgcolor=ft.Colors.LIGHT_BLUE_800,
            border_radius=ft.BorderRadius.all(3),
            alignment=ft.Alignment.CENTER,
            on_click= lambda e: self.btn_seleccion_todos()
        )

        return ft.Container(
                content=ft.Row(controls=[
                    self.txt_seleccionados_todos,  # Usar el texto separado
                    self.btn_seleccionados_todos,
                     ft.TextButton(
                        icon=ft.Icons.CANCEL,
                        width=30,
                        style=ft.ButtonStyle(padding=ft.Padding.all(5)),
                        on_click= lambda e: self.fn_cancel_selection()
                    ),
                    ],
                    expand=True,
                    alignment=ft.MainAxisAlignment.END
                                ),
                alignment=ft.Alignment.CENTER_RIGHT,
                width=180,
                height=40,
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                border_radius=ft.BorderRadius.all(3),
                border=ft.Border.all(1, ft.Colors.ON_SECONDARY_CONTAINER)
        )