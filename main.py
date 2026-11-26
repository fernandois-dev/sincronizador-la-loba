import asyncio
import threading
import os
import sys
import tomllib

# El Python incluido en el programa instalado no trae algunos módulos de la
# biblioteca estándar (wsgiref, que gspread necesita al importarse): se usan
# las copias de vendor/ solo si faltan.
import importlib.util
if importlib.util.find_spec("wsgiref") is None:
    sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor"))

# Primero: carpeta de configuración y datos (antes del logger y de Django).
# En el programa instalado es %APPDATA%\GestorLaLoba o ~/.config/gestor-la-loba.
from utilities import carpeta_datos
carpeta_datos.preparar()

import flet as ft
from utilities import atajos, pendientes, servicios, tema
from utilities.flet_compat import abrir_unico, instalar_texto_como_0_28
from components import aviso_actualizacion
# Import para el ORM de Django
import django
# Flet 1.x ejecuta main() y los handlers síncronos dentro del loop de asyncio.
# Django bloquea el ORM en ese contexto (SynchronousOnlyOperation). La app es
# de escritorio, de un solo usuario y con SQLite, así que se permite.
os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")
import apps.servidor.settings

# Logger — debe importarse ANTES de cualquier módulo propio para capturar
# errores de importación tempranos (incluida la conexión XML-RPC de Odoo).
from logger_config import get_logger
logger = get_logger(__name__)

from modules.servidor.google_sheet import GoogleService
from components.odoo_status_chip import OdooStatusChip
django.setup()
# import para estilos y configuraciones
from apps.servidor.styles import STYLES
from utilities.style_manager import StyleManager  # Cargar configuración del ORM

from apps.servidor.menudata import MenuData
from modules.servidor.routes import routes as server_routes



# from modules.api.routes import routes as api_routes

from router.control import ControlView

# from fastapi import FastAPI
# from data.serializers import ProductoSerializer
# import os
import configparser

# Read the port from server_settings.cfg

# Si falta el archivo, la app abre igual y muestra la pantalla de primera configuración.
config_path = str(carpeta_datos.ruta("server_settings.cfg"))
config = configparser.ConfigParser()
carpeta_datos.leer_ini(config, config_path)
FASTAPI_PORT = int(config.get('SERVER', 'FASTAPI_PORT', fallback=8000))




def get_app_version() -> str:
    """
    Lee la versión desde pyproject.toml (fuente única). En el ejecutable
    empaquetado con PyInstaller el archivo se extrae a sys._MEIPASS.
    """
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    try:
        with open(os.path.join(base, "pyproject.toml"), "rb") as f:
            return tomllib.load(f)["project"]["version"]
    except Exception as exc:
        logger.warning("No se pudo leer la versión desde pyproject.toml: %s", exc)
        return "desconocida"


APP_VERSION = get_app_version()


def _migrar_base() -> None:
    """En el programa instalado, crea o actualiza la base local al abrir.

    Revisar las migraciones toma 1–3 s, así que solo se hace cuando cambia la versión
    del programa (o si falta la base): la versión que dejó la base al día queda anotada
    en data/.version_base. Desde el código fuente se siguen aplicando a mano.
    """
    if carpeta_datos.es_codigo_fuente():
        return
    datos = carpeta_datos.carpeta() / "data"
    marca = datos / ".version_base"
    try:
        if (datos / "database.db").exists() and marca.read_text(encoding="utf-8").strip() == APP_VERSION:
            return
    except OSError:
        pass
    try:
        from django.core.management import call_command
        call_command("migrate", interactive=False, verbosity=0)
        marca.write_text(APP_VERSION, encoding="utf-8")
    except Exception:
        logger.exception("No se pudo crear o actualizar la base local")


_migrar_base()
        
def custom_go(page: ft.Page, route: str, params: dict = None) -> None:
    """
    Navega a una ruta interna de la app, con parámetros opcionales.

    En Flet 0.28, page.go cambiaba page.route y llamaba a on_route_change en
    el acto. En Flet 1.x se reemplazó por page.push_route(), que es asíncrono
    y pasa por el cliente. Como el Sincronizador muestra todas las páginas en
    una sola vista (ControlView), aquí se mantiene el comportamiento de 0.28:
    se cambia la ruta y se muestra la página de inmediato.

    Args:
        page (ft.Page): The Flet page instance.
        route (str): The route to navigate to.
        params (dict, optional): Parameters to pass to the route. Defaults to None.
    """
    page.params = params or {}
    page.route = route
    page._mostrar_ruta()


def route_change(page: ft.Page, control_view: ControlView) -> None:
    """
    Muestra la página de la ruta actual y actualiza el menú.

    Args:
        page (ft.Page): The Flet page instance.
        control_view (ControlView): The main control view instance.
    """
    control_view.display(params=page.params)
    actualizar_titulo(page, control_view)
    page.update()
    control_view.update_menu_selection(page.route)
    control_view.update_selected_item()
    page.params = {}
    page.update()
    pendientes.refrescar(page)
    
def actualizar_titulo(page: ft.Page, control_view: ControlView) -> None:
    """Pone en la barra superior el título de la pantalla actual."""
    titulo = getattr(page, "_titulo_barra", None)
    if titulo is None:
        return
    pantalla = getattr(control_view.control_page, "content", None)
    texto = getattr(pantalla, "titulo", None) or control_view.menudata.titulo_de_ruta(page.route)
    titulo.value = str(texto or "").strip()


def view_pop(page: ft.Page) -> None:
    """
    Handles the back navigation (view pop) in the app.

    Args:
        page (ft.Page): The Flet page instance.
    """
    page.views.pop()
    top_view = page.views[-1]
    page.custom_go(top_view.route)
    
def get_hojas_from_google(page: ft.Page) -> list:
        """
        Función para cargar la tabla base desde Google Sheets.
        """
        try:
            list_hojas = GoogleService.get_hojas()
        except Exception as exc:
            # Sin conexión o credentials.json inválido: la app abre igual y avisa.
            logger.error("No se pudo leer la Tabla Base de Google Sheets: %s", exc)
            abrir_unico(page, ft.SnackBar(
                ft.Text("No se pudo conectar con Google Sheets. Revisa la conexión a "
                        "internet y el archivo credentials.json (ver Sistema → Log)."),
                bgcolor=ft.Colors.ERROR, duration=8000))
            page.hojas = []
            return
        if not list_hojas:
            abrir_unico(page, ft.SnackBar(ft.Text("No se encontraron hojas en Google Sheets.")))
            page.hojas = []
            return

        page.hojas = list_hojas

def main(page: ft.Page):
    """
    Main entry point for the Flet application.

    Si faltan archivos de configuración (programa recién instalado), muestra la
    pantalla para importarlos y después abre la app en la misma ventana.

    Args:
        page (ft.Page): The Flet page instance.
    """
    if carpeta_datos.faltantes():
        from pages.primera_configuracion import mostrar_primera_configuracion
        mostrar_primera_configuracion(page, al_terminar=lambda: iniciar_app(page))
        return
    iniciar_app(page)


def iniciar_app(page: ft.Page):
    """Arma la app completa (requiere la configuración en su lugar)."""
    logger.info("Aplicación iniciada. Configurando página Flet.")

    # ── Pre-calentar la conexión Odoo en paralelo con el arranque ─────────────
    # La autenticación (~1 s) corre mientras se carga Google Sheets y se
    # construye la UI, para que la primera página no pague ese costo.
    import threading
    from modules.servidor.odoo import OdooService
    threading.Thread(target=OdooService.ping, daemon=True).start()

    # ── Scheduler semanal de bajo stock (hilo daemon, no bloquea UI) ──────────
    try:
        from modules.servidor.reportes.scheduler import ejecutar_reporte as _ejecutar_reporte
        _ejecutar_reporte(forzar=False)
    except Exception as _sched_err:
        logger.warning("No se pudo iniciar scheduler de bajo stock: %s", _sched_err)

    # Page configuration
    StyleManager.configure(STYLES)
    
    page.title = "Inventory Management System"
    page.params = {}
    page.route = "/inicio"
    page.custom_go = lambda route, params=None: custom_go(page, route, params)
    page.fonts = {
        "Roboto Mono": "RobotoMono-VariableFont_wght.ttf",
        "Roboto Slab": "RobotoSlab[wght].ttf",
    }
    page.theme_mode = ft.ThemeMode.LIGHT
    tema.aplicar(page)
    page.on_error = lambda e: logger.error("Page error: %s", e.data)
    # Initialize the main control view
    menudata = MenuData()
    get_hojas_from_google(page)
    modules = server_routes
    control_view = ControlView(page=page, modules=modules, menudata=menudata)

    # AppBar configuration
    odoo_status = OdooStatusChip(page)
    # A la izquierda el logo y el nombre de la app (chico); al centro, el título de la pantalla.
    page._titulo_barra = ft.Text("", theme_style=ft.TextThemeStyle.TITLE_LARGE, weight=ft.FontWeight.W_600)
    page.appbar = ft.AppBar(
        leading=ft.Row(
            controls=[
                ft.Container(padding=5, content=ft.Image(src="logo.svg"), width=40),
                ft.Text("Sincronizador\nLa Loba", size=12, weight=ft.FontWeight.W_500,
                        color=ft.Colors.ON_PRIMARY_CONTAINER),
            ],
            spacing=6,
        ),
        leading_width=150,
        title=page._titulo_barra,
        center_title=True,
        bgcolor=ft.Colors.PRIMARY_CONTAINER,
        actions=[
            odoo_status,
            aviso_actualizacion.boton_version(page, APP_VERSION),
        ],
    )
    aviso_actualizacion.revisar_al_iniciar(page, APP_VERSION)

    # Event handlers
    page._mostrar_ruta = lambda: route_change(page, control_view)

    def _on_route_change(e: ft.RouteChangeEvent):
        # El cliente también avisa los cambios de ruta (por ejemplo al conectar).
        # Si ya es la ruta mostrada, no se vuelve a construir la página.
        if e.route != page.route:
            custom_go(page, e.route)

    page.on_route_change = _on_route_change
    page.on_view_pop = lambda e: view_pop(page)

    # En Flet 1.x un control debe estar en la página antes de llamar a update(),
    # por eso primero se agrega la vista principal y después se navega.
    page.add(control_view)

    # Asistente IA: panel flotante a la derecha (conserva la conversación al navegar).
    try:
        from modules.servidor.components.panel_asistente import instalar_panel_asistente
        instalar_panel_asistente(page)
        # Por si hubo cambios en Odoo con la app cerrada (si no hay, no llama a la API).
        # Se importa en un hilo: el indexador carga numpy y openai (~1 s) y no debe
        # retrasar la ventana.
        def _indice_al_iniciar():
            try:
                from modules.ia.indexador import actualizar_en_segundo_plano
                actualizar_en_segundo_plano("inicio de la app")
            except Exception:
                logger.error("No se pudo revisar el índice de IA al iniciar", exc_info=True)

        threading.Thread(target=_indice_al_iniciar, name="indice-ia-inicio", daemon=True).start()
    except Exception:  # noqa: BLE001 - si falla, la app sigue sin el asistente
        logger.error("No se pudo instalar el panel del asistente IA", exc_info=True)

    # Servicios de Flet 1.x (enlaces, portapapeles, preferencias) y tema guardado.
    servicios.iniciar(page)
    atajos.instalar(page)

    async def _aplicar_preferencias():
        color = await servicios.leer_preferencia(page, "color")
        if color:
            tema.aplicar(page, color)
        if await servicios.leer_preferencia(page, "tema") == "oscuro" and control_view.left_nav:
            control_view.left_nav.aplicar_tema(True)
        elif color:
            page.update()

    page.run_task(_aplicar_preferencias)

    async def _refrescar_pendientes():
        """Recuenta los pendientes (fuera del loop) y los muestra en el menú lateral."""
        if control_view.left_nav is None:
            return
        control_view.left_nav.set_pendientes(await asyncio.to_thread(pendientes.contar))

    page._refrescar_pendientes = lambda: page.run_task(_refrescar_pendientes)
    logger.info("Navegando a ruta inicial: %s", page.route)
    page.custom_go(page.route)
    logger.info("UI cargada correctamente.")
    page.window.width = 1350
    page.window.height = 1000

    # Verificar conexión con Odoo tras montar la UI, sin bloquear el arranque
    odoo_status.check_async()


if __name__ == "__main__":
    instalar_texto_como_0_28()
    ft.run(main, #view=ft.AppView.WEB_BROWSER
           )
