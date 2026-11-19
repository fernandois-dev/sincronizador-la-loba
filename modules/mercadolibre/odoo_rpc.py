"""
Conexión XML-RPC mínima con Odoo para el Sincronizador ML.

No usa modules.servidor.odoo para que el .exe no arrastre Django ni el resto
del Gestor. Lee las mismas credenciales: sección [ODOO] de server_settings.cfg.
"""
from __future__ import annotations

import threading
import xmlrpc.client

from modules.mercadolibre.rutas import leer_config, ruta_config

_TIMEOUT = 30


class _Transporte(xmlrpc.client.SafeTransport):
    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = _TIMEOUT
        return conn


class OdooRPC:
    def __init__(self):
        cfg = leer_config()
        if not cfg.has_section("ODOO"):
            raise RuntimeError(f"Falta server_settings.cfg con la sección [ODOO] (se buscó en {ruta_config()}).")
        o = cfg["ODOO"]
        self.url, self.db = o.get("url", "").rstrip("/"), o.get("db", "")
        self.usuario, self.clave = o.get("username", ""), o.get("password", "")
        self._uid = None
        self._lock = threading.Lock()
        self._objetos = None

    def _conectar(self):
        transporte = _Transporte() if self.url.startswith("https") else None
        comun = xmlrpc.client.ServerProxy(f"{self.url}/xmlrpc/2/common", transport=transporte)
        self._uid = comun.authenticate(self.db, self.usuario, self.clave, {})
        if not self._uid:
            raise RuntimeError("Odoo rechazó el usuario o la clave de [ODOO].")
        self._objetos = xmlrpc.client.ServerProxy(
            f"{self.url}/xmlrpc/2/object", transport=_Transporte() if self.url.startswith("https") else None,
            allow_none=True)

    def __call__(self, modelo: str, metodo: str, args: list, kwargs: dict | None = None):
        with self._lock:
            for intento in (1, 2):
                try:
                    if not self._uid:
                        self._conectar()
                    return self._objetos.execute_kw(self.db, self._uid, self.clave, modelo, metodo,
                                                    args, kwargs or {})
                except (OSError, xmlrpc.client.ProtocolError):
                    self._uid = None  # conexión rota: reconectar una vez
                    if intento == 2:
                        raise
