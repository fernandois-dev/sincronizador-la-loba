"""
Actualización automática (utilities/actualizador.py y components/aviso_actualizacion.py).
"""
import asyncio
import os
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import pytest

from utilities import actualizador as act


@pytest.fixture(autouse=True)
def carpeta_de_datos_temporal(tmp_path_factory, monkeypatch):
    """El registro y las descargas del actualizador van a una carpeta temporal."""
    from utilities import carpeta_datos

    carpeta = tmp_path_factory.mktemp("datos")
    monkeypatch.setattr(carpeta_datos, "carpeta", lambda: carpeta)
    return carpeta


def _release(tag="v1.2.0", assets=None, **extra):
    nombre = act.nombre_asset()
    return {
        "tag_name": tag,
        "body": "## Novedades\n- algo nuevo",
        "html_url": "https://github.com/x/y/releases/tag/" + tag,
        "assets": assets if assets is not None else [
            {"name": nombre, "browser_download_url": "https://x/" + nombre, "size": 123}],
        **extra,
    }


def test_comparar_versiones():
    assert act.es_mas_nueva("1.10.0", "1.9.3")
    assert act.es_mas_nueva("v2.0", "1.99.99")
    assert not act.es_mas_nueva("1.2.0", "1.2.0")
    assert not act.es_mas_nueva("1.2.0", "2026.11.5")  # versión de desarrollo vieja del pyproject


def test_interpretar_release():
    info = act.interpretar_release(_release(), "1.1.9")
    assert info.version == "1.2.0" and info.tamano == 123 and "Novedades" in info.notas
    assert act.interpretar_release(_release(), "1.2.0") is None          # misma versión
    assert act.interpretar_release(_release(assets=[]), "1.0.0") is None  # sin paquete para este sistema
    assert act.interpretar_release(_release(prerelease=True), "1.0.0") is None


def test_solo_en_programa_instalado(monkeypatch):
    monkeypatch.delenv("GESTOR_ACTUALIZADOR", raising=False)
    assert not act.disponible()  # las pruebas corren desde el código fuente
    monkeypatch.setenv("GESTOR_ACTUALIZADOR", "1")
    assert act.disponible()


def test_extraer_rechaza_rutas_fuera(tmp_path):
    malo = tmp_path / "malo.tar.gz"
    (tmp_path / "x.txt").write_text("x")
    with tarfile.open(malo, "w:gz") as t:
        t.add(tmp_path / "x.txt", arcname="../fuera.txt")
    with pytest.raises(Exception):
        act.extraer(malo, tmp_path / "destino")
    assert not (tmp_path / "fuera.txt").exists() or (tmp_path / "fuera.txt").read_text() == "x"


@pytest.mark.skipif(sys.platform == "win32", reason="script de Linux")
def test_script_linux_reemplaza_y_reabre(tmp_path):
    """Instalación de prueba: el script espera al proceso, reemplaza solo lo que
    trae el paquete nuevo y abre el ejecutable nuevo."""
    programa = tmp_path / "programa"
    (programa / "app").mkdir(parents=True)
    (programa / "app" / "viejo.py").write_text("viejo")
    (programa / act.EJECUTABLE).write_text("#!/bin/sh\necho viejo\n")
    (programa / "otro_archivo_del_usuario.txt").write_text("no tocar")

    nueva = tmp_path / "nueva"
    (nueva / "app").mkdir(parents=True)
    (nueva / "app" / "nuevo.py").write_text("nuevo")
    marca = tmp_path / "abierto.txt"
    (nueva / act.EJECUTABLE).write_text(f"#!/bin/sh\necho nuevo > '{marca}'\n")

    proceso_app = subprocess.Popen(["sleep", "2"])  # hace de la app abierta
    script = act.aplicar(nueva, programa=programa, pid=proceso_app.pid)
    time.sleep(0.5)
    assert (programa / "app" / "viejo.py").exists(), "no debe reemplazar mientras la app sigue abierta"
    proceso_app.wait()

    for _ in range(50):
        if marca.exists():
            break
        time.sleep(0.2)
    assert marca.read_text().strip() == "nuevo"
    assert not (programa / "app" / "viejo.py").exists()
    assert (programa / "app" / "nuevo.py").read_text() == "nuevo"
    assert (programa / "otro_archivo_del_usuario.txt").read_text() == "no tocar"
    assert os.access(programa / act.EJECUTABLE, os.X_OK)
    assert not nueva.exists() and not script.exists()
    assert "OK: app reabierta" in act.leer_registro_pendiente()


def test_script_windows_usa_variables_de_entorno(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "gestor-la-loba.exe").write_text("x")
    bat = act._script_windows(tmp_path, 4321)
    assert str(tmp_path) not in bat  # las rutas llegan por NUEVA/DESTINO
    assert 'rmdir /s /q "%DESTINO%\\app"' in bat
    assert "PID eq 4321" in bat and "timeout" not in bat
    bat.encode("ascii")
    # Con saltos LF, cmd no encuentra las etiquetas de los goto.
    assert bat.replace("\r\n", "").count("\n") == 0
    assert "\r\n:esperar\r\n" in bat and "\r\n:reemplazar\r\n" in bat


def test_aviso_descarga_instala_y_cierra(monkeypatch, tmp_path, errores_log):
    from tests.apoyo import abrir_app, problemas_en_controles
    from components import aviso_actualizacion as aviso

    info = act.Actualizacion("9.9.9", "## Novedades\n- prueba", "https://x/p.tar.gz", 50, "https://x")
    llamadas = []

    def descargar_falso(a, progreso):
        for i in range(0, 51, 10):
            progreso(i, 50)
            time.sleep(0.05)
        llamadas.append("descargar")
        return tmp_path

    monkeypatch.setattr(act, "descargar", descargar_falso)
    monkeypatch.setattr(act, "aplicar", lambda nueva: llamadas.append(("aplicar", nueva)))

    async def prueba():
        app = await abrir_app()
        cerrada = []

        async def destruir():
            cerrada.append(True)
        monkeypatch.setattr(type(app.page.window), "destroy", lambda self: destruir())

        ventana = aviso.AvisoActualizacion(app.page, info, "1.0.0")
        ventana.abrir()
        await app.esperar()
        assert problemas_en_controles(app.page) == []
        await ventana.actualizar()
        assert llamadas == ["descargar", ("aplicar", tmp_path)]
        assert cerrada == [True]
        assert app.errores_envio == []
        await app.terminar()

    asyncio.run(prueba())


def test_aviso_muestra_error_si_falla(monkeypatch, errores_log):
    from tests.apoyo import abrir_app
    from components import aviso_actualizacion as aviso

    def falla(a, progreso):
        raise RuntimeError("sin internet")

    monkeypatch.setattr(act, "descargar", falla)
    info = act.Actualizacion("9.9.9", "", "https://x", 0, "https://x")

    async def prueba():
        app = await abrir_app()
        ventana = aviso.AvisoActualizacion(app.page, info, "1.0.0")
        ventana.abrir()
        await ventana.actualizar()
        assert "sin internet" in ventana.estado.value
        assert not ventana.boton_despues.disabled
        await app.terminar()

    asyncio.run(prueba())


def test_entorno_limpio_no_hereda_variables_de_la_app(monkeypatch):
    monkeypatch.setenv("FLET_DART_BRIDGE_PORT", "5555")
    monkeypatch.setenv("PYTHONHOME", "/x")
    monkeypatch.setenv("HOME_DE_PRUEBA", "si")
    entorno = act.entorno_limpio()
    assert "FLET_DART_BRIDGE_PORT" not in entorno and "PYTHONHOME" not in entorno
    assert entorno["HOME_DE_PRUEBA"] == "si"


def test_elegir_release_ignora_sincronizador_ml():
    releases = [
        _release("sml-v1.0.40"),            # Sincronizador ML: otro programa
        _release("v1.3.0", prerelease=True),
        _release("v1.2.0"),
        _release("v1.1.0"),
    ]
    assert act.elegir_release(releases, "1.0.0").version == "1.2.0"
    assert act.elegir_release(releases, "1.2.0") is None
    assert act.elegir_release(_release("v2.0.0"), "1.0.0").version == "2.0.0"  # un solo release


def test_notas_sin_instrucciones_de_instalacion():
    cuerpo = "## Novedades\n\n- Arreglo X\n\n## Instalar o actualizar\n\nDescarga el zip…"
    assert act.solo_novedades(cuerpo) == "## Novedades\n\n- Arreglo X"
    assert act.solo_novedades("- solo esto") == "- solo esto"


@pytest.mark.skipif(sys.platform != "win32", reason="script de Windows (corre en GitHub Actions)")
def test_script_windows_reemplaza_y_reabre(tmp_path):
    """Con cmd y robocopy reales: espera a que la "app" se cierre, reemplaza solo
    lo que trae el paquete y la vuelve a abrir."""
    import shutil

    # La "app": ping.exe copiado con el nombre del ejecutable, abierto unos segundos.
    ping = Path(os.environ["SystemRoot"]) / "System32" / "PING.EXE"
    programa = tmp_path / "Programa con espacios (x86) y tildes ñ"
    (programa / "app").mkdir(parents=True)
    (programa / "app" / "viejo.py").write_text("viejo")
    shutil.copy(ping, programa / "gestor-la-loba.exe")
    (programa / "otro_archivo_del_usuario.txt").write_text("no tocar")

    nueva = tmp_path / "nueva"
    (nueva / "app").mkdir(parents=True)
    (nueva / "app" / "nuevo.py").write_text("nuevo")
    shutil.copy(ping, nueva / "gestor-la-loba.exe")

    proceso_app = subprocess.Popen([str(programa / "gestor-la-loba.exe"), "-n", "4", "127.0.0.1"],
                                   stdout=subprocess.DEVNULL)
    act.aplicar(nueva, programa=programa, pid=proceso_app.pid)
    time.sleep(1)
    assert (programa / "app" / "viejo.py").exists(), "no debe reemplazar con la app abierta"
    proceso_app.wait()

    registro = ""
    for _ in range(60):
        time.sleep(1)
        if act.ruta_registro().exists():
            registro = act.ruta_registro().read_text(encoding="utf-8", errors="replace")
            if "OK:" in registro or "FALLO" in registro:
                break
    assert "OK: app reabierta" in registro, registro
    assert not (programa / "app" / "viejo.py").exists()
    assert (programa / "app" / "nuevo.py").read_text() == "nuevo"
    assert (programa / "otro_archivo_del_usuario.txt").read_text() == "no tocar"
