"""
Propagación de campos compartidos entre las hojas de un mismo producto.

Un producto que se compra a varios proveedores aparece en varias pestañas de
la tabla base (ver modules/servidor/duplicados.py). Descripción, precio de
venta y mín/máx son del producto, no del proveedor: cuando se sincronizan con
Odoo desde una hoja, el mismo valor se escribe en las demás hojas del
producto. Si no, al cargar otra hoja se vería "distinta a Odoo" y sincronizarla
revertiría el cambio.
"""

from django.db import transaction

from logger_config import get_logger
from modules.servidor.duplicados import CAMPOS_COMPARTIDOS, DuplicadosManager, filas_del_producto, refs_producto, tarifas_locales, valores_iguales
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, OdooProducto, TablaBase
from modules.servidor.odoo import OdooService

logger = get_logger(__name__)

# clave de campo compartido -> (campo en Comparativa, campo en TablaBase)
CAMPOS_LOCALES = {
    "producto": ("producto", "descripcion"),
    "precio": ("tb_precio", "precio"),
    "min": ("tb_min", "cant_min"),
    "max": ("tb_max", "cant_max"),
}


def separar_en_conflicto(filas, claves):
    """
    Filas del lote que comparten producto de Odoo (hojas hermanas cargadas a
    la vez). Si traen valores distintos no se puede saber cuál manda: se
    excluyen del lote. Si traen el mismo valor basta sincronizar una.

    Args:
        filas (list[Comparativa])
        claves (list[str]): campos compartidos que sincroniza la página

    Returns:
        tuple: (a_sincronizar, en_conflicto: list[list[Comparativa]])
    """
    por_producto = {}
    for fila in filas:
        por_producto.setdefault(fila.producto_id, []).append(fila)

    a_sincronizar, en_conflicto = [], []
    for grupo in por_producto.values():
        valores = [{clave: getattr(f, CAMPOS_LOCALES[clave][0]) for clave in claves} for f in grupo]
        if all(all(valores_iguales(v[clave], valores[0][clave]) for clave in claves) for v in valores):
            a_sincronizar.append(grupo[0])
        else:
            en_conflicto.append(grupo)
    return a_sincronizar, en_conflicto


def texto_conflicto(en_conflicto, claves):
    lineas = []
    for grupo in en_conflicto:
        valores = "; ".join(
            f"[{f.ref_interna}] " + ", ".join(str(getattr(f, CAMPOS_LOCALES[c][0])) for c in claves) for f in grupo)
        lineas.append(f"{grupo[0].producto}: {valores}")
    return ("Estos productos se excluyeron porque sus hojas tienen valores distintos entre sí; "
            "corrige la planilla para que coincidan:\n" + "\n".join(lineas))


# Estado de la fila de un proveedor en la planilla
UBICADA = "ubicada"
SIN_HOJA = "sin_hoja"
NO_ENCONTRADA = "no_encontrada"
VARIAS = "varias"


def opciones_por_producto(producto_ids):
    """
    Para cada producto, una opción por proveedor registrado en su pestaña
    Compra de Odoo, con la fila que le corresponde en la hoja de ese
    proveedor. La fila se ubica solo por REF: el código de proveedor de la
    línea o la referencia interna del producto.

    Returns:
        dict: {producto_id: [{partner_id, proveedor, hojas, estado, fila, candidatas, ultima_compra}]}
    """
    ids = set(producto_ids)
    productos = {p.id: p for p in OdooProducto.objects.filter(id__in=ids)}
    tarifas = {pid: tarifas_locales(pid) for pid in ids}
    hojas_por_proveedor = GoogleService.get_hojas_por_proveedor()
    try:
        ultimas_compras = OdooService.get_ultimas_compras(ids)
    except Exception:
        # La fecha es informativa: si Odoo falla, el diálogo se muestra igual.
        logger.error("No se pudo obtener la fecha de última compra.", exc_info=True)
        ultimas_compras = {}

    hojas = {h for pid in ids for t in tarifas[pid] for h in hojas_por_proveedor.get(t["partner_id"][0], [])}
    refs = [r for pid in ids if pid in productos
            for r in refs_producto({"default_code": productos[pid].default_code}, tarifas[pid])]
    filas_hoja = GoogleService.buscar_filas_producto(refs=refs, hojas=hojas) if hojas and refs else []

    resultado = {}
    for pid in ids:
        ref_producto = GoogleService._normaliza_codigo(productos[pid].default_code if pid in productos else "")
        opciones, vistos = [], set()
        for t in tarifas[pid]:
            partner_id = t["partner_id"][0]
            if partner_id in vistos:
                continue
            vistos.add(partner_id)
            hojas_proveedor = hojas_por_proveedor.get(partner_id, [])
            llaves = {k for k in (GoogleService._normaliza_codigo(t.get("product_code")), ref_producto) if k}
            candidatas = [f for f in filas_hoja if f["hoja"] in hojas_proveedor and f["ref"] in llaves]
            if not hojas_proveedor:
                estado = SIN_HOJA
            elif not candidatas:
                estado = NO_ENCONTRADA
            elif len(candidatas) > 1:
                estado = VARIAS
            else:
                estado = UBICADA
            opciones.append({
                "partner_id": partner_id,
                "proveedor": (t["partner_id"][1] or str(partner_id)).strip(),
                "hojas": hojas_proveedor,
                "estado": estado,
                "fila": candidatas[0] if estado == UBICADA else None,
                "candidatas": candidatas,
                "ultima_compra": ultimas_compras.get((pid, partner_id)),
            })
        resultado[pid] = opciones
    return resultado


def valor_opcion(opcion, clave):
    """Valor de un campo compartido en la fila de la opción, normalizado como al cargar la tabla base."""
    valor = opcion["fila"][clave]
    if clave == "producto":
        return " ".join(str(valor or "").upper().split())
    return valor


def motivo_no_elegible(opcion, claves):
    """None si la opción puede ser la fuente; si no, el motivo para mostrarlo."""
    if opcion["estado"] == SIN_HOJA:
        return "no tiene hoja en la planilla (ninguna pestaña con su id en B1)"
    if opcion["estado"] == NO_ENCONTRADA:
        return f"fila no encontrada en '{', '.join(opcion['hojas'])}' (sin REF vinculada)"
    if opcion["estado"] == VARIAS:
        return "varias filas posibles: " + ", ".join(f"'{f['hoja']}' fila {f['fila']}" for f in opcion["candidatas"])
    fila = opcion["fila"]
    for clave in claves:
        encabezado = next(e for c, _, e in CAMPOS_COMPARTIDOS if c == clave)
        if encabezado in fila["formulas"]:
            return f"{encabezado} es una fórmula en su fila"
        valor = fila[clave]
        if clave != "producto":
            try:
                float(valor)
            except (TypeError, ValueError):
                return f"{encabezado} vacío o no numérico en su fila"
        elif not str(valor or "").strip():
            return "descripción vacía en su fila"
    return None


class PropagadorHojas:
    """
    Acumula los valores que se sincronizaron con Odoo y, al terminar el lote,
    los escribe en todas las hojas de cada producto con una sola lectura y una
    sola escritura de la planilla.
    """

    def __init__(self):
        self.pendientes = {}   # producto_id -> {clave: valor}

    def registrar(self, producto_id, valores):
        """Llamar después de actualizar Odoo con éxito."""
        self.pendientes.setdefault(producto_id, {}).update(valores)
        campos = {CAMPOS_LOCALES[clave][0]: valor for clave, valor in valores.items()}
        Comparativa.objects.filter(producto_id=producto_id).update(**campos)

    def escribir(self):
        """
        Escribe los valores pendientes en la planilla.

        Returns:
            dict | None: {"state", "msg"} para el registro del diálogo, o None si no hubo nada que hacer
        """
        if not self.pendientes:
            return None

        productos = {p.id: {"id": p.id, "default_code": p.default_code}
                     for p in OdooProducto.objects.filter(id__in=self.pendientes)}
        tarifas = {pid: tarifas_locales(pid) for pid in self.pendientes}
        refs = [r for pid, p in productos.items() for r in refs_producto(p, tarifas[pid])]
        try:
            filas_hoja = GoogleService.buscar_filas_producto(refs=refs)
        except Exception as e:
            logger.error("Error leyendo la planilla para propagar a hojas hermanas.", exc_info=True)
            return {"state": "E", "msg": f"Odoo quedó actualizado, pero no se pudo leer la planilla para "
                                         f"actualizar las demás hojas: {e}"}

        cambios, advertencias, ubicaciones = [], [], []
        with transaction.atomic():
            for producto_id, valores in self.pendientes.items():
                producto = productos.get(producto_id)
                if not producto:
                    continue
                filas = filas_del_producto(producto, tarifas[producto_id], filas_hoja)
                nuevos = DuplicadosManager._cambios_planilla(filas, valores, advertencias)
                cambios += nuevos
                ubicaciones += sorted({f"'{h}' fila {n}" for h, n, _, _ in nuevos})
                campos_tb = {CAMPOS_LOCALES[clave][1]: valor for clave, valor in valores.items()}
                TablaBase.objects.filter(ref_interna__in=[f["ref"] for f in filas]).update(**campos_tb)

        if not cambios and not advertencias:
            return None
        try:
            GoogleService.actualizar_celdas_tabla_base(cambios)
        except Exception as e:
            logger.error("Error escribiendo hojas hermanas.", exc_info=True)
            return {"state": "E", "msg": f"Odoo quedó actualizado, pero falló la escritura en la planilla: {e}"}

        logger.info("Hojas hermanas actualizadas: %d celdas. %s", len(cambios), ubicaciones)
        msg = (f"Planilla: {len(cambios)} celdas actualizadas en las hojas del producto: "
               + ", ".join(ubicaciones)) if cambios else "Planilla: las hojas del producto ya estaban al día."
        if advertencias:
            msg += "\n" + "\n".join(advertencias)
        return {"state": "W" if advertencias else "S", "msg": msg}
