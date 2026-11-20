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
    monkeypatch.setattr(carpeta_datos, "faltantes",
                        getattr(carpeta_datos, "_faltantes_real", carpeta_datos.faltantes))
    return tmp_path


def _archivos_de_ejemplo(origen):
    cred = origen / "credentials (1).json"
    cred.write_text(json.dumps({"type": "service_account", "private_key": "x"}), encoding="utf-8")
    cfg = origen / "server_settings.cfg"
    cfg.write_text("[ODOO]\nurl = https://ejemplo\ndb = base\nusername = yo\npassword = clave\n",
                   encoding="utf-8")
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


def test_odoo_relee_la_configuracion_agregada_despues(carpeta_vacia, monkeypatch):
    """Primera apertura: Odoo se importa sin server_settings.cfg; al importarlo en la
    pantalla de configuración, la conexión debe usarlo sin reiniciar la app."""
    from modules.servidor import odoo

    conexion = odoo._OdooConnection()
    # apoyo.py reemplaza _ensure_uid para que las pantallas no usen la red; aquí se prueba el real.
    ensure_uid = getattr(odoo._OdooConnection, "_ensure_uid_real", odoo._OdooConnection._ensure_uid)
    assert conexion._cfg["url"] == ""

    (carpeta_vacia / "server_settings.cfg").write_text(
        "[ODOO]\nurl = https://ejemplo.odoo.com\ndb = base\nusername = yo\npassword = clave\n",
        encoding="utf-8")
    autenticado = []

    class ServidorFalso:
        def __init__(self, url, **kw):
            self.url = url

        def authenticate(self, db, usuario, clave, _):
            autenticado.append((self.url, db, usuario, clave))
            return 7

    monkeypatch.setattr(odoo.xmlrpc.client, "ServerProxy", ServidorFalso)
    assert ensure_uid(conexion) == 7
    assert autenticado == [("https://ejemplo.odoo.com/xmlrpc/2/common", "base", "yo", "clave")]


def test_cfg_parcial_se_combina_y_no_borra_odoo(carpeta_vacia, tmp_path_factory):
    """Elegir un .cfg con solo [GOOGLE] (como el bloque de IDs) no debe borrar [ODOO]."""
    origen = tmp_path_factory.mktemp("descargas")
    completo = origen / "server_settings.cfg"
    completo.write_text("[ODOO]\nurl = https://ejemplo\ndb = base\nusername = yo\npassword = clave\n"
                        "[MERCADOLIBRE_COLUMNAS]\nMLC435301 = Marca\n", encoding="utf-8")
    parcial = origen / "server_settings_google.cfg"
    parcial.write_text("; IDs\n[GOOGLE]\ntabla_base = abc\n[EMPRESA]\nnombre = Mi Ferretería\n",
                       encoding="utf-8")

    carpeta_datos.importar(parcial)          # primero solo el parcial: falta Odoo
    assert carpeta_datos.faltantes() == ["credentials.json", "server_settings.cfg"]
    assert carpeta_datos.odoo_incompleto() == ["url", "db", "username", "password"]

    carpeta_datos.importar(completo)         # luego el completo: se combinan
    import configparser
    cfg = configparser.ConfigParser()
    cfg.read(carpeta_vacia / "server_settings.cfg", encoding="utf-8")
    assert cfg["GOOGLE"]["tabla_base"] == "abc"
    assert cfg["EMPRESA"]["nombre"] == "Mi Ferretería"
    assert cfg["ODOO"]["password"] == "clave"
    assert "MLC435301" in (carpeta_vacia / "server_settings.cfg").read_text(encoding="utf-8")
    assert carpeta_datos.odoo_incompleto() == []
