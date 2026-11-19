"""
Registro de movimientos de stock enviados a Odoo.

Cada llamada a OdooService.set_inventario deja una fila en MovimientoStock (y una
línea en logs/app.log como respaldo), con el stock antes y después, quién lo hizo
y desde dónde. Los diálogos que sincronizan varios productos de una vez abren un
"lote" para que todas las filas de un mismo clic queden agrupadas y con el
detalle de cómo se armó la selección.
"""
import getpass
import socket
import contextvars
import uuid
from contextlib import contextmanager

from logger_config import get_logger

logger = get_logger(__name__)

# contextvars (y no threading.local) para que el lote siga vigente cuando el
# trabajo corre con asyncio.to_thread, que copia el contexto al hilo.
_lote: contextvars.ContextVar[str] = contextvars.ContextVar("lote_stock", default="")
_detalle: contextvars.ContextVar[str] = contextvars.ContextVar("detalle_lote_stock", default="")


def _equipo() -> str:
    try:
        return f"{getpass.getuser()}@{socket.gethostname()}"
    except Exception:
        return socket.gethostname()


@contextmanager
def lote(detalle: str = ""):
    """Agrupa los movimientos registrados dentro del bloque bajo un mismo id de lote."""
    id_lote = uuid.uuid4().hex[:8]
    t_lote = _lote.set(id_lote)
    t_detalle = _detalle.set(detalle or "")
    logger.info("Lote de stock %s iniciado. %s", id_lote, detalle or "")
    try:
        yield id_lote
    finally:
        _lote.reset(t_lote)
        _detalle.reset(t_detalle)


def registrar(origen: str, producto_id, producto: str = "", ref_interna: str = "",
              stock_anterior=None, valor_ingresado=None, reemplaza: bool = True,
              stock_final=None, estado: str = "", mensaje: str = ""):
    """Guarda el movimiento. Nunca lanza: un fallo al registrar no debe frenar el ajuste."""
    lote_id = _lote.get()
    detalle = _detalle.get()
    logger.info(
        "Stock [%s] lote=%s | %s | %s (id %s) | antes=%s ingresado=%s (%s) final=%s | %s | %s",
        estado, lote_id or "-", origen, producto, producto_id, stock_anterior, valor_ingresado,
        "reemplaza" if reemplaza else "suma", stock_final, mensaje, detalle,
    )
    try:
        from modules.servidor.models import MovimientoStock
        MovimientoStock.objects.create(
            origen=(origen or "")[:100],
            lote=lote_id,
            detalle=detalle[:255],
            producto_id=producto_id or 0,
            producto=(producto or "")[:255],
            ref_interna=(ref_interna or "")[:100],
            stock_anterior=stock_anterior,
            valor_ingresado=valor_ingresado,
            tipo="Reemplaza" if reemplaza else "Suma",
            stock_final=stock_final,
            estado=estado,
            mensaje=(mensaje or "")[:255],
            equipo=_equipo()[:100],
        )
    except Exception:
        logger.error("No se pudo guardar el movimiento de stock en la base.", exc_info=True)
