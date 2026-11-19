"""
Panel flotante del Asistente IA: entra deslizándose desde la derecha, sobre cualquier pantalla.

Vive en ``page.overlay`` (por encima del menú y del contenido), no en una ruta del menú: así
la conversación se conserva aunque se navegue entre pantallas. Se abre con el botón de la
barra superior y se oculta con la X del panel; ocultarlo no borra nada.

La página del asistente se crea recién la primera vez que se abre (para no cargar la IA
al iniciar la app).
"""
import flet as ft

ANCHO_NORMAL = 560
ANCHO_AMPLIO = 900
_OCULTO = ft.Offset(1.05, 0)    # fuera de la pantalla, a la derecha
_VISIBLE = ft.Offset(0, 0)


class PanelAsistente:
    def __init__(self, page: ft.Page):
        self.page = page
        self.abierto = False
        self.amplio = False
        self._asistente = None
        self.contenedor = ft.Container(
            right=0, top=0, bottom=0, width=ANCHO_NORMAL,
            offset=_OCULTO,
            animate_offset=ft.Animation(250, ft.AnimationCurve.EASE_OUT),
            animate_size=ft.Animation(200, ft.AnimationCurve.EASE_OUT),
            bgcolor=ft.Colors.GREY_100,
            shadow=ft.BoxShadow(blur_radius=24, spread_radius=2, color=ft.Colors.with_opacity(0.35, ft.Colors.BLACK)),
            border=ft.Border.only(left=ft.BorderSide(3, ft.Colors.AMBER_700)),
        )
        self.boton = ft.IconButton(
            icon=ft.Icons.FACE_2, icon_color=ft.Colors.AMBER_800, icon_size=28,
            tooltip="Asistente IA", on_click=lambda e: self.alternar(),
        )

    def _crear_asistente(self):
        from modules.servidor.pages.asistente_page import AsistentePage

        self._asistente = AsistentePage(self.page, al_ocultar=self.ocultar, al_ampliar=self.ampliar)
        self.contenedor.content = self._asistente

    def alternar(self):
        self.ocultar() if self.abierto else self.mostrar()

    def mostrar(self):
        if self._asistente is None:
            self._crear_asistente()
        self.abierto = True
        self.contenedor.offset = _VISIBLE
        self.page.update()

    def ocultar(self):
        self.abierto = False
        self.contenedor.offset = _OCULTO
        self.page.update()

    def ampliar(self):
        self.amplio = not self.amplio
        self.contenedor.width = ANCHO_AMPLIO if self.amplio else ANCHO_NORMAL
        self.page.update()


def instalar_panel_asistente(page: ft.Page) -> PanelAsistente:
    """Agrega el panel a la página y su botón a la barra superior. Llamar después de page.add(...)."""
    panel = PanelAsistente(page)
    page.overlay.append(panel.contenedor)
    if page.appbar is not None:
        page.appbar.actions.insert(0, panel.boton)
    page.panel_asistente = panel
    page.update()
    return panel
