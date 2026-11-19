import flet as ft
from utilities.flet_compat import PaginaFija

from components.estilos import (
    BOTON_EXITO, BOTON_NEUTRO, BOTON_ODOO, BOTON_PELIGRO, BOTON_PRIMARIO, RADIO_BOTON,
)


class CustomButtonCupertino(PaginaFija, ft.Container):
    def __init__(self, text, icon,
                 on_click,
                 bgcolor=ft.Colors.ON_SECONDARY,
                 color=ft.Colors.ON_SURFACE,
                 height=34,
                 autofocus=False,
                 disabled=False,
                 **kwargs):

        # Remover disabled de kwargs para evitar conflictos con Container
        kwargs.pop('disabled', None)

        # El espacio entre ícono y texto lo da el Row; se quitan espacios sobrantes del texto
        text = text.strip() if isinstance(text, str) else text

        self._disabled = disabled
        self._on_click_original = on_click
        self._color_original = color
        self._bgcolor_original = bgcolor
        self.text = text
        self.icon = icon
        self._height = height

        # Crear los controles de contenido
        self._icon_control = ft.Icon(icon=icon, color=color, size=18) if icon else ft.Container()
        self._text_control = ft.Text(text, color=color, size=13, weight=ft.FontWeight.W_500) if text else ft.Container()

        # Botón de solo ícono: padding simétrico para que quede cuadrado
        margen_horizontal = 12 if text else 8

        # Crear el contenido del botón
        self._content = ft.Container(
            content=ft.Row(
                [self._icon_control, self._text_control],
                spacing=6,
                height=height,
                tight=True,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            on_hover=self.on_hover if not disabled else None,
            margin=ft.Margin.symmetric(horizontal=margen_horizontal, vertical=3),
        )

        super().__init__(
            content=self._content,
            bgcolor=bgcolor if not disabled else ft.Colors.with_opacity(0.3, bgcolor),
            on_click=self._handle_click,
            padding=ft.Padding.all(0),
            border_radius=ft.BorderRadius.all(RADIO_BOTON),
            height=height,
            alignment=ft.Alignment.CENTER if kwargs.get("width") else None,
            animate=ft.Animation(150, ft.AnimationCurve.EASE_OUT),
            **kwargs
        )
        
        # Aplicar estado disabled inicial
        if disabled:
            self._apply_disabled_style_initial()
        
        self.bgcolor_original = bgcolor
        self.autofocus = autofocus and not disabled

    @property
    def disabled(self):
        """Getter para la propiedad disabled"""
        return self._disabled
    
    @disabled.setter
    def disabled(self, value):
        """Setter para la propiedad disabled"""
        self._disabled = value
        if value:
            self._apply_disabled_style()
        else:
            self._apply_enabled_style()
        
        # Solo actualizar si el control ya está en la página
        try:
            if hasattr(self, 'page') and self.page is not None:
                self.update()
        except (AssertionError, AttributeError, RuntimeError):
            # El control aún no está agregado a la página, no actualizar
            pass
    
    def _apply_disabled_style_initial(self):
        """Aplica el estilo para estado disabled durante inicialización"""
        self._content.on_hover = None
        
        if self._icon_control and hasattr(self._icon_control, 'color'):
            self._icon_control.color = ft.Colors.with_opacity(0.4, self._color_original)
        if self._text_control and hasattr(self._text_control, 'color'):
            self._text_control.color = ft.Colors.with_opacity(0.4, self._color_original)
    
    def _apply_disabled_style(self):
        """Aplica el estilo para estado disabled"""
        self.bgcolor = ft.Colors.with_opacity(0.3, self._bgcolor_original)
        self._content.on_hover = None
        
        if self._icon_control and hasattr(self._icon_control, 'color'):
            self._icon_control.color = ft.Colors.with_opacity(0.4, self._color_original)
        if self._text_control and hasattr(self._text_control, 'color'):
            self._text_control.color = ft.Colors.with_opacity(0.4, self._color_original)
    
    def _apply_enabled_style(self):
        """Aplica el estilo para estado enabled"""
        self.bgcolor = self._bgcolor_original
        self._content.on_hover = self.on_hover
        
        if self._icon_control and hasattr(self._icon_control, 'color'):
            self._icon_control.color = self._color_original
        if self._text_control and hasattr(self._text_control, 'color'):
            self._text_control.color = self._color_original
    
    def _handle_click(self, e):
        """Maneja el evento click, respetando el estado disabled"""
        if not self._disabled and self._on_click_original:
            self._on_click_original(e)

    def on_hover(self, e: ft.HoverEvent):
        if not self._disabled:  # Solo hacer hover si no está disabled
            if str(e.data).lower() == "true":
                self.bgcolor = ft.Colors.with_opacity(0.7, self._bgcolor_original)
            else:
                self.bgcolor = self._bgcolor_original
            
            # Solo actualizar si el control ya está en la página
            try:
                if hasattr(self, 'page') and self.page is not None:
                    self.update()
            except (AssertionError, AttributeError, RuntimeError):
                # El control aún no está agregado a la página, no actualizar
                pass


# ─── Botones compartidos ───────────────────────────────────────────────────────
# Se repiten en muchas ventanas; usar estas funciones para que se vean iguales.
# `on_click` recibe el evento, igual que cualquier botón de Flet.

def _boton(variante, text, icon, on_click, tooltip=None, **kwargs):
    bgcolor, color = variante
    return CustomButtonCupertino(
        text=text, icon=icon, on_click=on_click,
        bgcolor=bgcolor, color=color, tooltip=tooltip, **kwargs
    )


def boton_cargar_tb(on_click, tooltip="Cargar Tabla Base (Google Sheets)", **kwargs):
    return _boton(BOTON_PRIMARIO, "TB", ft.Icons.ARROW_DOWNWARD, on_click, tooltip, **kwargs)


def boton_recargar_tb(on_click, tooltip="Recargar las hojas seleccionadas", **kwargs):
    return _boton(BOTON_PRIMARIO, "", ft.Icons.REFRESH, on_click, tooltip, **kwargs)


def boton_limpiar_tb(on_click, tooltip="Limpiar tablas", **kwargs):
    return _boton(BOTON_PELIGRO, "", ft.Icons.CLEAR, on_click, tooltip, **kwargs)


def boton_cargar_odoo(on_click, text="Odoo", tooltip="Cargar datos desde Odoo", **kwargs):
    return _boton(BOTON_ODOO, text, ft.Icons.ARROW_DOWNWARD, on_click, tooltip, **kwargs)


def boton_cargar_datos(on_click, text="Cargar Datos", tooltip=None, **kwargs):
    return _boton(BOTON_PRIMARIO, text, ft.Icons.REFRESH, on_click, tooltip, **kwargs)


def boton_buscar(on_click, tooltip=None, **kwargs):
    return _boton(BOTON_PRIMARIO, "Buscar", ft.Icons.SEARCH, on_click, tooltip, **kwargs)


def boton_exportar(on_click, text="Exportar", tooltip=None, **kwargs):
    return _boton(BOTON_EXITO, text, ft.Icons.FILE_DOWNLOAD, on_click, tooltip, **kwargs)


def boton_filtro(on_click, tooltip=None, **kwargs):
    return _boton(BOTON_NEUTRO, "", ft.Icons.FILTER_ALT, on_click, tooltip, **kwargs)


class CustomIconButton(PaginaFija, ft.TextButton):
    def __init__(self, on_click, icon=ft.Icons.random, bgcolor=ft.Colors.PRIMARY_CONTAINER, color=ft.Colors.ON_PRIMARY_CONTAINER, width=34, height=34, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.icon=icon
        self.bgcolor=bgcolor
        self.color=color
        self.width=width
        self.height=height
        self.content=ft.Row([ft.Icon(icon=self.icon, size=20, color=self.color)], alignment=ft.MainAxisAlignment.CENTER)
        self.style=ft.ButtonStyle(padding=ft.Padding.all(9), bgcolor=self.bgcolor,color=self.color, shape=ft.RoundedRectangleBorder(radius=3), alignment=ft.Alignment(0,0))
        self.on_click=on_click