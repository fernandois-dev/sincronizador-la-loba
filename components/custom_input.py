import decimal
from enum import Enum
import inspect
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, campo_flet, cerrar_dialogo, en_pagina
from collections.abc import Callable
import locale
import threading
import time

from components.custom_buttons import CustomIconButton
from utilities.conditions import Conditions
for _lc in ('es_CL.UTF-8', 'es_CL.utf8', 'es_CL', 'Spanish_Chile'):
    try:
        locale.setlocale(locale.LC_ALL, _lc)
        break
    except locale.Error:
        continue
import datetime
from data.serach import buscar_modelo
import json
from dataclasses import dataclass, field
from typing import Any, List, Optional


class DisplayMode(Enum):
    EDIT = "edit"
    VIEW = "view"
    
class LayoutMode(Enum):
    VERTICAL = "vertical"
    HORIZONTAL = "horizontal"
    HORIZONTAL_WRAP = "horizontal_wrap"
    
STYLE_DEFAULT = {
    "height":50,
}

def format_currency(value):
    """Formatea un número como moneda (separado por puntos cada 3 dígitos)."""
    if value is None:
        return ""
    try:
        return f"{int(value):,}".replace(",", ".")
    except ValueError:
        return ""

def parse_currency(value):
    """Convierte un valor formateado como moneda a un número entero."""
    try:
        return int(value.replace(".", ""))
    except ValueError:
        return None


class CustomAutoField(PaginaFija, ft.TextField):
    def __init__(self, field, on_change, width=100, value=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.label = field.verbose_name
        self.on_change = on_change
        self.value = value
        self.width = width
        self.read_only = True
        self.disabled = True

        
class CustomIntegerField(PaginaFija, ft.TextField):
    def __init__(self, field, value=None, on_submit=None, on_change=None, width=350, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.value = value
        self._original_on_submit = on_submit
        self.on_change = on_change
        self.width = width
        self.shift_enter=True
        self.label = field.verbose_name
        self.text_align = ft.TextAlign.RIGHT
        # NO configurar on_submit aquí, se hará dinámicamente
        self.read_only = field.read_only
        
        # Centrar verticalmente el contenido del texto
        # self.content_padding = ft.Padding.symmetric(vertical=12, horizontal=12)
        self.content_padding = ft.Padding.only(top=0, right=0, bottom=16, left=0)
        self.text_vertical_align = ft.VerticalAlignment.CENTER
        
        # Configurar on_submit al final para permitir sobreescritura
        self._setup_submit_handler()

    def _setup_submit_handler(self):
        """Configura el manejador de submit inicial"""
        self.on_submit = self.handle_submit
    
    def set_on_submit(self, new_on_submit):
        """Permite cambiar el on_submit después de la inicialización"""
        # No modificar _original_on_submit aquí, solo cambiar el handler actual
        self.on_submit = new_on_submit
    
    def handle_submit(self, e):
        print(f"CustomIntegerField.handle_submit called for field {self.name}")
        print(f"_original_on_submit: {self._original_on_submit}")
        
        # Llamar al callback original si existe
        if self._original_on_submit:
            print(f"Calling original on_submit for {self.name}")
            self._original_on_submit(e)
        else:
            print(f"No original on_submit for {self.name}")
        
        # NO restablecer el foco aquí para permitir navegación
        # El sistema de navegación se encargará del foco
        # self.focused = True
        # self.value = "55"
        # self.update()

    @property
    def value(self):
        try:
            # Verificar si el valor existe y no está vacío
            if super().value and str(super().value).strip():
                return int(super().value)
            else:
                return None
        except (ValueError, TypeError):
            return None

    @value.setter
    def value(self, new_value):
        # Sobrescribir el setter para establecer el valor como cadena
        if  isinstance(new_value, int):
            campo_flet(ft.TextField, "value").__set__(self, str(new_value))
        else:
            campo_flet(ft.TextField, "value").__set__(self, new_value)
    
    def get_value(self):
        """Retorna el valor del campo como entero si es válido, sino como string"""
        try:
            if self.value is not None:
                return int(self.value)
            else:
                return super().value if super().value else None
        except (ValueError, TypeError):
            return super().value if super().value else None


class CustomMoneyField(PaginaFija, ft.TextField):
    def __init__(self, field, value=None,on_change=None, width=350, read_only=False, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.custom_on_change = on_change
        self.label = field.verbose_name
        self.value = value
        self.width = width
        
        self.text_align = ft.TextAlign.RIGHT  # Alinear texto a la derecha
        self.on_focus = self.handle_focus
        self.on_blur = self.handle_blur
        self.read_only = read_only
        self.content_padding = ft.Padding.only(top=0, right=0, bottom=16, left=0)
        # self.content_padding = ft.Padding.only(top=-4, right=10, bottom=0, left=10)
        # # self.text_vertical_align = ft.VerticalAlignment.START
        # self.bgcolor = "green"
         
        # self.height = STYLE_DEFAULT["height"]

        # Valor interno (numérico)
        self._numeric_value = None

        # Inicializar el valor si se pasa como argumento
        initial_value = kwargs.get("value", None)
        if initial_value is not None:
            self.value = initial_value  # Esto llamará al setter de `value`

    @property
    def value(self):
        """Valor visible (formateado como moneda)."""
        if self._numeric_value is None:
            return ""
        return format_currency(self._numeric_value)

    @value.setter
    def value(self, new_value):
        """Establece el valor interno (numérico) y actualiza el valor visible."""
        if new_value is None or new_value == "":
            self._numeric_value = None
        else:
            # Convertir el valor a un número entero
            if isinstance(new_value, str):
                self._numeric_value = self.parse_currency(new_value)
            elif isinstance(new_value, (int, float, decimal.Decimal)):
                self._numeric_value = int(new_value)
            else:
                raise ValueError("El valor debe ser un número o una cadena formateada como moneda.")
        # Actualizar el valor visible en el campo
        campo_flet(ft.TextField, "value").__set__(self, format_currency(self._numeric_value))

    @property
    def numeric_value(self):
        """Valor interno (numérico) para usar en el ORM o cálculos."""
        return self._numeric_value

    @numeric_value.setter
    def numeric_value(self, new_value):
        """Permite establecer directamente el valor numérico interno."""
        self._numeric_value = int(new_value) if new_value is not None else None
        # Actualizar el valor visible en el campo
        campo_flet(ft.TextField, "value").__set__(self, format_currency(self._numeric_value))

    def handle_focus(self, e):
        """Seleccionar todo el texto al hacer focus."""
        self.selection_start = 0
        self.selection_end = len(self.value) if self.value else 0
        self.update()

    def handle_blur(self, e):
        """Formatear el valor al perder el foco."""
        self.numeric_value = parse_currency(campo_flet(ft.TextField, "value").__get__(self, type(self)))
        if self._numeric_value is not None:
            self.value = self._numeric_value  # Esto llamará al setter de `value`
            self.update()
        
        # Disparar el evento on_change con el valor numérico
        if self.custom_on_change:
            self.custom_on_change(None, value=self.numeric_value)


class CustomDateTimeView(PaginaFija, ft.Container):
    def __init__(self, value=None, *args, **kwargs):
        """
        Visualiza una fecha y hora en el formato DD/MM/YYYY HH:MM:SS.
        
        Args:
            value (datetime.datetime): El valor de la fecha y hora a mostrar.
        """
        super().__init__(*args, **kwargs)
        self.value = value
        self.content = ft.Row(
            controls=[
                ft.Text(self.format_datetime(self.value))
            ],
            alignment=ft.MainAxisAlignment.END,
            spacing=0,
        )
        self.padding = ft.Padding.only(right=10)

    def format_datetime(self, value):
        """
        Formatea un objeto datetime en el formato DD/MM/YYYY HH:MM:SS.
        
        Args:
            value (datetime.datetime): El valor de la fecha y hora a formatear.
        
        Returns:
            str: La fecha y hora formateada como cadena.
        """
        if value is None:
            return ""
        return value.strftime("%d/%m/%Y %H:%M:%S")


class CustomMoneyView(PaginaFija, ft.Container):
    def __init__(self, value, size=None, color=None ,*args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value = value
        self.content = ft.Row(
            controls = [
                ft.Text(""),
                ft.Text(format_currency(self.value), size=size, color=color)
            ],
            alignment=ft.MainAxisAlignment.END,
            spacing=0,
        )
        # self.padding = ft.Padding.only(right=10)
        
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value):
        self._value = value
        if self.content:
            self.content.controls[1].value = format_currency(value) if value else ""
            self.content.update()
        
            
class CustomIntegerView(PaginaFija, ft.Container):
    def __init__(self, value, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value = value
        self.content = ft.Row(
            controls = [
                ft.Text(format_currency(self.value))
            ],
            alignment=ft.MainAxisAlignment.END,
            spacing=0,
        )
        # self.padding = ft.Padding.only(right=10)

       
class CustomBooleanView(PaginaFija, ft.Container):
    def __init__(self, value, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.value = value
        self.content = ft.Row(
            spacing=0,
            controls = [
                ft.Checkbox(
                    value=self.value,
                    disabled=True,
                            )
            ],
            alignment=ft.MainAxisAlignment.CENTER,
        )
        
        
class CustomTextField(PaginaFija, ft.TextField):
    def __init__(self, field, value=None, on_change=None, on_submit=None, width=350, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.on_change = on_change
        self._original_on_submit = on_submit
        self.width = width
        self.value = value
        self.label = field.verbose_name
        self.read_only = field.read_only
        # self.height = STYLE_DEFAULT["height"]
        
        # Configurar on_submit para permitir navegación
        self._setup_submit_handler()
    
    def _setup_submit_handler(self):
        """Configura el manejador de submit inicial"""
        if self._original_on_submit:
            self.on_submit = self._original_on_submit
    
    def set_on_submit(self, new_on_submit):
        """Permite cambiar el on_submit después de la inicialización"""
        # No modificar _original_on_submit aquí, solo cambiar el handler actual
        self.on_submit = new_on_submit

    
    def get_value(self):
        # default value str
        if self.input_type == "int" and f"{self.value}".isdigit():
            return int(self.value)
        else:
            return self.value

     
class CustomDateTimeField(PaginaFija, ft.Column):
    def __init__(self, field, value=None, on_change=None, helper_text="", read_only=False, helper_style=None, border_color=None,  *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.on_change = on_change
        self.value = value
        self.spacing = 2
        self.width = 350
        # self.height = STYLE_DEFAULT["height"]
        self._helper_text = helper_text
        self._helper_style = helper_style
        self._border_color = border_color
        self.fecha = None if not value else value.strftime("%d-%m-%Y")
        self.hora = None if not value else value.strftime("%H:%M")
        self.txt_fecha = ft.TextField(label=field.verbose_name, value=self.fecha, width=160, read_only=True)
        self.txt_hora = ft.TextField(label="Hora", value=self.hora, width=80, read_only=True)
        self.date_picker = ft.DatePicker(on_change=self.set_date, disabled=field.read_only)
        self.time_picker = ft.TimePicker(on_change=self.set_time, disabled=field.read_only)
        self.txt_error = ft.Container(content= ft.Text(self.helper_text, style=self.helper_style, size=11), 
                                      margin=ft.Margin.only(left=10), 
                                      visible=True if self.helper_text else False )
        self.controls = [
            ft.Row(controls=[
                self.txt_fecha,
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(icon=ft.Icons.CALENDAR_MONTH, size=28),
                    ], spacing=0),
                    width=40,height=40,
                    style=ft.ButtonStyle(padding=ft.Padding.all(5), bgcolor=ft.Colors.PRIMARY_CONTAINER, shape=ft.RoundedRectangleBorder(radius=3)),
                    on_click=self.open_date_picker
                ),
                self.txt_hora,
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(icon=ft.Icons.ACCESS_TIME, size=28),
                    ], spacing=0),
                    width=40,height=40,
                    style=ft.ButtonStyle(padding=ft.Padding.all(5), bgcolor=ft.Colors.PRIMARY_CONTAINER, shape=ft.RoundedRectangleBorder(radius=3)),
                    on_click=self.open_time_picker
                )
            ]), self.txt_error]
        
    @property
    def helper_text(self):
        return self._helper_text
    
    @helper_text.setter
    def helper_text(self, value):
        self._helper_text = value
        self.txt_error.visible = True if value else False
        self.txt_error.content.value = value
        self.txt_error.update()
        
    @property
    def helper_style(self):
        return self._helper_style
    
    @helper_style.setter
    def helper_style(self, value):
        self._helper_style = value
        self.txt_error.content.style = value
        self.txt_error.update()
        
    @property
    def border_color(self):
        return self._border_color
    
    @border_color.setter
    def border_color(self, value):
        self._border_color = value
        self.txt_fecha.border_color = value
        self.txt_fecha.update()
        self.txt_hora.border_color = value
        self.txt_hora.update()
        
    

    def get_value(self):
        return self.value

    def set_date(self, e):
        self.fecha = e.control.value.strftime("%d-%m-%Y")
        self.txt_fecha.value = self.fecha
        self.txt_fecha.update()
        self.update_value()
        # self.page.close_control(self.date_picker)

    def set_time(self, e):
        self.hora = e.control.value.strftime("%H:%M") if e.control.value else None
        self.txt_hora.value = self.hora
        self.txt_hora.update()
        self.update_value()
        # self.page.close_control(self.time_picker)
        
    

    def open_date_picker(self, e):
        abrir_dialogo(self.page, self.date_picker)

    def open_time_picker(self, e):
        abrir_dialogo(self.page, self.time_picker)

    def update_value(self):
        if self.fecha and self.hora:
            try:
                self.value = datetime.datetime.strptime(f"{self.fecha} {self.hora}", "%d-%m-%Y %H:%M")
            except ValueError:
                self.value = None
        else:
            self.value = None
        # Llamar al callback `on_change` si está definido
        if self.on_change:
            self.on_change(None, value=self.value)


class CustomCheckbox(PaginaFija, ft.Checkbox):
    
    def __init__(self, field, value=None, on_change=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.label = field.verbose_name
        self.on_change = on_change
        self.value = value
        self.disabled = field.read_only
    
    
class CustomDropdown(PaginaFija, ft.DropdownM2):
    def __init__(self, field, value=None, on_change=None, width=350, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.updade_value = on_change
        self.on_change = self.handle_change
        self.width = width
        self.label_style = ft.TextStyle(weight=ft.FontWeight.NORMAL)
        self.options=[ft.DropdownOption("", text=" ", data=None)] + [ ft.DropdownOption(str(opt.id), text=str(opt), data=opt) for opt in field.related_model.objects.all()]
        self.value = value.id if value else None
        self.label = field.verbose_name
        self.hover_color = "red"
        self.disabled = field.read_only
        # self.bgcolor = "blue"
        self.fill_color = ft.Colors.TRANSPARENT
        # self.focused_bgcolor = ft.Colors.BLUE
        # self.height = STYLE_DEFAULT["height"]
        
    def handle_change(self, e):
        
        selected_option = next(
            (opt for opt in self.options if opt.key == e.control.value), None
        )
        if selected_option:
            # Pasar el valor `data` del Option seleccionado al callback
            self.fill_color = ft.Colors.SECONDARY_CONTAINER
            self.updade_value(None, value=selected_option.data)
        else:
            self.fill_color = ft.Colors.TRANSPARENT
            self.updade_value(None, value=None)    
        self.update()


class SearchField(PaginaFija, ft.Container):
    def __init__(self , field, page=None,  border=None, on_change=None, on_submit = None, width=350, name="", label=None, value=None,data=None, helper_text="", 
                 helper_style=None, border_color=None, hint_text=None, hint_style=None, *args, **kwargs):
        super().__init__()
        self.on_change = on_change
        self.options = []  # Lista de opciones posibles
        self.on_submit_callback = on_submit  # Callback opcional para submit
        self.width = width
        self.name = field.name
        self.field = field
        self.label = label
        self.value = value
        self.data = data
        self.border = border
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
            read_only=field.read_only,
            content_padding=ft.Padding.only(top=0, right=4, bottom=16, left=4)

        )
        self.modal_text_field = ft.TextField(
            shift_enter=True,
            label="Filtrar sugerencias...",
            on_change=self.update_modal_suggestions,
            width=self.width,
            autofocus=True,
            read_only=field.read_only
        )
        self.btn_search = CustomIconButton(icon=ft.Icons.SEARCH, on_click=self.hundle_submit_btn)
        


        # Configurar el Container principal (el TextField)
        self.content = ft.Row(controls=[self.text_field, self.btn_search], spacing=10)
        # self.border = None  # Sin bordes decorativos en el Container
        self.border_radius = 0  # Sin esquinas redondeadas
        self.padding = 0
        
        # Modal para las sugerencias
        self.suggestions_modal = self.suggestions_modal = ft.AlertDialog(
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
    
    @property
    def value(self):
        return self._value
    
    @value.setter
    def value(self, value):
        self._value = value
        if hasattr(self, "text_field"):
            self.text_field.value = value
            self.text_field.bgcolor = ft.Colors.TRANSPARENT
            if en_pagina(self.text_field):
                self.text_field.update()

    @property
    def on_submit(self):
        """Permite acceder al callback de submit."""
        return self.on_submit_callback
    
    @on_submit.setter
    def on_submit(self, value):
        """Permite establecer el callback de submit."""
        self.on_submit_callback = value

    def focus(self):
        """Deriva el foco al campo de texto interno."""
        if hasattr(self, "text_field"):
            self.text_field.focus()
     
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
        self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER if value else ft.Colors.TRANSPARENT
        self.on_change(None, value=self.data)
        
    def handle_submit(self, e):
        if self.text_field.bgcolor == ft.Colors.ERROR_CONTAINER:
            self.text_field.bgcolor = ft.Colors.TRANSPARENT
            self.text_field.value = ""
            self.text_field.update()
            abrir_dialogo(self.page, self.suggestions_modal)
        
        # if not e.control.value or len(e.control.value) <= 3: return
        
        result = buscar_modelo(self.field.related_model.objects.all(), e.control.value)[:100]
        if result:
            if len(result) == 1:
                self.value = str(result[0])
                self.text_field.value = str(result[0])
                self.text_field.data = result[0]
                self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER
                self.data = result[0]
                self.text_field.update()
                # cerrar_dialogo(self.page, self.suggestions_modal)
                self.on_change(None, value=self.data)
            else:
                
                self.suggestions_modal.content.controls[1].controls = [  # Actualizar la segunda Column
                    ft.ListTile(
                        title=ft.Text(option),
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
        self.text_field.bgcolor = ft.Colors.ON_PRIMARY
        self.data = None
        self.text_field.update()
        self.on_change(None)

    def update_modal_suggestions(self, e):
        # if not e.control.value or len(e.control.value) <= 3: return
        if not e.control.value: return
        result = buscar_modelo(self.field.related_model.objects.all(), e.control.value)[:100]
        
        self.suggestions_modal.content.controls[1].controls = [  # Actualizar la segunda Column
                    ft.ListTile(
                        title=ft.Text(option),
                        on_click=lambda e, val=option: self.select_option(val),
                        data=option
                    ) for option in result
                ]
        self.page.update()

    def select_option(self, value):
        self.text_field.value = value
        self.text_field.data = value
        self.value = str(value)
        self.text_field.bgcolor = ft.Colors.SECONDARY_CONTAINER
        self.data = value
        self.text_field.update()
        cerrar_dialogo(self.page, self.suggestions_modal)
        self.text_field.focus()
        self.page.update()
        self.on_change(None, value=self.data)
    
    
class CustomDateField(PaginaFija, ft.Column):
    def __init__(self, field, value=None, on_change=None, helper_text="", read_only=False, helper_style=None, border_color=None,  *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = field.name
        self.on_change = on_change
        self.value = value
        self.spacing = 2
        self.width = 220
        # self.height = STYLE_DEFAULT["height"]
        self._helper_text = helper_text
        self._helper_style = helper_style
        self._border_color = border_color
        self.fecha = None if not value else value.strftime("%d-%m-%Y")
        self.txt_fecha = ft.TextField(label=field.verbose_name, value=self.fecha, width=160, read_only=True)
        self.date_picker = ft.DatePicker(on_change=self.set_date, disabled=field.read_only)
        self.txt_error = ft.Container(content= ft.Text(self.helper_text, style=self.helper_style, size=11), 
                                      margin=ft.Margin.only(left=10), 
                                      visible=True if self.helper_text else False )
        self.controls = [
            ft.Row(controls=[
                self.txt_fecha,
                ft.TextButton(
                    content=ft.Row([
                        ft.Icon(icon=ft.Icons.CALENDAR_MONTH, size=28),
                    ], spacing=0),
                    width=40,height=40,
                    style=ft.ButtonStyle(padding=ft.Padding.all(5), bgcolor=ft.Colors.PRIMARY_CONTAINER, shape=ft.RoundedRectangleBorder(radius=3)),
                    on_click=self.open_date_picker
                ),
            ]), self.txt_error]
        
    @property
    def helper_text(self):
        return self._helper_text
    
    @helper_text.setter
    def helper_text(self, value):
        self._helper_text = value
        self.txt_error.visible = True if value else False
        self.txt_error.content.value = value
        self.txt_error.update()
        
    @property
    def helper_style(self):
        return self._helper_style
    
    @helper_style.setter
    def helper_style(self, value):
        self._helper_style = value
        self.txt_error.content.style = value
        self.txt_error.update()
        
    @property
    def border_color(self):
        return self._border_color
    
    @border_color.setter
    def border_color(self, value):
        self._border_color = value
        self.txt_fecha.border_color = value
        self.txt_fecha.update()

    def get_value(self):
        return self.value

    def set_date(self, e):
        self.fecha = e.control.value.strftime("%d-%m-%Y")
        self.txt_fecha.value = self.fecha
        self.txt_fecha.update()
        self.update_value()

    def open_date_picker(self, e):
        abrir_dialogo(self.page, self.date_picker)

    def open_time_picker(self, e):
        abrir_dialogo(self.page, self.time_picker)

    def update_value(self):
        if self.fecha:
            try:
                self.value = datetime.datetime.strptime(self.fecha, "%d-%m-%Y")
            except ValueError:
                self.value = None
        else:
            self.value = None
        # Llamar al callback `on_change` si está definido
        if self.on_change:
            self.on_change(None, value=self.value)
            

def get_input_by_type(input_type: str, **kwargs):
    list_inputs = {
            "CustomAutoField": CustomAutoField,
            "CustomIntegerField": CustomIntegerField,
            "CustomDecimalField": CustomMoneyField,
            "CustomCharField": CustomTextField,
            "CustomEmailField": CustomTextField,
            "CustomDateTimeField": CustomDateTimeField,
            "CustomMoneyField": CustomMoneyField,
            "CustomBooleanField": CustomCheckbox,
            "CustomForeignKey": CustomDropdown,
            "CustomDateField": CustomDateField
            }
    
    filtered_kwargs = filter_kwargs(list_inputs[input_type], kwargs)
    
    if input_type in list_inputs:
        filtered_kwargs = filter_kwargs(list_inputs[input_type], kwargs)
        return list_inputs[input_type](**filtered_kwargs)
    else:
        filtered_kwargs = filter_kwargs(CustomTextField, kwargs)
        return CustomTextField(**filtered_kwargs)
    
def filter_kwargs(cls, kwargs):
    """Filtra los parámetros de kwargs para que solo incluyan los aceptados por la clase."""
    accepted_params = get_accepted_params(cls)
    return {key: value for key, value in kwargs.items() if key in accepted_params}

# TODO Agregar funcionalidad para visualizar los campos.
def get_view_by_type(input_type: str, **kwargs):
    list_inputs = {
            "CustomAutoField": CustomIntegerView,
            "CustomMoneyField": CustomMoneyView,
            "CustomDecimalField": CustomMoneyView,
            "CustomIntegerField": CustomIntegerView,
            "CustomBooleanField": CustomBooleanView,
            "CustomDateTimeField": CustomDateTimeView,
            }
    if input_type in list_inputs:
        filtered_kwargs = filter_kwargs(list_inputs[input_type], kwargs)
        return list_inputs[input_type](**filtered_kwargs)
    else:
        filtered_kwargs = filter_kwargs(ft.Text, kwargs)
        # En Flet 0.28 Text convertía value a texto; en 1.x se envía tal cual
        # y un objeto (por ejemplo una ForeignKey de Django) no se puede enviar.
        valor = filtered_kwargs.get("value")
        if valor is not None and not isinstance(valor, str):
            filtered_kwargs["value"] = str(valor)
        return ft.Text(**filtered_kwargs, selectable=True)

def get_accepted_params(cls):
    """Obtiene los parámetros aceptados por el constructor de una clase."""
    signature = inspect.signature(cls.__init__)
    return list(signature.parameters.keys())

class ManagerField(PaginaFija, ft.Container):
    def __init__(self,
                 display_mode: DisplayMode = DisplayMode.EDIT,
                 layout_mode: LayoutMode = LayoutMode.VERTICAL,
                 input_type: str = "CustomCharField",
                 conditions = Conditions(),
                 expand = 1,
                 *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.custom_edit = None
        self.layout_mode = layout_mode
        self.custom_view = None
        self.conditions = conditions
        self.display_mode = display_mode
        self.input_type = input_type
        self.value = None
        self.content = None
        self.expand = False # expand if layout_mode != LayoutMode.HORIZONTAL_WRAP else None
        self.padding = ft.Padding.only(left=4, right=4, top=0, bottom=0)
        # self.bgcolor = ft.Colors.ON_ERROR
        

    def build_field(self, **kwargs):
        self.value = kwargs.get("value", None)
        self.name = kwargs.get("name", "")
        obj = kwargs.get("obj", None)
        field = kwargs.get("field", "")
        
        # Extraer manejadores de foco
        on_focus_handler = kwargs.get("on_focus", None)
        on_blur_handler = kwargs.get("on_blur", None)
        
        # si en condiciones esta solo lectura pasarlo a kwargs
        if self.conditions and field.name in self.conditions.fields_readonly:
            kwargs["read_only"] = True

        self.override_input_type = self.conditions.overrides_input_type.get(self.name, None) if self.conditions else None
        self.override_view_type = self.conditions.overrides_view_type.get(self.name, None) if self.conditions else None
        
        column_width = getattr(field, "column_width", None)
        self.width = self.conditions.fields_column_width.get(field.name, column_width) if self.conditions else column_width
        self.height = 38
        self.alignment = ft.Alignment.CENTER_LEFT
        if self.conditions.fields_conditions_display.items():
            for field_name, condition in self.conditions.fields_conditions_display.items():
                if field_name == self.name:
                    # aplica la propiedad obtenida de la condicion si la condicion se cumple
                    if callable(condition):
                        if obj:
                            self.value = condition(obj)
                        else:
                            self.value = None
                        # recorro value
                        if isinstance(self.value, dict):
                            for key, val in self.value.items():
                                setattr(self, key, val)

                    break

        if self.display_mode == DisplayMode.EDIT:
            self.content = get_input_by_type(self.input_type, **kwargs) if not self.override_input_type else self.override_input_type(**kwargs)
            
            # Agregar manejadores de foco si están disponibles
            if self.content and on_focus_handler:
                if hasattr(self.content, 'on_focus'):
                    original_on_focus = getattr(self.content, 'on_focus', None)
                    def combined_on_focus(e):
                        if original_on_focus:
                            original_on_focus(e)
                        on_focus_handler()
                    self.content.on_focus = combined_on_focus
                    
            if self.content and on_blur_handler:
                if hasattr(self.content, 'on_blur'):
                    original_on_blur = getattr(self.content, 'on_blur', None)
                    def combined_on_blur(e):
                        if original_on_blur:
                            original_on_blur(e)
                        on_blur_handler()
                    self.content.on_blur = combined_on_blur
                    
        else: # DisplayMode.VIEW
            self.custom_view = get_view_by_type(self.input_type, **kwargs) if not self.override_view_type else  self.override_view_type(**filter_kwargs(self.override_view_type, kwargs))
            # if self.layout_mode == LayoutMode.HORIZONTAL and hasattr(self.custom_view, 'label'):
            #     self.custom_view.label = None
            self.content = self.custom_view
            
    # def set_edit_mode(self):
    #     """Cambia el modo de visualización a edición."""
    #     self.change_mode(DisplayMode.EDIT)
    
    def set_light_edit_mode(self):
        if hasattr(self.content, "border"):
            self.content.border = ft.InputBorder.NONE
            self.height = 38
            self.bgcolor = ft.Colors.ON_TERTIARY
        if hasattr(self.content, "label"):
            self.content.label = None
        self.content.expand = self.conditions.fields_expand.get(self.name, 1)

    def change_mode(self, mode):
        self.display_mode = mode
        if mode == DisplayMode.EDIT:
            self.content = self.custom_edit
        else:
            self.content = self.custom_view
        self.update()
        
    def get_field(self):
        return self.content
    
    def set_value(self, value):
        self.value = value
        self.content.value = value
        # if self.display_mode == DisplayMode.EDIT:
        #     self.custom_edit.value = value
        # else:
        #     self.custom_view.value = value
        # self.update()
        
    
        
