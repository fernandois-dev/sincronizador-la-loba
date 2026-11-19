import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo
import configparser
import os

from modules.servidor.printer import get_impresoras_disponibles
from utilities import carpeta_datos

# from components.custom_input import CustomToast


class ServerConfigPage(PaginaFija, ft.Container):
    def __init__(self, page=None, params={}):
        super().__init__()
        self.page = page
        self.config_path = str(carpeta_datos.ruta("server_settings.cfg"))
        self.config = configparser.ConfigParser()

        # Cargar configuración existente o crear una nueva
        if os.path.exists(self.config_path):
            self.load_config()
        else:
            self.create_default_config()

        # Campos de configuración
        self.txt_numero_puerto = ft.TextField(
            label="Número de puerto",
            value=self.config.get("SERVER", "FASTAPI_PORT"),
            width=300,
        )

        reporte_activo = self.config.getboolean("REPORTES", "reporte_bajo_stock_activo", fallback=False)
        self.sw_reporte = ft.Switch(
            value=reporte_activo,
            active_color=ft.Colors.ORANGE_700,
        )

        self.txt_odoo_url = ft.TextField(
            label="URL de Odoo",
            value=self.config.get("ODOO", "url", fallback=""),
            width=300,
        )
        self.txt_odoo_db = ft.TextField(
            label="Base de datos",
            value=self.config.get("ODOO", "db", fallback=""),
            width=300,
        )
        self.txt_odoo_username = ft.TextField(
            label="Usuario",
            value=self.config.get("ODOO", "username", fallback=""),
            width=300,
        )
        self.txt_odoo_password = ft.TextField(
            label="Contraseña",
            value=self.config.get("ODOO", "password", fallback=""),
            password=True,
            can_reveal_password=True,
            width=300,
        )

        impresoras_disponibles = get_impresoras_disponibles()
        impresora_actual = self.config.get("IMPRESORA", "nombre", fallback="")
        if impresora_actual and impresora_actual not in impresoras_disponibles:
            impresoras_disponibles.append(impresora_actual)
        self.dd_impresora = ft.Dropdown(
            label="Impresora de códigos de barra",
            value=impresora_actual or None,
            options=[ft.DropdownOption(nombre) for nombre in impresoras_disponibles],
            width=300,
        )

        # Botones
        self.btn_guardar = ft.Button(
            content="Guardar Configuración",
            icon=ft.Icons.SAVE,
            on_click=self.save_config,
        )
        self.btn_cerrar = ft.Button(
            content="Cerrar",
            icon=ft.Icons.CLOSE,
            on_click=self.close_window,
        )

        # Layout de la ventana
        self.content = ft.Column(
            controls=[
                ft.Text("Configuración del Servidor", size=20, weight=ft.FontWeight.BOLD),
                self.txt_numero_puerto,
                ft.Divider(),
                ft.Text("Conexión con Odoo", size=16, weight=ft.FontWeight.W_600),
                self.txt_odoo_url,
                self.txt_odoo_db,
                self.txt_odoo_username,
                self.txt_odoo_password,
                ft.Divider(),
                ft.Text("Impresora", size=16, weight=ft.FontWeight.W_600),
                self.dd_impresora,
                ft.Divider(),
                ft.Text("Reportes", size=16, weight=ft.FontWeight.W_600),
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.INVENTORY_2, color=ft.Colors.ORANGE_700),
                        ft.Column(
                            controls=[
                                ft.Text("Reporte semanal de bajo stock", size=14),
                                ft.Text(
                                    "Se envía automáticamente cada lunes por Gmail",
                                    size=11, color=ft.Colors.GREY_500,
                                ),
                            ],
                            spacing=2,
                            expand=True,
                        ),
                        self.sw_reporte,
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=12,
                ),
                ft.Row(
                    controls=[self.btn_guardar, self.btn_cerrar],
                    alignment=ft.MainAxisAlignment.END,
                ),
            ],
            spacing=20,
            width=440,
        )

    def atajos(self):
        return {"f8": lambda: self.page.custom_go("/")}

    def load_config(self):
        """Carga la configuración desde el archivo."""
        carpeta_datos.leer_ini(self.config, self.config_path)

    def create_default_config(self):
        """Crea una configuración por defecto si no existe el archivo."""
        self.config["SERVER"] = {
            "FASTAPI_PORT": "3500",
        }
        with open(self.config_path, "w", encoding="utf-8") as configfile:
            self.config.write(configfile)

    def save_config(self, e):
        """Guarda la configuración en el archivo."""
        self.config["SERVER"]["FASTAPI_PORT"] = self.txt_numero_puerto.value

        if not self.config.has_section("REPORTES"):
            self.config.add_section("REPORTES")
        self.config["REPORTES"]["reporte_bajo_stock_activo"] = str(self.sw_reporte.value).lower()

        if not self.config.has_section("ODOO"):
            self.config.add_section("ODOO")
        self.config["ODOO"]["url"] = self.txt_odoo_url.value
        self.config["ODOO"]["db"] = self.txt_odoo_db.value
        self.config["ODOO"]["username"] = self.txt_odoo_username.value
        self.config["ODOO"]["password"] = self.txt_odoo_password.value

        if not self.config.has_section("IMPRESORA"):
            self.config.add_section("IMPRESORA")
        self.config["IMPRESORA"]["nombre"] = self.dd_impresora.value or ""

        with open(self.config_path, "w", encoding="utf-8") as configfile:
            self.config.write(configfile)

        # ft.Toast("Configuración guardada correctamente.").show()
        abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Configuración guardada correctamente")))
        self.page.update()
        # toast = CustomToast("Configuración guardada", duration=3, close_button=True)
        # toast.show(self.page)

    def close_window(self, e):
        """Cierra la ventana de configuración."""
        self.page.custom_go("/")
