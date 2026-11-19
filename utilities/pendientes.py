"""Pendientes de sincronización y compras (los números del menú lateral y del Inicio).

``contar()`` consulta la base local (Comparativa) y devuelve ``{ruta_del_menu: cantidad}``.
Es bloqueante: llamarla con ``asyncio.to_thread``. ``refrescar(page)`` pide a la
app que la vuelva a contar y actualice el menú (no hace nada si aún no está listo).
"""
from django.db.models import F, Q
from django.db.models.functions import Lower, Trim


def precios():
    from modules.servidor.models import Comparativa
    return Comparativa.objects.filter(existe=True, odoo_activo=True).exclude(tb_precio=F("odoo_precio")).count()


def descripciones():
    from modules.servidor.models import Comparativa
    return Comparativa.objects.filter(existe=True, odoo_activo=True, desc_ok=False).count()


def barcodes():
    from modules.servidor.models import Comparativa
    return Comparativa.objects.filter(existe=True).exclude(
        Q(tb_barcode__isnull=True) | Q(odoo_barcode__isnull=True)
    ).annotate(
        tb_barcode_clean=Lower(Trim("tb_barcode")),
        odoo_barcode_clean=Lower(Trim("odoo_barcode")),
    ).exclude(tb_barcode_clean=F("odoo_barcode_clean")).count()


def nuevos_productos():
    from modules.servidor.models import Comparativa
    return Comparativa.objects.exclude(existe=True).count()


def rutas_abastecimiento():
    from modules.servidor.models import Comparativa
    return Comparativa.objects.filter(existe=True).filter(
        ~Q(tb_min=F("odoo_min")) | ~Q(tb_max=F("odoo_max"))
    ).count()


def proveedores():
    from modules.servidor.pages.sincroniza_proveedores_page import proveedores_pendientes
    return proveedores_pendientes().count()


def compras():
    """Productos con cantidad en CANT. COMP pendiente de generar orden de compra."""
    from modules.servidor.models import Comparativa
    return Comparativa.objects.filter(existe=True, cantidad_compra__gt=0).count()


# ruta del menú → función que cuenta
POR_RUTA = {
    "sincronizacion/precio": precios,
    "sincronizacion/barcode": barcodes,
    "sincronizacion/descripcion": descripciones,
    "sincronizacion/nuevos_productos": nuevos_productos,
    "sincronizacion/abastecimiento": rutas_abastecimiento,
    "sincronizacion/proveedores": proveedores,
    "compras/orden_compra": compras,
}


def contar() -> dict:
    """Cantidad de pendientes por ruta del menú. Una cuenta que falle se deja en 0."""
    from logger_config import get_logger

    resultado = {}
    for ruta, fn in POR_RUTA.items():
        try:
            resultado[ruta] = int(fn() or 0)
        except Exception:
            get_logger(__name__).exception("No se pudo contar los pendientes de %s", ruta)
            resultado[ruta] = 0
    return resultado


def refrescar(page) -> None:
    """Pide recontar los pendientes y actualizar el menú."""
    pedir = getattr(page, "_refrescar_pendientes", None)
    if callable(pedir):
        pedir()
