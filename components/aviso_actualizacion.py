"""
Aviso de versión nueva (interfaz de utilities/actualizador.py).

- Al abrir la app se consulta GitHub en segundo plano; si hay versión nueva
  aparece un diálogo con las novedades y los botones "Más tarde" / "Actualizar".
- "Actualizar" descarga el paquete con barra de progreso, deja listo el script
  que reemplaza el programa y cierra la app; el script la vuelve a abrir.
- Clic en la versión de la barra superior: busca en ese momento.
"""
from __future__ import annotations

import asyncio
import logging

import flet as ft

from utilities import actualizador
from utilities.flet_compat import abrir_dialogo, abrir_unico, cerrar_dialogo
from utilities.servicios import abrir_url

logger = logging.getLogger("gestor_loba.actualizador")


def revisar_al_iniciar(page: ft.Page, version_actual: str) -> None:
    """Busca una versión nueva sin bloquear el arranque. Sin internet no avisa nada."""
    if not actualizador.disponible():
        return

    async def _revisar():
        await asyncio.sleep(3)  # que primero cargue la app
        try:
            act = await asyncio.to_thread(actualizador.buscar, version_actual)
        except Exception as exc:
            logger.info("No se pudo buscar actualizaciones: %s", exc)
            return
        if act:
            mostrar_aviso(page, act, version_actual)

    page.run_task(_revisar)


def buscar_ahora(page: ft.Page, version_actual: str) -> None:
    """Búsqueda manual (clic en la versión)."""
    async def _buscar():
        if not actualizador.disponible():
            abrir_unico(page, ft.SnackBar(ft.Text(
                "Las actualizaciones automáticas funcionan en el programa instalado "
                "(desde el código fuente usa git pull).")))
            return
        abrir_unico(page, ft.SnackBar(ft.Text("Buscando actualizaciones…")))
        try:
            act = await asyncio.to_thread(actualizador.buscar, version_actual)
        except Exception as exc:
            abrir_unico(page, ft.SnackBar(ft.Text(f"No se pudo consultar GitHub: {exc}"),
                                          bgcolor=ft.Colors.ERROR))
            return
        if act:
            mostrar_aviso(page, act, version_actual)
        else:
            abrir_unico(page, ft.SnackBar(ft.Text(f"Ya tienes la última versión ({version_actual}).")))

    page.run_task(_buscar)


def boton_version(page: ft.Page, version_actual: str) -> ft.Control:
    """Texto de versión de la barra superior; al hacer clic busca actualizaciones."""
    return ft.Container(
        padding=16,
        tooltip="Buscar actualizaciones",
        on_click=lambda e: buscar_ahora(page, version_actual),
        content=ft.Text(f"Version {version_actual}", theme_style=ft.TextThemeStyle.BODY_SMALL),
    )


def mostrar_aviso(page: ft.Page, act: actualizador.Actualizacion, version_actual: str) -> None:
    AvisoActualizacion(page, act, version_actual).abrir()


class AvisoActualizacion:
    def __init__(self, page: ft.Page, act: actualizador.Actualizacion, version_actual: str):
        self.page = page
        self.act = act
        self.version_actual = version_actual
        self.barra = ft.ProgressBar(value=0, width=420)
        self.estado = ft.Text("")
        self.boton_actualizar = ft.FilledButton(
            "Actualizar ahora", icon=ft.Icons.SYSTEM_UPDATE_ALT, on_click=self._actualizar)
        self.boton_despues = ft.TextButton("Más tarde", on_click=lambda e: self.cerrar())
        megas = f" · {self.act.tamano / 1_048_576:.0f} MB" if self.act.tamano else ""
        self.dialogo = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Hay una versión nueva: {act.version}"),
            content=ft.Column(
                [
                    ft.Text(f"Tienes la {version_actual}{megas}. La configuración y la base local "
                            "no se tocan; la app se cierra y se vuelve a abrir sola."),
                    ft.Container(
                        ft.Column([ft.Markdown(act.notas or "Sin notas.",
                                               selectable=True,
                                               on_tap_link=lambda e: abrir_url(page, e.data))],
                                  scroll=ft.ScrollMode.AUTO),
                        height=220, width=520,
                        bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST,
                        border_radius=8, padding=10,
                    ),
                    self.estado,
                ],
                tight=True, spacing=10,
            ),
            actions=[
                ft.TextButton("Ver en GitHub", on_click=lambda e: abrir_url(page, act.pagina)),
                self.boton_despues,
                self.boton_actualizar,
            ],
        )

    def abrir(self) -> None:
        abrir_dialogo(self.page, self.dialogo)

    def cerrar(self) -> None:
        cerrar_dialogo(self.page, self.dialogo)

    def _actualizar(self, e=None) -> None:
        self.page.run_task(self.actualizar)

    async def actualizar(self) -> None:
        self.boton_actualizar.disabled = True
        self.boton_despues.disabled = True
        self.estado.value = "Descargando…"
        contenido = self.dialogo.content.controls
        if self.barra not in contenido:
            contenido.append(self.barra)
        self.dialogo.update()

        avance = {"bajado": 0, "total": self.act.tamano}

        def progreso(bajado, total):  # corre en el hilo de descarga: solo guarda números
            avance["bajado"], avance["total"] = bajado, total or avance["total"]

        tarea = asyncio.create_task(asyncio.to_thread(actualizador.descargar, self.act, progreso))
        while not tarea.done():
            if avance["total"]:
                self.barra.value = min(avance["bajado"] / avance["total"], 1)
                self.estado.value = (f"Descargando… {avance['bajado'] / 1_048_576:.0f} de "
                                     f"{avance['total'] / 1_048_576:.0f} MB")
            self.dialogo.update()
            await asyncio.sleep(0.3)
        try:
            nueva = tarea.result()
            self.barra.value = None  # indeterminada
            self.estado.value = "Instalando… la app se cerrará y volverá a abrir."
            self.dialogo.update()
            await asyncio.to_thread(actualizador.aplicar, nueva)
        except Exception as exc:
            logger.exception("Falló la actualización")
            self.estado.value = f"No se pudo actualizar: {exc}"
            self.estado.color = ft.Colors.ERROR
            self.barra.value = 0
            self.boton_despues.disabled = False
            self.boton_despues.content = "Cerrar"
            self.dialogo.update()
            return
        await asyncio.sleep(1)
        await self.page.window.destroy()
