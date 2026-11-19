import flet as ft

from utilities.flet_compat import PaginaFija, abrir_dialogo, campo_flet, cerrar_dialogo, en_pagina
from components.custom_buttons import CustomIconButton

class GenericSearchField(PaginaFija, ft.Container):
    def __init__(self, name="",
                 page=None,  border=None, on_change=None, on_submit=None, handle_search=None,
                 width=350, label=None, value=None,data=None, helper_text="", 
                 helper_style=None, border_color=None, hint_text=None, hint_style=None, read_only=False, *args, **kwargs):
        super().__init__()
        self.on_change = on_change
        self.options = []  # Lista de opciones posibles
        self.on_submit_callback = on_submit  # Callback opcional para submit
        self.handle_search = handle_search  # Callback opcional para búsqueda
        self.width = width
        self.height = 35
        self.name = name
        self.label = label
        self.value = value
        self.data = data
        self.border = border
        self.read_only = read_only
        self._helper_text = helper_text
        self._helper_style = helper_style
        self._border_color = border_color
        self._hint_text = hint_text
        self._hint_style = hint_style
        self.page = page

        # Configurar el TextField
        self.text_field = ft.TextField(
            # label=hint_text,
            shift_enter=True,
            on_submit=lambda e: self.handle_submit(e),
            on_change=self.update_suggestions,
            expand=True,
            label=self.label,
            value=self.value,
            read_only=self.read_only,
            content_padding=ft.Padding.only(top=0, right=4, bottom=16, left=4),
            text_size=12,
        
        )
        self.modal_text_field = ft.TextField(
            shift_enter=True,
            label="Filtrar sugerencias...",
            on_change=self.update_modal_suggestions,
            width=self.width,
            autofocus=True,
            read_only=self.read_only
        )
        self.btn_search = CustomIconButton(icon=ft.Icons.SEARCH, on_click=self.hundle_submit_btn)
        


        # Configurar el Container principal (el TextField)
        self.content = ft.Row(controls=[self.text_field, self.btn_search], spacing=10)
        # self.border = None  # Sin bordes decorativos en el Container
        self.border_radius = 0  # Sin esquinas redondeadas
        self.padding = 0
        
        # Modal para las sugerencias
        self.suggestions_modal = ft.AlertDialog(
            content=ft.Column(
                controls=[
                    self.modal_text_field,
                    ft.Column(controls=[], spacing=0, scroll=ft.ScrollMode.AUTO, width=self.width),
                ],
                spacing=5,
            ),
            modal=False,  # No bloquea la UI
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            shape=ft.RoundedRectangleBorder(radius=5),
            elevation=10,
        )
        
        if self.value: self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER
        else: self.text_field.bgcolor = ft.Colors.GREEN_100
        
    
    @property
    def focus(self):
        """Devuelve si el campo de texto tiene el foco."""
        return self.text_field.focus

    @focus.setter
    def focus(self, value):
        """Establece el foco en el campo de texto."""
        if hasattr(self, "text_field"):
            self.text_field.focus = value
            self.text_field.update()
        
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value):
        self._value = value
        if hasattr(self, "text_field"):
            self.text_field.value = value
            self.text_field.bgcolor = ft.Colors.GREEN_100
            if en_pagina(self.text_field):
                self.text_field.update()
     
    @property
    def helper_text(self):
        return self._helper_text
    
    @helper_text.setter
    def helper_text(self, value):
        self._helper_text = value
        self.text_field.helper_text = value
        self.text_field.update()
        
    @property
    def hint_text(self):
        return self._hint_text
    
    @hint_text.setter
    def hint_text(self, value):
        self._hint_text = value
        self.text_field.hint_text = value
        self.text_field.update()
        
    @property
    def hint_style(self):
        return self._hint_style
    
    @hint_style.setter
    def hint_style(self, value):
        self._hint_style = value
        self.text_field.hint_style = value
        self.text_field.update()
        
    @property
    def helper_style(self):
        return self._helper_style
    
    @helper_style.setter
    def helper_style(self, value):
        self._helper_style = value
        self.text_field.helper_style = value
        self.text_field.update()
        
    @property
    def border_color(self):
        return self._border_color
    
    @border_color.setter
    def border_color(self, value):
        self._border_color = value
        self.text_field.border_color = value
        self.text_field.update()
        
            
    @property
    def border(self):
        return None

    @border.setter
    def border(self, value):
        if hasattr(self, "text_field"):
            self.text_field.border = value
        campo_flet(ft.Container, "border").__set__(self, None)
        
    # Propiedad label para compatibilidad con ManagerField
    @property
    def label(self):
        return self._label

    @label.setter
    def label(self, value):
        self._label = value
        if hasattr(self, "text_field"):
            self.text_field.label = value  # Actualizar el label del TextField
            if en_pagina(self.text_field):
                self.text_field.update()
        
    def hundle_submit_btn(self, e):
        abrir_dialogo(self.page, self.suggestions_modal)  # Abrir el modal con sugerencias
        self.modal_text_field.value = self.text_field.value
        self.modal_text_field.update()
        
    def set_initial_value(self, value, data=None):
        self.value = value
        self.data = data
        self.text_field.value = value
        self.text_field.data = data
        self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER if value else ft.Colors.GREEN_100
        self.on_change(None, value=self.data)
        
    def handle_submit(self, e):
        if self.text_field.bgcolor == ft.Colors.ERROR_CONTAINER:
            self.text_field.bgcolor = ft.Colors.GREEN_100
            self.text_field.value = ""
            self.text_field.update()
            abrir_dialogo(self.page, self.suggestions_modal)
        
        # if not e.control.value or len(e.control.value) <= 3: return
        
        # result = buscar_modelo(self.field.related_model.objects.all(), e.control.value)[:100]
        result = self.handle_search(e.control.value) if self.handle_search else []
        if result:
            if len(result) == 1:
                result = result[0] if isinstance(result[0], dict) else {"id": result[0], "name": result[0]}
                self.value = str(result["id"])
                self.text_field.value = str(result["name"])
                self.text_field.data = result
                self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER
                self.data = result
                self.text_field.update()
                # cerrar_dialogo(self.page, self.suggestions_modal)
                self.on_change(None, value=self.data)
            else:
                
                self.suggestions_modal.content.controls[1].controls = [  # Actualizar la segunda Column
                    ft.ListTile(
                        title=ft.Text(option["name"] if isinstance(option, dict) else option),
                        on_click=lambda e, val=option: self.select_option(val),
                        data=option
                    ) for option in result
                ]
                abrir_dialogo(self.page, self.suggestions_modal)  # Abrir el modal con sugerencias
                self.modal_text_field.value = e.control.value  # Sincronizar el TextField del modal
        else:
            self.text_field.focus()
            self.text_field.bgcolor = ft.Colors.ERROR_CONTAINER
            self.text_field.value = ""
            self.text_field.update()
        
        # cerrar_dialogo(self.page, self.suggestions_modal)  # Cerrar el modal
        # self.text_field.focus()
        # self.page.update()
        if self.on_submit_callback:
            self.on_submit_callback(self.text_field.value)
        

    def update_suggestions(self, e):
        self.text_field.bgcolor = ft.Colors.GREEN_100
        self.data = None
        self.text_field.update()
        self.on_change(None)

    def update_modal_suggestions(self, e):
        # if not e.control.value or len(e.control.value) <= 3: return
        if not e.control.value: return
        result = self.handle_search(e.control.value) if self.handle_search else []
        if result:
            self.suggestions_modal.content.controls[1].controls = [  # Actualizar la segunda Column
                ft.ListTile(
                    title=ft.Text(opt if isinstance(opt, str) else opt['name']),
                    on_click=lambda e, val=opt: self.select_option(val),
                    data=opt
                ) for opt in result
            ]
            self.page.update()

    def select_option(self, value):
        self.value = str(value["id"]) if isinstance(value, dict) else str(value)
        self.text_field.value = value["name"] if isinstance(value, dict) else str(value)
        self.text_field.data = value
        self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER
        self.data = value
        self.text_field.update()
        cerrar_dialogo(self.page, self.suggestions_modal)
        self.text_field.focus()
        self.page.update()
        self.on_change(None, value=self.data)