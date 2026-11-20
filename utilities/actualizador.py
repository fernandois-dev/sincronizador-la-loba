"""
Actualización automática desde GitHub Releases.

Flujo (solo en el programa instalado; desde el código fuente no hace nada):
1. buscar()     consulta el último Release y lo compara con la versión actual.
2. descargar()  baja el paquete de este sistema a la carpeta de datos y lo
                descomprime.
3. aplicar()    deja corriendo un script aparte que espera a que la app se
                cierre, reemplaza los archivos del programa y la vuelve a abrir.
                La app debe cerrarse justo después.

Solo se reemplazan las entradas que trae el paquete nuevo (el .exe, app/,
site-packages/...): si el programa se descomprimió en una carpeta con otros
archivos, esos no se tocan. La configuración y la base local están en otra
carpeta (utilities/carpeta_datos.py), así que tampoco se tocan.

Este módulo no depende de Flet: la interfaz está en components/aviso_actualizacion.py.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import ssl
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from utilities import carpeta_datos

REPO = "fernandois-dev/sincronizador-la-loba"
# Lista de releases (no /latest: el repo también publica el Sincronizador ML con
# tags sml-v...). GESTOR_ACTUALIZADOR_API permite probar contra otro servidor;
# puede devolver un release o una lista.
API_RELEASES = os.getenv("GESTOR_ACTUALIZADOR_API") or f"https://api.github.com/repos/{REPO}/releases?per_page=30"
PAGINA_RELEASES = f"https://github.com/{REPO}/releases/latest"

ASSET_WINDOWS = "GestorLaLoba-windows.zip"
ASSET_LINUX = "GestorLaLoba-linux.tar.gz"
EJECUTABLE = "gestor-la-loba.exe" if sys.platform == "win32" else "gestor-la-loba"


@dataclass
class Actualizacion:
    version: str
    notas: str
    url: str
    tamano: int
    pagina: str


# ── versión ───────────────────────────────────────────────────────────────────
def _numeros(version: str) -> tuple[int, ...]:
    partes = re.findall(r"\d+", version.split("-")[0].split("+")[0])
    return tuple(int(p) for p in partes[:3]) + (0,) * (3 - len(partes[:3]))


def es_mas_nueva(candidata: str, actual: str) -> bool:
    """Compara versiones tipo 1.2.3 (acepta prefijo v)."""
    return _numeros(candidata) > _numeros(actual)


def nombre_asset() -> str:
    return ASSET_WINDOWS if sys.platform == "win32" else ASSET_LINUX


def carpeta_programa() -> Path:
    """Carpeta donde está instalado el programa (la que contiene el ejecutable).

    En el paquete de flet build el código vive en <programa>/app/.
    """
    return Path(__file__).resolve().parents[2]


def disponible() -> bool:
    """El actualizador solo actúa en el programa instalado (o si se fuerza para probar)."""
    if os.getenv("GESTOR_ACTUALIZADOR") == "0":
        return False
    if os.getenv("GESTOR_ACTUALIZADOR") == "1":
        return True
    return not carpeta_datos.es_codigo_fuente()


# ── 1. buscar ─────────────────────────────────────────────────────────────────
def _contexto_ssl() -> ssl.SSLContext:
    """Certificados del sistema + los de certifi. El Python incluido en el programa
    trae su propio OpenSSL, que en algunos Linux no encuentra los del sistema."""
    contexto = ssl.create_default_context()
    try:
        import certifi
        contexto.load_verify_locations(certifi.where())
    except Exception:
        pass
    return contexto


def _abrir(pedido, timeout: float):
    return urllib.request.urlopen(pedido, timeout=timeout, context=_contexto_ssl())


def _pedir_json(url: str, timeout: float = 8) -> dict:
    pedido = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": "gestor-la-loba-actualizador",
    })
    with _abrir(pedido, timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def solo_novedades(cuerpo: str) -> str:
    """Del texto del release, lo que va antes de las instrucciones de instalación."""
    corte = re.search(r"(?m)^#+\s*Instalar", cuerpo)
    return (cuerpo[:corte.start()] if corte else cuerpo).strip()


def interpretar_release(datos: dict, version_actual: str) -> Actualizacion | None:
    """Devuelve la actualización si el release es más nuevo y trae paquete para este sistema."""
    if datos.get("draft") or datos.get("prerelease"):
        return None
    version = str(datos.get("tag_name", "")).lstrip("vV")
    if not version or not es_mas_nueva(version, version_actual):
        return None
    asset = next((a for a in datos.get("assets", []) if a.get("name") == nombre_asset()), None)
    if not asset:
        return None
    return Actualizacion(
        version=version,
        notas=solo_novedades(datos.get("body") or ""),
        url=asset["browser_download_url"],
        tamano=int(asset.get("size") or 0),
        pagina=datos.get("html_url") or PAGINA_RELEASES,
    )


def elegir_release(releases: list | dict, version_actual: str) -> Actualizacion | None:
    """De la lista de releases, la versión más nueva del Gestor (tag vX.Y.Z) que
    traiga paquete para este sistema y sea mayor que la actual."""
    if isinstance(releases, dict):
        releases = [releases]
    candidatas = []
    for datos in releases:
        if not re.fullmatch(r"[vV]\d+(\.\d+){0,2}", str(datos.get("tag_name", ""))):
            continue
        act = interpretar_release(datos, version_actual)
        if act:
            candidatas.append(act)
    return max(candidatas, key=lambda a: _numeros(a.version), default=None)


def buscar(version_actual: str) -> Actualizacion | None:
    """Consulta GitHub. Bloqueante (usar asyncio.to_thread). Sin internet → excepción."""
    return elegir_release(_pedir_json(API_RELEASES), version_actual)


# ── 2. descargar ──────────────────────────────────────────────────────────────
def _carpeta_trabajo() -> Path:
    destino = carpeta_datos.carpeta() / "actualizacion"
    destino.mkdir(parents=True, exist_ok=True)
    return destino


def descargar(act: Actualizacion, progreso=None) -> Path:
    """Descarga y descomprime el paquete. Devuelve la carpeta con el programa nuevo.

    progreso(bytes_descargados, total) se llama durante la descarga.
    """
    trabajo = _carpeta_trabajo()
    archivo = trabajo / nombre_asset()
    pedido = urllib.request.Request(act.url, headers={"User-Agent": "gestor-la-loba-actualizador"})
    with _abrir(pedido, 60) as resp, open(archivo, "wb") as salida:
        total = int(resp.headers.get("Content-Length") or act.tamano or 0)
        bajado = 0
        while True:
            bloque = resp.read(1024 * 256)
            if not bloque:
                break
            salida.write(bloque)
            bajado += len(bloque)
            if progreso:
                progreso(bajado, total)
    if act.tamano and archivo.stat().st_size != act.tamano:
        raise RuntimeError("La descarga quedó incompleta. Inténtalo de nuevo.")

    nueva = trabajo / f"v{act.version}"
    if nueva.exists():
        shutil.rmtree(nueva)
    nueva.mkdir()
    extraer(archivo, nueva)
    archivo.unlink()
    if not (nueva / EJECUTABLE).exists():
        raise RuntimeError(f"El paquete descargado no trae {EJECUTABLE}.")
    return nueva


def extraer(archivo: Path, destino: Path) -> None:
    """Descomprime sin permitir rutas fuera de destino."""
    destino = destino.resolve()
    if archivo.name.endswith(".zip"):
        with zipfile.ZipFile(archivo) as z:
            for nombre in z.namelist():
                if not (destino / nombre).resolve().is_relative_to(destino):
                    raise RuntimeError(f"Ruta no permitida en el paquete: {nombre}")
            z.extractall(destino)
    else:
        with tarfile.open(archivo) as t:
            t.extractall(destino, filter="data")


# ── 3. aplicar ────────────────────────────────────────────────────────────────
def _script_windows(nueva: Path, pid: int) -> str:
    """Script .bat. Las rutas llegan por variables de entorno (NUEVA, DESTINO,
    REGISTRO) para no depender de la codificación del archivo.

    Se escribe con saltos de línea CRLF: con LF, cmd no encuentra las etiquetas
    de los goto y el script se corta sin reemplazar nada. Cada paso queda en
    REGISTRO (la app lo copia a su log al abrir).
    """
    lineas = [
        "@echo off",
        "setlocal",
        'echo %date% %time% inicio: esperando que se cierre la app (PID {pid})>>"%REGISTRO%"',
        "set /a INTENTOS=0",
        ":esperar",
        f'tasklist /FI "PID eq {pid}" /NH 2>nul | find /I "{EJECUTABLE}" >nul',
        "if errorlevel 1 goto reemplazar",
        "set /a INTENTOS+=1",
        "if %INTENTOS% GEQ 60 goto reemplazar",
        "ping -n 2 127.0.0.1 >nul",
        "goto esperar",
        ":reemplazar",
        'echo %date% %time% app cerrada (espera %INTENTOS% s); reemplazando en %DESTINO%>>"%REGISTRO%"',
        # margen para que Windows suelte los archivos del programa
        "ping -n 3 127.0.0.1 >nul",
    ]
    for e in sorted(nueva.iterdir()):
        destino = f'"%DESTINO%\\{e.name}"'
        if e.is_dir():
            lineas.append(f'if exist {destino} rmdir /s /q {destino} 2>>"%REGISTRO%"')
        else:
            lineas.append(f'if exist {destino} del /f /q {destino} 2>>"%REGISTRO%"')
    lineas += [
        'robocopy "%NUEVA%" "%DESTINO%" /E /MOVE /NFL /NDL /NJH /NJS /R:10 /W:1 >>"%REGISTRO%"',
        "set RC=%errorlevel%",
        'echo %date% %time% robocopy termino con codigo %RC% (menor que 8 = bien)>>"%REGISTRO%"',
        "if %RC% GEQ 8 goto fallo",
        f'if not exist "%DESTINO%\\{EJECUTABLE}" goto fallo',
        f'start "" /D "%DESTINO%" "%DESTINO%\\{EJECUTABLE}"',
        'echo %date% %time% OK: app reabierta>>"%REGISTRO%"',
        'rmdir /s /q "%NUEVA%" 2>nul',
        "goto fin",
        ":fallo",
        'echo %date% %time% FALLO: no se pudo reemplazar el programa>>"%REGISTRO%"',
        f'if exist "%DESTINO%\\{EJECUTABLE}" start "" /D "%DESTINO%" "%DESTINO%\\{EJECUTABLE}"',
        ":fin",
        'endlocal',
        '(goto) 2>nul & del "%~f0"',
    ]
    return "\r\n".join(lineas).replace("{pid}", str(pid)) + "\r\n"


def _script_linux(nueva: Path, pid: int) -> str:
    """Script sh. Las rutas llegan por variables de entorno (NUEVA, DESTINO, REGISTRO)."""
    entradas = " ".join(f"'{e.name}'" for e in sorted(nueva.iterdir()))
    return f"""#!/bin/sh
echo "$(date) inicio: esperando que se cierre la app (PID {pid})" >> "$REGISTRO"
i=0
while kill -0 {pid} 2>/dev/null && [ $i -lt 60 ]; do sleep 1; i=$((i+1)); done
echo "$(date) app cerrada; reemplazando en $DESTINO" >> "$REGISTRO"
for e in {entradas}; do
  rm -rf "$DESTINO/$e"
  mv "$NUEVA/$e" "$DESTINO/$e" 2>> "$REGISTRO"
done
chmod +x "$DESTINO/{EJECUTABLE}"
rm -rf "$NUEVA"
cd "$DESTINO" && nohup "./{EJECUTABLE}" >/dev/null 2>&1 &
echo "$(date) OK: app reabierta" >> "$REGISTRO"
rm -f "$0"
"""


def entorno_limpio() -> dict:
    """Entorno para el script y la app reabierta, sin las variables internas de
    esta instancia (puerto del puente con la ventana, PYTHONHOME...). Si se
    heredan, la app nueva intenta hablar con la ventana ya cerrada y queda en blanco."""
    prefijos = ("FLET_", "PYTHON", "SERIOUS_PYTHON")
    return {k: v for k, v in os.environ.items() if not k.upper().startswith(prefijos)}


def puede_escribir(programa: Path) -> bool:
    try:
        prueba = programa / ".prueba_escritura"
        prueba.write_text("ok")
        prueba.unlink()
        return True
    except OSError:
        return False


def aplicar(nueva: Path, programa: Path | None = None, pid: int | None = None) -> Path:
    """Lanza el script que reemplaza el programa y lo reabre. Devuelve la ruta del script.

    Después de llamarlo, la app tiene que cerrarse (el script espera ese PID).
    """
    programa = programa or carpeta_programa()
    pid = pid or os.getpid()
    if not puede_escribir(programa):
        raise PermissionError(
            f"No hay permiso para escribir en {programa}. Descarga la versión nueva "
            "desde la página de Releases o instala el programa en una carpeta tuya.")
    entorno = entorno_limpio()
    entorno.update({"NUEVA": str(nueva), "DESTINO": str(programa), "REGISTRO": str(ruta_registro())})
    ruta_registro().unlink(missing_ok=True)
    if sys.platform == "win32":
        script = Path(tempfile.gettempdir()) / "actualizar_gestor_la_loba.bat"
        # Bytes tal cual: write_text en Windows convertiría \r\n en \r\r\n.
        script.write_bytes(_script_windows(nueva, pid).encode("ascii"))
        # Consola oculta propia (los comandos del script la heredan: sin ventanas
        # negras) y fuera del grupo de procesos de la app, para que no se cierre con ella.
        sin_ventana, grupo_nuevo, fuera_del_job = 0x08000000, 0x00000200, 0x01000000
        try:
            subprocess.Popen(["cmd", "/c", str(script)], env=entorno, close_fds=True,
                             creationflags=sin_ventana | grupo_nuevo | fuera_del_job)
        except OSError:
            # El job de la app no permite salir de él: se lanza igual.
            subprocess.Popen(["cmd", "/c", str(script)], env=entorno, close_fds=True,
                             creationflags=sin_ventana | grupo_nuevo)
    else:
        script = Path(tempfile.gettempdir()) / "actualizar_gestor_la_loba.sh"
        script.write_text(_script_linux(nueva, pid), encoding="utf-8")
        script.chmod(0o755)
        subprocess.Popen(["/bin/sh", str(script)], start_new_session=True, close_fds=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=entorno)
    return script


def ruta_registro() -> Path:
    """Registro del script de actualización (se revisa al abrir la app)."""
    return _carpeta_trabajo() / "registro.txt"


def leer_registro_pendiente() -> str | None:
    """Devuelve y borra el registro de la última actualización, si quedó uno."""
    ruta = ruta_registro()
    if not ruta.exists():
        return None
    texto = ruta.read_text(encoding="utf-8", errors="replace").strip()
    ruta.unlink(missing_ok=True)
    return texto or None
