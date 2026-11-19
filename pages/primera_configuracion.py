"""
Pantalla de primera configuración.

Aparece cuando el programa recién instalado no encuentra sus archivos de
configuración (credentials.json, server_settings.cfg). Permite elegirlos desde
donde estén (descargas, pendrive, Drive) y los copia a la carpeta de datos
(utilities/carpeta_datos.py). Cuando están todos, abre la app en la misma ventana.
"""
from __future__ import annotations

import flet as ft

from utilities import carpeta_datos
from utilities.servicios import copiar


def mostrar_primera_configuracion(page: ft.Page, al_terminar) -> None:
    page.title = "Gestor La Loba — Configuración inicial"
    PantallaPrimeraConfiguracion(page, al_terminar).montar()


class PantallaPrimeraConfiguracion:
    def __init__(self, page: ft.Page, al_terminar):
        self.page = page
        self.al_terminar = al_terminar
        self.lista = ft.Column(spacing=4)
        self.mensaje = ft.Text("", selectable=True)
        self.boton_continuar = ft.FilledButton(
            "Abrir el Gestor", icon=ft.Icons.ARROW_FORWARD, on_click=self._continuar)

    # ── armado ────────────────────────────────────────────────────────────────
    def montar(self) -> None:
        carpeta = str(carpeta_datos.carpeta())
        contenido = ft.Column(
            [
                ft.Text("Configuración inicial", theme_style=ft.TextThemeStyle.HEADLINE_SMALL),
                ft.Text(
                    "Antes de usar el Gestor hay que copiar los archivos de configuración "
                    "(los mismos que antes se dejaban junto al .exe). Pídelos al "
                    "administrador y elígelos aquí: se guardan en tu carpeta de datos y "
                    "no se pierden al actualizar el programa."),
                ft.Container(height=8),
                self.lista,
                ft.Container(height=8),
                ft.Row(
                    [
                        ft.FilledButton("Elegir archivos…", icon=ft.Icons.UPLOAD_FILE,
                                        on_click=self._elegir),
                        ft.OutlinedButton("Abrir carpeta de datos", icon=ft.Icons.FOLDER_OPEN,
                                          on_click=self._abrir_carpeta),
                        ft.TextButton("Revisar de nuevo", icon=ft.Icons.REFRESH,
                                      on_click=lambda e: self._actualizar()),
                    ],
                    wrap=True,
                ),
                ft.Row(
                    [
                        ft.Text("Carpeta de datos:", weight=ft.FontWeight.BOLD),
                        ft.Text(carpeta, selectable=True),
                        ft.IconButton(ft.Icons.COPY, tooltip="Copiar ruta",
                                      on_click=lambda e: copiar(self.page, carpeta)),
                    ],
                    wrap=True,
                ),
                self.mensaje,
                ft.Container(height=8),
                self.boton_continuar,
            ],
            spacing=10,
            scroll=ft.ScrollMode.AUTO,
        )
        self.page.controls.clear()
        self.page.add(ft.Container(contenido, padding=30, width=760))
        self._actualizar()

    def _actualizar(self) -> None:
        faltan = carpeta_datos.faltantes()
        filas = []
        for nombre, obligatorio, descripcion in carpeta_datos.ARCHIVOS:
            esta = carpeta_datos.ruta(nombre).exists()
            if esta:
                icono, color, estado = ft.Icons.CHECK_CIRCLE, ft.Colors.GREEN, "listo"
            elif obligatorio:
                icono, color, estado = ft.Icons.ERROR_OUTLINE, ft.Colors.ERROR, "falta"
            else:
                icono, color, estado = ft.Icons.REMOVE_CIRCLE_OUTLINE, ft.Colors.OUTLINE, "opcional"
            filas.append(ft.ListTile(
                leading=ft.Icon(icono, color=color),
                title=ft.Text(f"{nombre}  ({estado})"),
                subtitle=ft.Text(descripcion),
                dense=True,
            ))
        self.lista.controls = filas
        self.boton_continuar.disabled = bool(faltan)
        self.page.update()

    # ── acciones ──────────────────────────────────────────────────────────────
    def _elegir(self, e=None) -> None:
        async def _abrir():
            archivos = await ft.FilePicker().pick_files(
                dialog_title="Elige credentials.json, server_settings.cfg y .env",
                allow_multiple=True,
            )
            self.importar([a.path for a in (archivos or []) if a.path])

        self.page.run_task(_abrir)

    def importar(self, rutas: list[str]) -> None:
        """Copia los archivos elegidos a la carpeta de datos y muestra el resultado."""
        if not rutas:
            return
        guardados, errores = [], []
        for ruta in rutas:
            try:
                guardados.append(carpeta_datos.importar(ruta))
            except Exception as exc:  # archivo ilegible o desconocido
                errores.append(str(exc))
        partes = []
        if guardados:
            partes.append("Guardado: " + ", ".join(guardados) + ".")
        partes.extend(errores)
        self.mensaje.value = " ".join(partes)
        self._actualizar()

    def _abrir_carpeta(self, e=None) -> None:
        try:
            carpeta_datos.abrir_carpeta()
        except Exception as exc:
            self.mensaje.value = f"No se pudo abrir la carpeta: {exc}"
            self.page.update()

    def _continuar(self, e=None) -> None:
        if carpeta_datos.faltantes():
            self._actualizar()
            return
        self.page.controls.clear()
        self.page.update()
        self.al_terminar()
