"""
Motor del Sincronizador ML: pasadas periódicas (ventas ML → Odoo, luego stock
Odoo → ML), registro de eventos en SQLite y color del indicador.

Colores:
  rojo  = hay errores sin resolver (de la última pasada) o errores sin ver
  verde = hay movimientos de Mercado Libre sin ver (ventas, cancelaciones)
  azul  = sin novedades
  gris  = pausado
Los cambios de stock Odoo → ML se registran pero no cambian el color.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

from logger_config import LOG_FILE, get_logger
from modules.mercadolibre.rutas import raiz

logger = get_logger("sincronizador_ml")

DB_PATH = raiz() / "data" / "sincronizador_ml.db"
MOVIMIENTOS = ("venta", "cancelacion")
DIAS_HISTORIAL = 90


class Registro:
    """Eventos en data/sincronizador_ml.db (se ven en el panel)."""

    def __init__(self, ruta=DB_PATH):
        ruta.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(ruta, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock, self._db:
            self._db.execute("""CREATE TABLE IF NOT EXISTS eventos (
                id INTEGER PRIMARY KEY AUTOINCREMENT, fecha TEXT NOT NULL, tipo TEXT NOT NULL,
                texto TEXT NOT NULL, detalle TEXT)""")
            self._db.execute("CREATE TABLE IF NOT EXISTS estado (clave TEXT PRIMARY KEY, valor TEXT)")
            self._db.execute("DELETE FROM eventos WHERE fecha < ?",
                             ((datetime.now() - timedelta(days=DIAS_HISTORIAL)).isoformat(timespec="seconds"),))

    def agregar(self, tipo: str, texto: str, detalle: dict | None = None) -> int:
        with self._lock, self._db:
            cur = self._db.execute("INSERT INTO eventos (fecha, tipo, texto, detalle) VALUES (?, ?, ?, ?)",
                                   (datetime.now().isoformat(timespec="seconds"), tipo, texto,
                                    json.dumps(detalle or {}, ensure_ascii=False)))
            return cur.lastrowid

    def eventos(self, tipos: list[str] | None = None, limite: int = 300) -> list[dict]:
        sql, args = "SELECT id, fecha, tipo, texto, detalle FROM eventos", []
        if tipos:
            sql += f" WHERE tipo IN ({','.join('?' * len(tipos))})"
            args += tipos
        sql += " ORDER BY id DESC LIMIT ?"
        with self._lock:
            filas = self._db.execute(sql, args + [limite]).fetchall()
        return [{"id": i, "fecha": f, "tipo": t, "texto": x, "detalle": json.loads(d or "{}")} for i, f, t, x, d in filas]

    def hay_sin_ver(self, tipos) -> bool:
        with self._lock:
            return bool(self._db.execute(
                f"SELECT 1 FROM eventos WHERE id > ? AND tipo IN ({','.join('?' * len(tipos))}) LIMIT 1",
                [self.visto_hasta(), *tipos]).fetchone())

    def visto_hasta(self) -> int:
        fila = self._db.execute("SELECT valor FROM estado WHERE clave = 'visto_hasta'").fetchone()
        return int(fila[0]) if fila else 0

    def marcar_visto(self) -> None:
        with self._lock, self._db:
            ultimo = self._db.execute("SELECT COALESCE(MAX(id), 0) FROM eventos").fetchone()[0]
            self._db.execute("INSERT OR REPLACE INTO estado VALUES ('visto_hasta', ?)", (str(ultimo),))


class Motor:
    def __init__(self, cada_segundos: int = 300, al_cambiar=None, al_vender=None):
        self.cada = cada_segundos
        self.registro = Registro()
        self.pausado = False
        self.ocupado = False
        self.ultima_pasada: datetime | None = None
        self.proxima: datetime | None = None
        self.resumen = "Iniciando…"
        self.errores_activos: list[str] = []
        self.fallos_seguidos = 0
        self._despertar = threading.Event()
        self._al_cambiar = al_cambiar or (lambda: None)
        self._al_vender = al_vender or (lambda texto: None)
        self._ml = self._odoo = None

    # -- color --
    def color(self) -> str:
        if self.pausado:
            return "gris"
        if self.errores_activos or self.registro.hay_sin_ver(["error"]):
            return "rojo"
        if self.registro.hay_sin_ver(list(MOVIMIENTOS)):
            return "verde"
        return "azul"

    def estado(self) -> dict:
        return {
            "color": self.color(), "pausado": self.pausado, "ocupado": self.ocupado, "resumen": self.resumen,
            "ultima_pasada": self.ultima_pasada.isoformat(timespec="seconds") if self.ultima_pasada else None,
            "proxima": self.proxima.isoformat(timespec="seconds") if self.proxima and not self.pausado else None,
            "errores_activos": self.errores_activos, "visto_hasta": self.registro.visto_hasta(),
            "cada_minutos": round(self.cada / 60, 1),
        }

    # -- acciones --
    def sincronizar_ahora(self):
        self._despertar.set()

    def marcar_visto(self):
        self.registro.marcar_visto()
        self._al_cambiar()

    def alternar_pausa(self):
        self.pausado = not self.pausado
        self.registro.agregar("sistema", "Sincronización pausada" if self.pausado else "Sincronización reanudada")
        self._al_cambiar()
        if not self.pausado:
            self._despertar.set()

    # -- bucle --
    def iniciar(self):
        self.registro.agregar("sistema", "Sincronizador ML iniciado")
        threading.Thread(target=self._bucle, daemon=True, name="motor-ml").start()

    def _bucle(self):
        while True:
            if not self.pausado:
                self.pasada()
            self.proxima = datetime.now() + timedelta(seconds=self.cada)
            self._al_cambiar()
            self._despertar.wait(self.cada)
            self._despertar.clear()

    def pasada(self):
        from modules.mercadolibre.client import MercadoLibreClient
        from modules.mercadolibre.stock import sincronizar_stock
        from modules.mercadolibre.ventas import Odoo, sincronizar_ventas

        self.ocupado = True
        self._al_cambiar()
        inicio = time.time()
        eventos, revisadas, fallo = [], 0, None
        try:
            self._ml = self._ml or MercadoLibreClient()
            self._odoo = self._odoo or Odoo()
            eventos = sincronizar_ventas(self._ml, self._odoo)
            if any(e["tipo"] == "error" for e in eventos):
                # una venta sin registrar en Odoo haría subir el stock en ML: se espera a que se resuelva
                eventos.append({"tipo": "aviso", "texto": "Stock no sincronizado en esta pasada: "
                                                          "hay ventas sin registrar en Odoo.", "detalle": {}})
            else:
                eventos_stock, revisadas = sincronizar_stock(self._ml, self._odoo)
                eventos += eventos_stock
        except Exception as e:
            logger.error("Pasada fallida", exc_info=True)
            self._odoo = None  # reconectar en la próxima
            self.fallos_seguidos += 1
            fallo = f"No se pudo conectar, se reintenta en la próxima sincronización: {e}"
            # una falla de conexión aislada (internet, Mercado Libre u Odoo un momento) es aviso;
            # si se repite, o si es de configuración (no se arregla sola), es error
            tipo = "aviso" if _pasajero(e) and self.fallos_seguidos < 2 else "error"
            eventos.append({"tipo": tipo, "texto": fallo if tipo == "aviso" else
                            f"La sincronización falló: {e}", "detalle": {}})
        else:
            self.fallos_seguidos = 0

        # errores: se registran solo cuando aparecen (no cada 5 minutos el mismo)
        errores = [e["texto"] for e in eventos if e["tipo"] == "error"]
        for e in eventos:
            if e["tipo"] == "error" and e["texto"] in self.errores_activos:
                continue
            self.registro.agregar(e["tipo"], e["texto"], e.get("detalle"))
            if e["tipo"] in MOVIMIENTOS:
                self._al_vender(e["texto"])
        resueltos = [x for x in self.errores_activos if x not in errores]
        for x in resueltos:
            self.registro.agregar("resuelto", f"Resuelto: {x}")
        self.errores_activos = errores

        segundos = time.time() - inicio
        cuenta = {t: sum(1 for e in eventos if e["tipo"] == t)
                  for t in ("venta", "cancelacion", "stock", "error", "aviso")}
        partes = [f"{n} {nombre}" for n, nombre in (
            (cuenta["venta"], "venta(s) nueva(s)"), (cuenta["cancelacion"], "cancelación(es)"),
            (cuenta["stock"], "cambio(s) de stock"), (cuenta["error"], "error(es)"),
            (cuenta["aviso"], "aviso(s)")) if n]
        self.resumen = (", ".join(partes) if partes else "Sin novedades") + \
            (f" · {revisadas} publicación(es) revisada(s)" if revisadas else "") + f" · {segundos:.1f} s"
        self.registro.agregar("pasada", self.resumen, {"segundos": round(segundos, 1)})
        self.ultima_pasada = datetime.now()
        self.ocupado = False
        self._al_cambiar()


def _pasajero(e: Exception) -> bool:
    """¿Falla de conexión que probablemente se arregla sola?"""
    import xmlrpc.client

    import requests

    from modules.mercadolibre.client import MercadoLibreError

    if isinstance(e, (OSError, requests.RequestException, xmlrpc.client.ProtocolError, TimeoutError)):
        return True
    estado = getattr(e, "status", None)
    return isinstance(e, MercadoLibreError) and estado is not None and (estado >= 500 or estado in (403, 429))


def ultimas_lineas_log(n: int = 300) -> str:
    try:
        with open(LOG_FILE, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            f.seek(max(tam - 200_000, 0))
            return "\n".join(f.read().decode("utf-8", "replace").splitlines()[-n:])
    except FileNotFoundError:
        return ""
