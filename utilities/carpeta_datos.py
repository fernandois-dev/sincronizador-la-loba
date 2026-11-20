"""
Carpeta de configuración y datos del Gestor.

Ahí viven los archivos que NO van dentro del programa ni en git:

    .env                 claves de IA, Mercado Libre y Gmail (opcional)
    credentials.json     cuenta de servicio de Google (obligatorio)
    server_settings.cfg  Odoo, impresora, Mercado Libre (obligatorio)
    data/database.db     base local (se crea sola)
    data/ml_tokens.json, data/ia/ ...
    logs/

Dónde queda:
- Desde el código fuente (hay carpeta .git): la carpeta del proyecto, como siempre.
  server_settings.cfg sigue en apps/servidor/.
- En el programa instalado (flet build): una carpeta del usuario, que no se
  borra al actualizar:
      Windows: %APPDATA%\\GestorLaLoba
      Linux:   ~/.config/gestor-la-loba
- Si existe la variable GESTOR_ROOT, se usa esa (también la usa el .exe del
  Sincronizador ML).

Este módulo no importa nada de la app: se llama al principio de main.py,
antes del logger y de Django.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

PROYECTO = Path(__file__).resolve().parents[1]
NOMBRE_WINDOWS = "GestorLaLoba"
NOMBRE_LINUX = "gestor-la-loba"

# (archivo, obligatorio, para qué sirve)
ARCHIVOS = [
    ("credentials.json", True, "Cuenta de servicio de Google (planillas y Drive)"),
    ("server_settings.cfg", True, "Conexión a Odoo, impresora y Mercado Libre"),
    (".env", False, "Claves del asistente IA, Mercado Libre y Gmail (opcional)"),
]


def es_codigo_fuente() -> bool:
    """True cuando se ejecuta desde una copia del repositorio (desarrollo)."""
    return (PROYECTO / ".git").exists()


def carpeta() -> Path:
    """Carpeta de configuración y datos (ver la explicación del módulo)."""
    if os.getenv("GESTOR_ROOT"):
        return Path(os.environ["GESTOR_ROOT"])
    if es_codigo_fuente():
        return PROYECTO
    if sys.platform == "win32":
        base = os.getenv("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / NOMBRE_WINDOWS
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / NOMBRE_LINUX


def ruta(nombre: str) -> Path:
    """Ruta de uno de los ARCHIVOS dentro de la carpeta de datos."""
    raiz = carpeta()
    if nombre == "server_settings.cfg":
        # En el proyecto vive en apps/servidor/ (igual que modules/mercadolibre/rutas.py).
        en_proyecto = raiz / "apps" / "servidor" / "server_settings.cfg"
        if en_proyecto.exists() and not (raiz / nombre).exists():
            return en_proyecto
    return raiz / nombre


def leer_ini(parser, ruta_archivo) -> list[str]:
    """parser.read() en UTF-8 (como el Sincronizador ML), con respaldo cp1252
    para archivos guardados antes por Windows. No depende del idioma del equipo
    (el Python del programa instalado puede venir sin UTF-8 por defecto)."""
    try:
        return parser.read(ruta_archivo, encoding="utf-8")
    except UnicodeDecodeError:
        return parser.read(ruta_archivo, encoding="cp1252")


CLAVES_ODOO = ("url", "db", "username", "password")


def odoo_incompleto() -> list[str]:
    """Claves de [ODOO] que faltan en server_settings.cfg ([] si está completo)."""
    import configparser
    cfg = configparser.ConfigParser()
    try:
        leer_ini(cfg, str(ruta("server_settings.cfg")))
    except (configparser.Error, OSError):
        return list(CLAVES_ODOO)
    return [c for c in CLAVES_ODOO if not cfg.get("ODOO", c, fallback="").strip()]


def faltantes() -> list[str]:
    """Archivos obligatorios que todavía no están (o, en server_settings.cfg,
    que no traen la conexión a Odoo) en la carpeta de datos."""
    resultado = []
    for nombre, obligatorio, _ in ARCHIVOS:
        if not obligatorio:
            continue
        if not ruta(nombre).exists():
            resultado.append(nombre)
        elif nombre == "server_settings.cfg" and odoo_incompleto():
            resultado.append(nombre)
    return resultado


def importar(origen: str | Path) -> str:
    """Copia un archivo elegido por el usuario a la carpeta de datos.

    Reconoce el archivo por su nombre o por su contenido (por si se llama
    distinto, por ejemplo "credentials (1).json"). Devuelve el nombre con que
    quedó guardado.
    """
    origen = Path(origen)
    destino = _reconocer(origen)
    ruta_destino = carpeta() / destino
    ruta_destino.parent.mkdir(parents=True, exist_ok=True)
    if destino == "server_settings.cfg" and ruta_destino.exists():
        _combinar_ini(origen, ruta_destino)
    else:
        shutil.copyfile(origen, ruta_destino)
    if destino == ".env":
        _cargar_env()
    return destino


def _combinar_ini(origen: Path, destino: Path) -> None:
    """Agrega al server_settings.cfg existente las secciones y claves del elegido.

    Así, elegir un archivo con solo algunas secciones (por ejemplo [GOOGLE]) no
    borra [ODOO] ni el resto. Lo que viene en el archivo elegido manda. Se deja
    un respaldo del anterior.
    """
    import configparser
    actual = configparser.ConfigParser(interpolation=None)
    actual.optionxform = str  # respeta mayúsculas (claves tipo MLC435301)
    leer_ini(actual, str(destino))
    nuevo = configparser.ConfigParser(interpolation=None)
    nuevo.optionxform = str
    leer_ini(nuevo, str(origen))
    shutil.copyfile(destino, destino.with_name(destino.name + ".anterior"))
    for seccion in nuevo.sections():
        if not actual.has_section(seccion):
            actual.add_section(seccion)
        for clave, valor in nuevo.items(seccion, raw=True):
            actual.set(seccion, clave, valor)
    with open(destino, "w", encoding="utf-8") as salida:
        actual.write(salida)


def _reconocer(origen: Path) -> str:
    nombre = origen.name.lower()
    if nombre == ".env" or nombre.endswith(".env") or nombre == "env.txt":
        return ".env"
    if nombre.endswith(".cfg") or nombre.endswith(".ini"):
        return "server_settings.cfg"
    if nombre.endswith(".json"):
        return "credentials.json"
    texto = origen.read_text(encoding="utf-8", errors="ignore")[:4000]
    if '"type": "service_account"' in texto or '"private_key"' in texto:
        return "credentials.json"
    if "[ODOO]" in texto or "[SERVER]" in texto:
        return "server_settings.cfg"
    if "=" in texto:
        return ".env"
    raise ValueError(f"No se reconoce el archivo {origen.name}: se espera "
                     "credentials.json, server_settings.cfg o .env")


def _cargar_env() -> None:
    archivo = carpeta() / ".env"
    if archivo.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(archivo)
        except ImportError:
            pass


def preparar() -> Path:
    """Deja lista la carpeta de datos. Llamar al principio de main.py.

    - GESTOR_ROOT apunta a la carpeta (lo usan el logger y modules/mercadolibre/rutas.py).
    - Crea data/ y logs/.
    - En el programa instalado, el directorio de trabajo pasa a ser esa carpeta,
      así las rutas relativas que quedan en el código ("data/...", "logs/...")
      caen ahí y no dentro del programa.
    - Carga el .env de la carpeta (los load_dotenv() posteriores no lo pisan).
    """
    raiz = carpeta()
    raiz.mkdir(parents=True, exist_ok=True)
    (raiz / "data").mkdir(exist_ok=True)
    (raiz / "logs").mkdir(exist_ok=True)
    os.environ["GESTOR_ROOT"] = str(raiz)
    if not es_codigo_fuente():
        os.chdir(raiz)
    _cargar_env()
    return raiz


def abrir_carpeta() -> None:
    """Abre la carpeta de datos en el explorador de archivos."""
    raiz = str(carpeta())
    if sys.platform == "win32":
        os.startfile(raiz)  # noqa: S606
    else:
        import subprocess
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, raiz])
