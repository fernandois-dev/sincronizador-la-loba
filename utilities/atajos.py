"""Atajos de teclado de la app.

Hay un solo manejador para toda la app (``page.on_keyboard_event``). Cada
pantalla puede ofrecer los suyos con un método ``atajos()`` que devuelve un
diccionario ``{"ctrl+f": funcion, "f5": funcion, ...}``. Las funciones pueden
ser normales o ``async``.

F1 muestra la lista de atajos disponibles en la pantalla actual.
"""
import inspect

import flet as ft

from logger_config import get_logger
from utilities.flet_compat import abrir_unico, cerrar_dialogo

logger = get_logger(__name__)

# Descripción que se muestra con F1 (las teclas que no estén aquí se muestran tal cual).
DESCRIPCIONES = {
    "f1": "Ver esta ayuda",
    "f5": "Recargar los datos de la pantalla",
    "ctrl+f": "Ir al buscador",
    "pagedown": "Página siguiente",
    "pageup": "Página anterior",
    "f8": "Volver al inicio",
}


def combinacion(e) -> str:
    """'Ctrl' + 'F' → 'ctrl+f'; 'Page Down' → 'pagedown'."""
    partes = [m for m, activo in (("ctrl", e.ctrl), ("alt", e.alt), ("shift", e.shift)) if activo]
    partes.append(str(e.key or "").replace(" ", "").lower())
    return "+".join(partes)


def pantalla_actual(page):
    """La pantalla que muestra el router (o None)."""
    try:
        return page.controls[0].control_page.content
    except (AttributeError, IndexError):
        return None


def atajos_de(pantalla) -> dict:
    fn = getattr(pantalla, "atajos", None)
    try:
        return dict(fn()) if callable(fn) else {}
    except Exception:
        logger.exception("Error al leer los atajos de %s", type(pantalla).__name__)
        return {}


NOMBRES = {"pagedown": "Av Pág", "pageup": "Re Pág", "escape": "Esc"}


def nombre_tecla(clave: str) -> str:
    return "+".join(NOMBRES.get(p, p.capitalize()) for p in clave.split("+"))


def mostrar_ayuda(page, atajos: dict):
    filas = [("F1", DESCRIPCIONES["f1"])] + [(nombre_tecla(t), DESCRIPCIONES.get(t, "")) for t in atajos]
    dlg = ft.AlertDialog(
        title=ft.Row([ft.Icon(ft.Icons.KEYBOARD), ft.Text("Atajos de teclado")], spacing=8),
        content=ft.Column(
            controls=[
                ft.Row([
                    ft.Container(
                        content=ft.Text(t, size=12, weight=ft.FontWeight.BOLD),
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=ft.BorderRadius.all(6),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                        width=110,
                    ),
                    ft.Text(d, size=13),
                ])
                for t, d in filas
            ],
            tight=True,
            spacing=6,
        ),
        actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(page, dlg))],
    )
    abrir_unico(page, dlg)


def instalar(page):
    async def al_presionar(e):
        clave = combinacion(e)
        pantalla = pantalla_actual(page)
        atajos = atajos_de(pantalla)
        if clave == "f1":
            mostrar_ayuda(page, atajos)
            return
        accion = atajos.get(clave)
        if accion is None:
            return
        try:
            resultado = accion()
            if inspect.isawaitable(resultado):
                await resultado
        except Exception:
            logger.exception("Error en el atajo %s", clave)

    page.on_keyboard_event = al_presionar
