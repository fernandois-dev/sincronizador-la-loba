"""
Stock de Odoo → cantidad disponible de las publicaciones de Mercado Libre.

Disponible para ML = a mano en Odoo − pendiente de entregar (ventas confirmadas
aún no despachadas, del local o de ML) − stock_reserva de [MERCADOLIBRE].
Nunca menos de 0. Con 0, ML pausa la publicación sola; al volver a haber
stock, la reactiva.

Solo toca publicaciones activas o pausadas, sin variantes y con SKU que exista
en Odoo. Cada cambio queda como evento ("ESPUMA 5 CM D 24 (ESP0044): 11 → 10").
"""
from __future__ import annotations

from logger_config import get_logger

from modules.mercadolibre.client import MercadoLibreClient
from modules.mercadolibre.rutas import leer_config

logger = get_logger(__name__)

ESTADOS_SINCRONIZABLES = ("active", "paused")


def stock_reserva() -> int:
    cfg = leer_config()
    try:
        return max(int(cfg.get("MERCADOLIBRE", "stock_reserva", fallback="0") or 0), 0)
    except ValueError:
        return 0


def publicaciones(ml: MercadoLibreClient) -> list[dict]:
    """Todas las publicaciones del vendedor con estado, cantidad y SKU."""
    vendedor = ml.usuario_actual()["id"]
    ids, offset = [], 0
    while True:
        r = ml.get(f"/users/{vendedor}/items/search", params={"limit": 100, "offset": offset})
        lote = r.get("results", [])
        ids += lote
        offset += len(lote)
        if not lote or offset >= (r.get("paging") or {}).get("total", 0):
            break
    items = ml.items(ids, "id,title,status,sub_status,available_quantity,attributes,seller_custom_field,variations")
    for b in items:
        b["sku"] = (b.get("seller_custom_field") or next(
            (a.get("value_name") for a in b.get("attributes") or [] if a.get("id") == "SELLER_SKU"), "") or "").strip()
    return items


def sincronizar_stock(ml: MercadoLibreClient | None = None, odoo=None, simular: bool = False) -> tuple[list[dict], int]:
    """Una pasada. Devuelve (eventos, publicaciones revisadas)."""
    from modules.mercadolibre.ventas import Odoo

    ml = ml or MercadoLibreClient()
    odoo = odoo or Odoo()
    reserva = stock_reserva()
    items = [i for i in publicaciones(ml) if i.get("status") in ESTADOS_SINCRONIZABLES]
    skus = sorted({i["sku"] for i in items if i["sku"]})
    productos = {
        p["default_code"]: p for p in odoo("product.product", "search_read", [[["default_code", "in", skus]]],
                                           {"fields": ["default_code", "name", "qty_available", "outgoing_qty"]})
    } if skus else {}

    eventos = []
    for item in items:
        sku = item["sku"]
        if item.get("variations"):
            continue  # publicaciones con variantes: todavía no se sincronizan
        p = productos.get(sku)
        if not p:
            eventos.append({"tipo": "error", "texto": f"Stock: la publicación {item['id']} ({item.get('title', '')}) "
                                                      f"tiene SKU '{sku or 'vacío'}', que no está en Odoo.",
                            "detalle": {"item": item["id"], "sku": sku}})
            continue
        deseado = max(int((p.get("qty_available") or 0) - (p.get("outgoing_qty") or 0)) - reserva, 0)
        actual = int(item.get("available_quantity") or 0)
        if deseado == actual:
            continue
        texto = f"Sincronización de stock de {p['name'].title()} ({sku}): {actual} → {deseado}"
        if simular:
            eventos.append({"tipo": "simulacion", "texto": "(simulación) " + texto, "detalle": {}})
            continue
        ml.put(f"/items/{item['id']}", json={"available_quantity": deseado})
        logger.info("%s", texto)
        eventos.append({"tipo": "stock", "texto": texto,
                        "detalle": {"item": item["id"], "sku": sku, "antes": actual, "despues": deseado}})
    return eventos, len(items)
