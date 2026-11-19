"""
Servicios de Flet 1.x: abrir enlaces, portapapeles y preferencias guardadas.

En 1.x son objetos async que no van en la página. Se crean una vez por página
con ``iniciar(page)`` (en main) y se guardan en la página, porque Flet
desregistra los servicios que quedan sin referencia.
"""
import flet as ft

from logger_config import get_logger
from utilities.flet_compat import abrir_unico

logger = get_logger(__name__)

_PREFIJO = "laloba."


def iniciar(page: ft.Page) -> None:
    """Crea los servicios de la página (llamar dentro de main)."""
    if getattr(page, "_servicios_laloba", None) is None:
        page._servicios_laloba = {
            "url": ft.UrlLauncher(),
            "portapapeles": ft.Clipboard(),
            "preferencias": ft.SharedPreferences(),
        }


def _servicio(page: ft.Page, nombre: str):
    iniciar(page)
    return page._servicios_laloba[nombre]


def abrir_url(page: ft.Page, url: str) -> None:
    """Abre el enlace en el navegador del equipo."""
    if not url:
        return

    async def _abrir():
        try:
            await _servicio(page, "url").launch_url(url)
        except Exception as e:
            logger.error("No se pudo abrir %s.", url, exc_info=True)
            abrir_unico(page, ft.SnackBar(ft.Text(f"No se pudo abrir el enlace: {e}"), bgcolor=ft.Colors.ERROR))

    page.run_task(_abrir)


def copiar(page: ft.Page, texto: str, aviso: str = "Copiado al portapapeles") -> None:
    """Copia el texto al portapapeles y muestra un aviso corto."""
    if not texto:
        return

    async def _copiar():
        try:
            await _servicio(page, "portapapeles").set(texto)
            abrir_unico(page, ft.SnackBar(ft.Text(aviso), duration=1500))
        except Exception as e:
            logger.error("No se pudo copiar al portapapeles.", exc_info=True)
            abrir_unico(page, ft.SnackBar(ft.Text(f"No se pudo copiar: {e}"), bgcolor=ft.Colors.ERROR))

    page.run_task(_copiar)


def guardar_preferencia(page: ft.Page, clave: str, valor) -> None:
    """Guarda una preferencia del equipo (tema, filtros...). No espera."""

    async def _guardar():
        try:
            await _servicio(page, "preferencias").set(_PREFIJO + clave, valor)
        except Exception:
            logger.warning("No se pudo guardar la preferencia %s.", clave, exc_info=True)

    page.run_task(_guardar)


async def leer_preferencia(page: ft.Page, clave: str, defecto=None):
    """Lee una preferencia guardada; devuelve ``defecto`` si no existe o falla."""
    try:
        valor = await _servicio(page, "preferencias").get(_PREFIJO + clave)
    except Exception:
        logger.warning("No se pudo leer la preferencia %s.", clave, exc_info=True)
        return defecto
    return defecto if valor is None else valor
