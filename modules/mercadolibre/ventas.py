"""
Ventas de Mercado Libre → órdenes de venta en Odoo.

Cada orden pagada de ML se registra como una orden de venta confirmada en Odoo:
  - cliente "MERCADO LIBRE" (ya existe en Odoo),
  - referencia del cliente "ML <id de la orden>" (así nunca se duplica),
  - productos por SKU (default_code = SELLER_SKU de la publicación),
  - precio = lo que pagó el comprador (los precios de Odoo incluyen IVA).
Confirmarla reserva el stock, así el local no vende lo que ya se vendió en ML.
La entrega se valida y la boleta (física) se hace al despachar.

Si ML cancela una orden que ya está en Odoo y todavía no se despachó, se cancela
también en Odoo; si ya se despachó, solo se avisa en el log.

No usa las notificaciones de ML (necesitan una URL pública): revisa las órdenes
actualizadas desde la última pasada, con un margen para no perder ninguna.

Uso: scripts/ml_servicio.py (una pasada o en bucle).
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone

from logger_config import get_logger
from modules.mercadolibre.client import MercadoLibreClient, MercadoLibreError
from modules.mercadolibre.rutas import raiz

logger = get_logger(__name__)

ESTADO_PATH = raiz() / "data" / "ml_ventas_estado.json"
CLIENTE_ML = "MERCADO LIBRE"
PREFIJO_REF = "ML "
MARGEN = timedelta(hours=2)          # se vuelve a mirar este rato hacia atrás en cada pasada
INICIO_POR_DEFECTO = timedelta(days=3)


# ── Odoo ──────────────────────────────────────────────────────────────────────
class Odoo:
    """Lo mínimo de Odoo que usa el servicio. `ejecutar(modelo, método, args, kwargs)`."""

    def __init__(self, ejecutar=None):
        if ejecutar is None:
            from modules.mercadolibre.odoo_rpc import OdooRPC
            ejecutar = OdooRPC()
        self._ejecutar = ejecutar
        self._cliente_id = None
        self._productos: dict[str, int] = {}

    def __call__(self, modelo, metodo, args, kwargs=None):
        return self._ejecutar(modelo, metodo, args, kwargs or {})

    def accion(self, modelo, metodo, ids):
        """Botón de Odoo que devuelve None (XML-RPC responde 'cannot marshal None', pero se ejecutó)."""
        try:
            return self(modelo, metodo, [ids])
        except Exception as e:
            if "cannot marshal None" in str(e):
                return None
            raise

    def cliente_ml(self) -> int:
        if not self._cliente_id:
            ids = self("res.partner", "search", [[["name", "=ilike", CLIENTE_ML]]], {"limit": 1})
            if not ids:
                raise RuntimeError(f"No existe el cliente '{CLIENTE_ML}' en Odoo.")
            self._cliente_id = ids[0]
        return self._cliente_id

    def producto(self, sku: str) -> int | None:
        if sku not in self._productos:
            ids = self("product.product", "search", [[["default_code", "=", sku]]], {"limit": 1})
            if not ids:
                return None
            self._productos[sku] = ids[0]
        return self._productos[sku]

    def orden_existente(self, ref: str) -> dict | None:
        r = self("sale.order", "search_read", [[["client_order_ref", "=", ref]]],
                 {"fields": ["name", "state", "picking_ids"], "limit": 1})
        return r[0] if r else None


# ── Mercado Libre ─────────────────────────────────────────────────────────────
def ordenes_actualizadas(ml: MercadoLibreClient, desde: datetime) -> list[dict]:
    """Órdenes del vendedor actualizadas desde `desde` (todas las páginas)."""
    vendedor = ml.usuario_actual()["id"]
    ordenes, offset = [], 0
    while True:
        r = ml.get("/orders/search", params={
            "seller": vendedor,
            "order.date_last_updated.from": desde.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000-00:00"),
            "sort": "date_asc", "limit": 50, "offset": offset,
        })
        lote = r.get("results", [])
        ordenes += lote
        offset += len(lote)
        if not lote or offset >= (r.get("paging") or {}).get("total", 0):
            return ordenes


def sku_de(ml: MercadoLibreClient, linea: dict) -> str:
    item = linea.get("item") or {}
    sku = item.get("seller_sku") or item.get("seller_custom_field")
    if not sku and item.get("id"):  # User Products: el SKU viene como atributo de la publicación
        pub = ml.get(f"/items/{item['id']}", params={"attributes": "attributes,seller_custom_field"})
        sku = pub.get("seller_custom_field") or next(
            (a.get("value_name") for a in pub.get("attributes") or [] if a.get("id") == "SELLER_SKU"), None)
    return (sku or "").strip()


# ── Sincronización ────────────────────────────────────────────────────────────
def armar_orden(ml: MercadoLibreClient, odoo: Odoo, orden: dict) -> tuple[dict | None, list[str]]:
    """Valores de sale.order para la orden de ML, o (None, errores) si falta algún producto."""
    lineas, errores = [], []
    for linea in orden.get("order_items") or []:
        sku = sku_de(ml, linea)
        titulo = (linea.get("item") or {}).get("title", "")
        producto_id = odoo.producto(sku) if sku else None
        if not producto_id:
            errores.append(f"'{titulo}': SKU '{sku or 'sin SKU'}' no está en Odoo")
            continue
        lineas.append((0, 0, {
            "product_id": producto_id,
            "product_uom_qty": linea.get("quantity", 1),
            "price_unit": linea.get("unit_price") or 0,
        }))
    if errores or not lineas:
        return None, errores or ["la orden no tiene productos"]
    comprador = (orden.get("buyer") or {}).get("nickname", "")
    envio = (orden.get("shipping") or {}).get("id")
    origen = [f"Mercado Libre {orden['id']}"]
    if orden.get("pack_id"):
        origen.append(f"carrito {orden['pack_id']}")
    if envio:
        origen.append(f"envío {envio}")
    return {
        "partner_id": odoo.cliente_ml(),
        "client_order_ref": f"{PREFIJO_REF}{orden['id']}",
        "origin": " · ".join(origen),
        "note": f"Venta Mercado Libre {orden['id']} — comprador {comprador}. "
                f"Boleta física al despachar, dentro del paquete.",
        "order_line": lineas,
    }, []


def _evento(tipo: str, texto: str, **detalle) -> dict:
    """tipo: venta | cancelacion | error | aviso | simulacion | stock."""
    return {"tipo": tipo, "texto": texto, "detalle": detalle}


def procesar_orden(ml: MercadoLibreClient, odoo: Odoo, orden: dict, simular: bool = False) -> dict | None:
    """Registra / cancela una orden de ML en Odoo. Devuelve el evento, o None si no había nada que hacer."""
    ref = f"{PREFIJO_REF}{orden['id']}"
    estado = orden.get("status")
    existente = odoo.orden_existente(ref)

    if estado == "paid":
        if existente:
            return None  # ya registrada
        vals, errores = armar_orden(ml, odoo, orden)
        if not vals:
            logger.error("Venta ML %s NO registrada en Odoo: %s", orden["id"], "; ".join(errores))
            return _evento("error", f"Venta {ref} no registrada en Odoo: " + "; ".join(errores), orden=orden["id"])
        total = sum(l[2]["product_uom_qty"] * l[2]["price_unit"] for l in vals["order_line"])
        productos = ", ".join(f"{(l.get('item') or {}).get('title', '')} ×{l.get('quantity', 1)}"
                              for l in orden.get("order_items") or [])
        if simular:
            return _evento("simulacion", f"Se registraría la venta {ref} por {_plata(total)}: {productos}")
        so_id = odoo("sale.order", "create", [vals])
        odoo.accion("sale.order", "action_confirm", [so_id])
        nombre = odoo("sale.order", "read", [[so_id]], {"fields": ["name"]})[0]["name"]
        logger.info("Venta ML %s registrada en Odoo como %s ($%s).", orden["id"], nombre, total)
        return _evento("venta", f"Nueva venta {ref} → {nombre} en Odoo, {_plata(total)}: {productos}",
                       orden=orden["id"], odoo=nombre, total=total)

    if estado == "cancelled" and existente and existente["state"] != "cancel":
        despachadas = odoo("stock.picking", "search_count",
                           [[["id", "in", existente["picking_ids"]], ["state", "=", "done"]]])
        if despachadas:
            logger.warning("Venta ML %s cancelada, pero %s ya se despachó: revisar a mano.",
                           orden["id"], existente["name"])
            return _evento("error", f"Venta {ref} cancelada en Mercado Libre, pero {existente['name']} ya se "
                                    "despachó: revisar a mano.", orden=orden["id"], odoo=existente["name"])
        if simular:
            return _evento("simulacion", f"Se cancelaría {existente['name']} (venta {ref} cancelada en ML)")
        odoo.accion("sale.order", "action_cancel", [existente["id"]])
        logger.info("Venta ML %s cancelada: %s cancelada en Odoo.", orden["id"], existente["name"])
        return _evento("cancelacion", f"Venta {ref} cancelada en Mercado Libre → {existente['name']} cancelada en Odoo",
                       orden=orden["id"], odoo=existente["name"])
    return None


def _plata(monto) -> str:
    return f"${monto:,.0f}".replace(",", ".")


def _leer_estado() -> dict:
    try:
        return json.loads(ESTADO_PATH.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def _guardar_estado(estado: dict) -> None:
    ESTADO_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = ESTADO_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(estado, indent=2), encoding="utf-8")
    tmp.replace(ESTADO_PATH)


def sincronizar_ventas(ml: MercadoLibreClient | None = None, odoo: Odoo | None = None,
                       desde: datetime | None = None, simular: bool = False) -> list[dict]:
    """
    Una pasada: órdenes de ML actualizadas desde la última vez → Odoo. Devuelve los eventos.
    Solo avanza la marca de tiempo si todas las órdenes quedaron bien, para
    reintentar las que fallaron (p. ej. un SKU que falta en Odoo) en la siguiente.
    """
    ml = ml or MercadoLibreClient()
    odoo = odoo or Odoo()
    estado = _leer_estado()
    ahora = datetime.now(timezone.utc)
    if desde is None:
        ultima = estado.get("ultima_ok")
        desde = (datetime.fromisoformat(ultima) if ultima else ahora - INICIO_POR_DEFECTO) - MARGEN
    eventos = []
    for orden in ordenes_actualizadas(ml, desde):
        try:
            evento = procesar_orden(ml, odoo, orden, simular)
        except Exception as e:
            logger.error("Error procesando la venta ML %s", orden.get("id"), exc_info=True)
            evento = _evento("error", f"Error con la venta {PREFIJO_REF}{orden.get('id')}: {e}", orden=orden.get("id"))
        if evento:
            eventos.append(evento)
    if not simular and not any(e["tipo"] == "error" for e in eventos):
        _guardar_estado({**estado, "ultima_ok": ahora.isoformat()})
    return eventos


def servicio(cada_segundos: int = 300) -> None:
    """Bucle del servicio: una pasada cada `cada_segundos`. Un error no lo detiene."""
    logger.info("Servicio de ventas Mercado Libre → Odoo iniciado (cada %s s).", cada_segundos)
    while True:
        try:
            for evento in sincronizar_ventas():
                logger.info("%s", evento["texto"])
        except (MercadoLibreError, Exception):
            logger.error("Pasada de ventas ML fallida; se reintenta en la próxima.", exc_info=True)
        time.sleep(cada_segundos)
