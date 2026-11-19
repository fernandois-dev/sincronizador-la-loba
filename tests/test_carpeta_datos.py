"""
Carpeta de datos y pantalla de primera configuración (programa instalado).
"""
import asyncio
import json

import pytest

from tests.apoyo import abrir_app, problemas_en_controles
from utilities import carpeta_datos


@pytest.fixture
def carpeta_vacia(tmp_path, monkeypatch):
    """Simula un programa recién instalado: carpeta de datos vacía."""
    import main  # noqa: F401  main.py llama a preparar() al importarse: que use la carpeta real

    monkeypatch.setenv("GESTOR_ROOT", str(carpeta_datos.carpeta()))
    monkeypatch.setattr(carpeta_datos, "carpeta", lambda: tmp_path)
    # El .env de ejemplo se carga en os.environ: que no quede para las otras pruebas.
    monkeypatch.setenv("IA_API_KEY", "")
    # apoyo.py reemplaza faltantes() para que la app abra directo; aquí se usa la real.
    monkeypatch.setattr(carpeta_datos, "faltantes", lambda: [
        n for n, oblig, _ in carpeta_datos.ARCHIVOS if oblig and not (tmp_path / n).exists()])
    return tmp_path


def _archivos_de_ejemplo(origen):
    cred = origen / "credentials (1).json"
    cred.write_text(json.dumps({"type": "service_account", "private_key": "x"}), encoding="utf-8")
    cfg = origen / "server_settings.cfg"
    cfg.write_text("[ODOO]\nurl = https://ejemplo\n", encoding="utf-8")
    env = origen / "claves.txt"
    env.write_text("IA_API_KEY=abc\n", encoding="utf-8")
    return [cred, cfg, env]


def test_carpeta_en_programa_instalado(monkeypatch, tmp_path):
    monkeypatch.delenv("GESTOR_ROOT", raising=False)
    monkeypatch.setattr(carpeta_datos, "es_codigo_fuente", lambda: False)
    monkeypatch.setenv("APPDATA", str(tmp_path / "appdata"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    ruta = carpeta_datos.carpeta()
    assert ruta.name in ("GestorLaLoba", "gestor-la-loba")
    assert str(ruta).startswith(str(tmp_path))


def test_carpeta_desde_codigo_fuente(monkeypatch):
    monkeypatch.delenv("GESTOR_ROOT", raising=False)
    assert carpeta_datos.carpeta() == carpeta_datos.PROYECTO


def test_importar_reconoce_archivos(carpeta_vacia, tmp_path_factory):
    origen = tmp_path_factory.mktemp("descargas")
    guardados = [carpeta_datos.importar(r) for r in _archivos_de_ejemplo(origen)]
    assert guardados == ["credentials.json", "server_settings.cfg", ".env"]
    assert carpeta_datos.faltantes() == []
    assert (carpeta_vacia / "credentials.json").exists()


def test_pantalla_primera_configuracion(carpeta_vacia, tmp_path_factory, errores_log):
    origen = tmp_path_factory.mktemp("descargas")

    async def prueba():
        app = await abrir_app()
        # Sin archivos: aparece la pantalla de configuración, no la app.
        assert app.page.appbar is None
        assert app.page.title.startswith("Gestor La Loba")
        assert problemas_en_controles(app.page) == []

        from pages import primera_configuracion as pc
        pantalla = next(o for o in _objetos(pc.PantallaPrimeraConfiguracion))
        assert pantalla.boton_continuar.disabled

        pantalla.importar([str(r) for r in _archivos_de_ejemplo(origen)])
        assert not pantalla.boton_continuar.disabled

        pantalla._continuar()  # abre la app en la misma ventana
        await app.esperar()
        assert app.page.appbar is not None
        assert problemas_en_controles(app.page) == []
        assert app.errores_envio == []
        await app.terminar()

    asyncio.run(prueba())


def _objetos(clase):
    import gc

    return (o for o in gc.get_objects() if isinstance(o, clase))
