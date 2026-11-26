"""
Apoyo para las pruebas de la interfaz del Sincronizador.

Las pruebas abren la app sobre una sesión de Flet sin cliente (no se abre una
ventana): cada mensaje que la app enviaría al cliente se serializa igual que en
la app real, así que aparecen los mismos errores (valores que no se pueden
enviar, excepciones al construir páginas, etc.).

Nada de esto escribe en servicios reales:
- Google Sheets: sin conexión; get_hojas devuelve una pestaña de prueba.
- Odoo: conexión falsa que devuelve listas vacías y rechaza escrituras.
- HTTP (Mercado Libre, IA): bloqueado.
- La base SQLite es una copia temporal (o una base vacía migrada si no hay data/database.db).
"""
import asyncio
import os
import shutil
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

HOJA_PRUEBA = "HOJA PRUEBA"


class ServicioBloqueado(RuntimeError):
    """Una prueba intentó usar un servicio externo."""


def preparar_entorno() -> Path:
    """Configura Django sobre una copia de la base y desconecta los servicios externos.

    Devuelve la ruta de la copia de la base.
    """
    os.chdir(RAIZ)
    _sin_archivo_de_log()
    if str(RAIZ) not in sys.path:
        sys.path.insert(0, str(RAIZ))
    os.environ["DJANGO_ALLOW_ASYNC_UNSAFE"] = "true"

    copia = Path(tempfile.mkdtemp(prefix="laloba_pruebas_")) / "database.db"
    # Con la base local (equipo de desarrollo) se prueba sobre una copia; sin ella
    # (repo recién clonado, GitHub Actions) se crea vacía con las migraciones.
    if (RAIZ / "data" / "database.db").exists():
        shutil.copy2(RAIZ / "data" / "database.db", copia)

    import apps.servidor.settings  # noqa: F401  (configura Django)
    from django.conf import settings

    settings.DATABASES["default"]["NAME"] = str(copia)
    import django

    django.setup()
    from django.core.management import call_command

    call_command("migrate", interactive=False, verbosity=0)

    _sin_log_en_archivo()
    _bloquear_http()
    _odoo_falso()
    _google_falso()
    _scheduler_apagado()
    _configuracion_presente()
    return copia


def _configuracion_presente():
    """La app abre directo (sin la pantalla de primera configuración), aunque en
    la máquina de pruebas no estén credentials.json ni server_settings.cfg."""
    from utilities import carpeta_datos

    carpeta_datos._faltantes_real = getattr(carpeta_datos, "_faltantes_real", carpeta_datos.faltantes)
    carpeta_datos.faltantes = lambda: []


def _sin_archivo_de_log():
    """Antes de importar la app: su logger no abre logs/app.log (es el log real)."""
    import logging
    import logging.handlers

    class _SinArchivo(logging.NullHandler):
        def __init__(self, *args, **kwargs):
            super().__init__()

    logging.handlers.TimedRotatingFileHandler = _SinArchivo
    logging.FileHandler = _SinArchivo


def _sin_log_en_archivo():
    """Las pruebas no escriben en logs/app.log (es el log de la app real)."""
    import logging

    loggers = [logging.getLogger()] + [l for l in logging.Logger.manager.loggerDict.values()
                                       if isinstance(l, logging.Logger)]
    for logger in loggers:
        for handler in list(logger.handlers):
            if isinstance(handler, logging.FileHandler):
                logger.removeHandler(handler)
                handler.close()


def _bloquear_http():
    import requests

    def bloqueado(self, method, url, *args, **kwargs):
        raise ServicioBloqueado(f"HTTP bloqueado en pruebas: {method} {url}")

    requests.Session.request = bloqueado


def _odoo_falso():
    import modules.servidor.odoo as odoo

    lecturas = {"search", "search_read", "read", "search_count", "fields_get",
                "name_search", "read_group", "name_get", "check_access_rights"}

    def execute_kw(self, _db, _uid, _password, model, method, *args, **kwargs):
        if method not in lecturas:
            raise ServicioBloqueado(f"Odoo bloqueado en pruebas: {model}.{method}")
        return 0 if method == "search_count" else []

    odoo._OdooConnection.execute_kw = execute_kw
    odoo._OdooConnection._ensure_uid_real = getattr(
        odoo._OdooConnection, "_ensure_uid_real", odoo._OdooConnection._ensure_uid)
    odoo._OdooConnection._ensure_uid = lambda self: 1
    odoo._OdooConnection.ping = lambda self: True
    odoo._OdooConnection.is_connected = lambda self: True


def _google_falso():
    import modules.servidor.google_sheet as gs

    def sin_google(name):
        raise ServicioBloqueado(f"Google Sheets bloqueado en pruebas: {name}")

    gs._get_workbook_real = getattr(gs, "_get_workbook_real", gs._get_workbook)
    gs._get_workbook = sin_google
    gs.GoogleService.get_hojas = staticmethod(lambda: [HOJA_PRUEBA])


def _scheduler_apagado():
    import modules.servidor.reportes.scheduler as sch

    sch.ejecutar_reporte = lambda *a, **k: None


class AppDePrueba:
    """La app abierta sobre una sesión de Flet sin cliente."""

    def __init__(self, page, conexion, errores_envio, sesion):
        self.sesion = sesion  # la página guarda la sesión con referencia débil
        self.page = page
        self.conexion = conexion
        self.errores_envio = errores_envio

    def ir(self, ruta: str, params: dict | None = None):
        self.page.custom_go(ruta, params)

    async def esperar(self, segundos: float = 0.2):
        """Deja correr las tareas pendientes (hilos, run_task)."""
        await asyncio.sleep(segundos)

    async def terminar(self, limite: float = 15):
        """Espera a que terminen los trabajos en segundo plano antes de cerrar la sesión."""
        import threading

        await asyncio.sleep(0.2)
        await asyncio.to_thread(self.conexion.executor.shutdown, True)
        actual = threading.current_thread()
        for hilo in threading.enumerate():
            if hilo is not actual and hilo.daemon and hilo.is_alive():
                await asyncio.to_thread(hilo.join, limite)
        await asyncio.sleep(0.1)


async def abrir_app() -> AppDePrueba:
    """Crea una sesión de Flet de prueba y ejecuta main() del Sincronizador."""
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.messaging.connection import Connection
    from flet.messaging.protocol import configure_encode_object_for_msgpack
    from flet.messaging.session import Session
    from flet.pubsub.pubsub_hub import PubSubHub

    errores_envio: list[str] = []
    codificar = configure_encode_object_for_msgpack(BaseControl)

    class ConexionDePrueba(Connection):
        def send_message(self, message):
            try:
                msgpack.packb([message.action, message.body], default=codificar)
            except Exception as e:  # el cliente real no recibiría este mensaje
                errores_envio.append(f"{type(e).__name__}: {e}")

    conexion = ConexionDePrueba()
    conexion.loop = asyncio.get_running_loop()
    conexion.executor = ThreadPoolExecutor(max_workers=4)
    conexion.pubsubhub = PubSubHub()
    sesion = Session(conexion)
    page = sesion.page
    # Igual que al registrar un cliente real: se envía la página inicial,
    # lo que monta los controles internos (por ejemplo la pila de diálogos).
    msgpack.packb(sesion.get_page_patch(), default=codificar)

    import main as app_main
    import utilities.flet_compat as compat

    # Lo mismo que hace main.py al iniciar (si existe en esta versión).
    for nombre in ("instalar_texto_como_0_28",):
        if hasattr(compat, nombre):
            getattr(compat, nombre)()

    app_main.main(page)
    return AppDePrueba(page, conexion, errores_envio, sesion)


def problemas_en_controles(raiz) -> list[str]:
    """Revisa el árbol de controles buscando valores que el cliente rechaza.

    Son los errores que en la app real aparecen como bloques grises o como
    "type 'String' is not a subtype of type 'int'": no lanzan excepción en Python.
    """
    import flet as ft
    from flet.controls.base_control import BaseControl

    problemas: list[str] = []
    vistos: set[int] = set()

    def nombre(c):
        return f"{type(c).__name__}({getattr(c, '_i', '?')})"

    def revisar(valor, ruta):
        if isinstance(valor, BaseControl):
            if id(valor) in vistos:
                return
            vistos.add(id(valor))
            valores = getattr(valor, "_values", {}) or {}
            if isinstance(valor, ft.Text):
                v = valores.get("value")
                if v is not None and not isinstance(v, str):
                    problemas.append(f"{ruta}/{nombre(valor)}: Text.value es {type(v).__name__}")
                if isinstance(valores.get("style"), ft.TextThemeStyle):
                    problemas.append(f"{ruta}/{nombre(valor)}: Text.style recibe TextThemeStyle (usar theme_style)")
            if isinstance(valor, (ft.Row, ft.Column)) and valores.get("wrap"):
                for hijo in valor.controls or []:
                    if getattr(hijo, "expand", None) not in (None, False, 0):
                        problemas.append(
                            f"{ruta}/{nombre(valor)}: fila/columna con wrap=True tiene un hijo con expand "
                            f"({nombre(hijo)}); en la app real se ve un bloque gris"
                        )
            if isinstance(valor, ft.Icon) and isinstance(valores.get("icon"), str):
                problemas.append(f"{ruta}/{nombre(valor)}: Icon.icon es texto ({valores.get('icon')!r}); usar ft.Icons")
            for campo, v in valores.items():
                revisar(v, f"{ruta}/{nombre(valor)}.{campo}")
            for campo in getattr(type(valor), "_structural_fields", ()):
                revisar(getattr(valor, campo, None), f"{ruta}/{nombre(valor)}.{campo}")
        elif isinstance(valor, (list, tuple)):
            for i, v in enumerate(valor):
                revisar(v, f"{ruta}[{i}]")
        elif isinstance(valor, dict):
            for k, v in valor.items():
                revisar(v, f"{ruta}[{k!r}]")

    revisar(raiz, "")
    return problemas
