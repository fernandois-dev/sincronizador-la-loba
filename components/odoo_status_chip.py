import asyncio

import flet as ft

from utilities.flet_compat import PaginaFija, abrir_unico
from logger_config import get_logger
from modules.servidor.odoo import OdooService

logger = get_logger(__name__)


class OdooStatusChip(PaginaFija, ft.Container):
    """
    Indicador de estado de conexión con Odoo para el AppBar.
    Estados: conectando (gris/spinner), conectado (verde), desconectado
    (rojo, clic para reintentar). Toda llamada a OdooService corre en un
    hilo daemon para no bloquear la UI.
    """

    def __init__(self, page: ft.Page):
        super().__init__()
        self.page = page
        self.padding = ft.Padding.symmetric(horizontal=8)
        self.tooltip = "Comprobando conexión con Odoo..."
        self.on_click = self._on_click
        self._icon = ft.Icon(ft.Icons.SYNC, size=18, color=ft.Colors.GREY_400)
        self.content = self._icon

    def check_async(self):
        """Lanza la verificación de conexión en un hilo daemon."""
        self.page.run_task(self._check)

    async def _check(self):
        connected = await asyncio.to_thread(OdooService.ping)
        self._render(connected)

    def _render(self, connected: bool):
        if connected:
            self._icon.icon = ft.Icons.CLOUD_DONE
            self._icon.color = ft.Colors.GREEN_600
            self.tooltip = "Conectado a Odoo"
        else:
            self._icon.icon = ft.Icons.CLOUD_OFF
            self._icon.color = ft.Colors.RED_400
            self.tooltip = "Sin conexión con Odoo — clic para reintentar"
        if self.page:
            self.update()

    def _on_click(self, e):
        self._icon.icon = ft.Icons.SYNC
        self._icon.color = ft.Colors.GREY_400
        self.tooltip = "Reconectando..."
        self.update()
        self.page.run_task(self._reconnect)

    async def _reconnect(self):
        connected = await asyncio.to_thread(OdooService.reconnect)
        self._render(connected)
        if self.page:
            mensaje = "Conexión con Odoo restablecida." if connected else "No se pudo conectar con Odoo."
            abrir_unico(self.page, ft.SnackBar(ft.Text(mensaje)))
