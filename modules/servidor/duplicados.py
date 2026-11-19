"""
Productos que se compran a varios proveedores (y por lo tanto aparecen en
varias pestañas de la tabla base).

Cada pestaña es un proveedor (id en B1) y cada fila tiene su propia REF
INTERNA (ADEPAC006, TODOFER044...). En Odoo el producto es uno solo, con un
código de barras único, y el vínculo con cada hoja queda registrado en la
pestaña Compra: una línea de proveedor (product.supplierinfo) por proveedor,
con su precio de compra y, como "código del proveedor", la REF de la fila en
esa hoja. Así cada hoja conserva sus REF y Odoo sabe quién vende el producto.

Una fila de la planilla está vinculada a un producto de Odoo si:
  - su REF es la referencia interna del producto (default_code), o
  - el proveedor de su hoja + su REF coinciden con una línea de proveedor.

Este módulo resuelve dos situaciones que aparecen al sincronizar:
  - Producto nuevo cuyo código de barras ya existe en Odoo: se vincula la
    fila al producto existente (se agrega su línea de proveedor) y se
    reconcilian los campos compartidos (descripción, precio venta, mín, máx).
  - Código de barras que ya tiene OTRO producto de Odoo: el artículo está
    creado dos veces. Se unifican: el usuario elige cuál conservar, el otro se
    archiva y su stock y líneas de proveedor pasan al conservado.
"""

from dataclasses import dataclass, field

from django.db import transaction

from logger_config import get_logger
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, OdooProducto, OdooProveedor, OdooRuta, OdooTarifa, TablaBase
from modules.servidor.odoo import OdooService, normalize_barcode

logger = get_logger(__name__)

# (clave, etiqueta, encabezado en la planilla)
CAMPOS_COMPARTIDOS = [
    ("producto", "Descripción", "PRODUCTO"),
    ("precio", "Precio venta", "VENTA FLB"),
    ("min", "Cant. mínima", "MIN"),
    ("max", "Cant. máxima", "MAX"),
]

ACTUAL = "actual"
NUEVO = "nuevo"

PRESETS = {
    "Mantener existentes": {clave: ACTUAL for clave, _, _ in CAMPOS_COMPARTIDOS},
    "Usar nuevos": {clave: NUEVO for clave, _, _ in CAMPOS_COMPARTIDOS},
    "Solo actualizar precio": {**{clave: ACTUAL for clave, _, _ in CAMPOS_COMPARTIDOS}, "precio": NUEVO},
}

# Lados de una unificación (sincronización de códigos de barra)
FILA = "fila"            # producto de Odoo vinculado a la fila que se sincroniza
EXISTENTE = "existente"  # producto de Odoo que ya tiene el código de barras


def valores_iguales(a, b):
    try:
        return float(a or 0) == float(b or 0)
    except (TypeError, ValueError):
        # Igual que al cargar la tabla base: mayúsculas y espacios colapsados.
        return " ".join(str(a or "").upper().split()) == " ".join(str(b or "").upper().split())


def _numero_planilla(valor):
    """Evita escribir 3400.0 en la planilla cuando el valor es entero."""
    try:
        numero = float(valor or 0)
    except (TypeError, ValueError):
        return valor
    return int(numero) if numero.is_integer() else numero


def _norm(valor):
    return GoogleService._normaliza_codigo(valor)


def id_proveedor(valor):
    """Id de proveedor de B1 de una hoja (viene como número o texto)."""
    try:
        return int(float(valor))
    except (TypeError, ValueError):
        return None


def refs_producto(producto, tarifas):
    """REF con que un producto puede aparecer en la planilla."""
    return [r for r in [producto.get("default_code"), *(t.get("product_code") for t in tarifas)] if r]


def filas_del_producto(producto, tarifas, filas_hoja):
    """Filas de la planilla vinculadas a un producto de Odoo (ver docstring del módulo)."""
    ref = _norm(producto.get("default_code"))
    codigos = {(t["partner_id"][0], _norm(t.get("product_code"))) for t in tarifas if t.get("product_code")}
    return [f for f in filas_hoja
            if (ref and f["ref"] == ref) or (id_proveedor(f["proveedor_id"]), f["ref"]) in codigos]


def tarifas_locales(producto_id):
    """Líneas de proveedor de la caché local con el mismo formato que las de Odoo."""
    return [
        {"id": t.id, "partner_id": [t.partner_id, t.partner], "price": t.price,
         "sequence": t.sequence, "product_code": t.product_code}
        for t in OdooTarifa.objects.filter(product_tmpl_id=producto_id).order_by("sequence", "id")
    ]


def _nombre_proveedor(partner_id):
    proveedor = OdooProveedor.objects.filter(id=partner_id).first()
    return (proveedor.name if proveedor else str(partner_id)).strip()


@dataclass
class ConflictoDuplicado:
    fila: Comparativa
    existente: dict                      # product.template de Odoo que ya tiene el código
    tarifas: list = field(default_factory=list)   # líneas de proveedor del existente
    ruta: dict | None = None             # regla mín/máx del existente
    fila_hoja: dict | None = None        # fila de planilla que se intenta sincronizar
    filas_vinculadas: list = field(default_factory=list)  # filas vinculadas al existente
    otras_filas: list = field(default_factory=list)       # mismo código, sin vínculo
    error_planilla: str | None = None
    # Solo en sincronización de códigos: el producto de Odoo de la propia fila
    producto_fila: dict | None = None
    tarifas_fila: list = field(default_factory=list)
    ruta_fila: dict | None = None
    filas_fila: list = field(default_factory=list)        # filas vinculadas al producto de la fila

    @property
    def barcode(self):
        return normalize_barcode(self.fila.tb_barcode)

    def lado(self, cual):
        if cual == EXISTENTE:
            return {"producto": self.existente, "tarifas": self.tarifas, "ruta": self.ruta,
                    "filas_hoja": self.filas_vinculadas}
        return {"producto": self.producto_fila or {}, "tarifas": self.tarifas_fila, "ruta": self.ruta_fila,
                "filas_hoja": self.filas_fila or ([self.fila_hoja] if self.fila_hoja else [])}

    def valor_lado(self, cual, clave):
        lado = self.lado(cual)
        producto, ruta = lado["producto"], lado["ruta"] or {}
        return {
            "producto": producto.get("name") or "",
            "precio": producto.get("list_price") or 0,
            "min": ruta.get("product_min_qty") or 0,
            "max": ruta.get("product_max_qty") or 0,
        }[clave]

    def valor_actual(self, clave):
        return self.valor_lado(EXISTENTE, clave)

    def valor_nuevo(self, clave):
        return {
            "producto": self.fila.producto or "",
            "precio": self.fila.tb_precio or 0,
            "min": self.fila.tb_min or 0,
            "max": self.fila.tb_max or 0,
        }[clave]

    def valores_finales(self, elecciones):
        return {
            clave: self.valor_nuevo(clave) if elecciones.get(clave) == NUEVO else self.valor_actual(clave)
            for clave, _, _ in CAMPOS_COMPARTIDOS
        }

    def tarifa_proveedor_nuevo(self):
        proveedor_id = self.fila.tb_proveedor_id
        return next((t for t in self.tarifas if t["partner_id"][0] == proveedor_id), None) if proveedor_id else None


class DuplicadosManager:

    @staticmethod
    def detectar_conflictos(filas):
        """
        Separa las filas a crear en Odoo entre las que no tienen problema y las
        cuyo código de barras ya pertenece a un producto existente.

        Returns:
            tuple: (conflictos: list[ConflictoDuplicado], limpias: list[Comparativa])
        """
        return DuplicadosManager._detectar(filas, lambda fila, producto: True)

    @staticmethod
    def detectar_conflictos_barcode(filas):
        """
        Igual que detectar_conflictos, para la sincronización de códigos de
        barra: hay conflicto si el código ya lo tiene OTRO producto de Odoo.
        """
        return DuplicadosManager._detectar(filas, lambda fila, producto: producto["id"] != fila.producto_id,
                                           con_producto_fila=True)

    @staticmethod
    def _detectar(filas, es_conflicto, con_producto_fila=False):
        productos = OdooService.get_productos_por_barcodes([f.tb_barcode for f in filas if f.tb_barcode])
        por_barcode = {normalize_barcode(p["barcode"]): p for p in productos if p.get("barcode")}

        conflictos, limpias = [], []
        for fila in filas:
            producto = por_barcode.get(normalize_barcode(fila.tb_barcode))
            if producto and es_conflicto(fila, producto):
                conflictos.append(ConflictoDuplicado(fila=fila, existente=producto))
            else:
                limpias.append(fila)

        if not conflictos:
            return conflictos, limpias

        ids = [c.existente["id"] for c in conflictos]
        if con_producto_fila:
            ids += [c.fila.producto_id for c in conflictos]
            productos_fila = {p["id"]: p for p in OdooService.get_productos_por_ids([c.fila.producto_id for c in conflictos])}
        tarifas = OdooService.get_tarifas_por_productos(ids)
        rutas = OdooService.get_rutas_por_productos(ids)

        def de(producto_id):
            return (sorted((t for t in tarifas if t["product_tmpl_id"][0] == producto_id), key=lambda t: t.get("sequence") or 0),
                    next((r for r in rutas if r["product_tmpl_id"][0] == producto_id), None))

        for c in conflictos:
            c.tarifas, c.ruta = de(c.existente["id"])
            if con_producto_fila:
                c.producto_fila = productos_fila.get(c.fila.producto_id)
                c.tarifas_fila, c.ruta_fila = de(c.fila.producto_id)

        try:
            refs = [c.fila.ref_interna for c in conflictos]
            for c in conflictos:
                refs += refs_producto(c.existente, c.tarifas)
                if c.producto_fila:
                    refs += refs_producto(c.producto_fila, c.tarifas_fila)
            filas_hoja = GoogleService.buscar_filas_producto(barcodes=[c.barcode for c in conflictos], refs=refs)
            for c in conflictos:
                DuplicadosManager._asignar_filas_hoja(c, filas_hoja)
        except Exception as e:
            logger.error("No se pudo buscar los duplicados en la planilla.", exc_info=True)
            for c in conflictos:
                c.error_planilla = str(e)

        logger.info("Duplicados detectados: %d de %d filas.", len(conflictos), len(filas))
        return conflictos, limpias

    @staticmethod
    def _asignar_filas_hoja(conflicto, filas_hoja):
        ref_nueva = _norm(conflicto.fila.ref_interna)
        proveedor_nueva = conflicto.fila.tb_proveedor_id
        barcode = conflicto.barcode

        candidatas = [f for f in filas_hoja if f["ref"] == ref_nueva and f["barcode"] == barcode]
        if len(candidatas) > 1 and proveedor_nueva:
            candidatas = [f for f in candidatas if id_proveedor(f["proveedor_id"]) == proveedor_nueva]
        # Si aun así hay más de una no se puede saber cuál es; se prefiere no
        # tocar esa fila antes que editar la equivocada.
        conflicto.fila_hoja = candidatas[0] if len(candidatas) == 1 else None

        conflicto.filas_vinculadas = filas_del_producto(conflicto.existente, conflicto.tarifas, filas_hoja)
        if conflicto.producto_fila:
            conflicto.filas_fila = filas_del_producto(conflicto.producto_fila, conflicto.tarifas_fila, filas_hoja)

        conocidas = {(f["hoja"], f["fila"]) for f in [conflicto.fila_hoja, *conflicto.filas_vinculadas,
                                                      *conflicto.filas_fila] if f}
        conflicto.otras_filas = [f for f in filas_hoja
                                 if f["barcode"] == barcode and (f["hoja"], f["fila"]) not in conocidas]

    @staticmethod
    def _releer_planilla(conflicto, refs):
        """Vuelve a ubicar las filas justo antes de escribir (pueden haberse insertado filas)."""
        filas_antes = [conflicto.fila_hoja, *conflicto.filas_vinculadas, *conflicto.filas_fila]
        hojas = {f["hoja"] for f in filas_antes if f}
        if not hojas:
            return None
        fila_hoja_original = conflicto.fila_hoja
        frescas = GoogleService.buscar_filas_producto(barcodes=[conflicto.barcode], refs=refs, hojas=hojas)
        DuplicadosManager._asignar_filas_hoja(conflicto, frescas)
        if fila_hoja_original and not conflicto.fila_hoja:
            return (f"La fila de '{conflicto.fila.producto}' ya no se encuentra en la hoja "
                    f"'{fila_hoja_original['hoja']}'. Recarga la tabla base e inténtalo de nuevo.")
        return None

    @staticmethod
    def nombre_proveedor_hoja(fila_hoja):
        partner_id = id_proveedor(fila_hoja.get("proveedor_id"))
        return _nombre_proveedor(partner_id) if partner_id else ""

    # ── Vincular una fila nueva a un producto existente ────────────────────

    @staticmethod
    def resolver(conflicto, elecciones):
        """
        Vincula la fila al producto existente: registra su proveedor en Odoo
        (con la REF de la fila como código) y aplica los valores elegidos en
        Odoo, en la planilla y en las tablas locales.

        Args:
            conflicto (ConflictoDuplicado)
            elecciones (dict): {clave: ACTUAL | NUEVO} para cada campo compartido

        Returns:
            dict: {"state": "S" | "W" | "E", "msg": str}
        """
        fila = conflicto.fila
        existente = conflicto.existente
        producto_id = existente["id"]
        finales = conflicto.valores_finales(elecciones)
        detalle, advertencias = [], []

        # 1) Re-ubicar las filas en la planilla
        try:
            error = DuplicadosManager._releer_planilla(
                conflicto, [fila.ref_interna, *refs_producto(existente, conflicto.tarifas)])
        except Exception as e:
            logger.error("Error releyendo la planilla para '%s'.", fila.producto, exc_info=True)
            return {"state": "E", "msg": f"No se pudo leer la planilla, no se aplicó ningún cambio: {e}"}
        if error:
            return {"state": "E", "msg": error + " No se aplicó ningún cambio."}
        filas_objetivo = [f for f in [conflicto.fila_hoja, *conflicto.filas_vinculadas] if f]
        if not filas_objetivo:
            advertencias.append("No se encontró la fila en la planilla; solo se actualizó Odoo.")

        # 2) Odoo: campos compartidos del producto existente
        r = DuplicadosManager._aplicar_compartidos_odoo(
            producto_id, finales, {clave: conflicto.valor_actual(clave) for clave, _, _ in CAMPOS_COMPARTIDOS},
            (conflicto.ruta or {}).get("id"), detalle)
        if r.get("state") != "S":
            return r
        ruta_id = r["ruta_id"]

        # 3) Odoo: el proveedor de la fila queda registrado en la pestaña Compra,
        #    con su precio de compra y la REF de la fila como código.
        tarifa = conflicto.tarifa_proveedor_nuevo()
        tarifa_id = tarifa["id"] if tarifa else None
        secuencia = tarifa["sequence"] if tarifa else max([t.get("sequence") or 0 for t in conflicto.tarifas] or [0]) + 1
        if not fila.tb_proveedor_id:
            advertencias.append("La fila no tiene proveedor; no se registró su línea de proveedor en Odoo.")
        else:
            r = DuplicadosManager._registrar_linea_proveedor(
                producto_id, tarifa, fila.tb_proveedor_id, fila.ref_interna, fila.tb_precio_compra, secuencia, detalle)
            if r.get("state") != "S":
                return r
            tarifa_id = r["id"]

        # 4) Planilla: valores finales en la fila y en las vinculadas (sin tocar REF)
        cambios = DuplicadosManager._cambios_planilla(filas_objetivo, finales, advertencias)
        DuplicadosManager._escribir_planilla(cambios, fila.producto, detalle, advertencias)

        # 5) Tablas locales, para no tener que recargar todo
        try:
            DuplicadosManager._actualizar_local(conflicto, finales, ruta_id, tarifa_id, secuencia)
        except Exception:
            logger.error("Error actualizando tablas locales para '%s'.", fila.producto, exc_info=True)
            advertencias.append("No se pudieron actualizar las tablas locales; recarga Odoo y la tabla base.")

        msg = "\n".join([f"Vinculado a [{existente.get('default_code')}] {finales['producto']}", *detalle, *advertencias])
        logger.info("Duplicado resuelto: '%s': producto Odoo %s. %s", fila.producto, producto_id, msg)
        return {"state": "W" if advertencias else "S", "msg": msg}

    @staticmethod
    def _aplicar_compartidos_odoo(producto_id, finales, actuales, ruta_id, detalle):
        """Escribe en Odoo los campos compartidos que cambian. Devuelve el ruta_id resultante."""
        if not valores_iguales(finales["producto"], actuales["producto"]):
            r = OdooService.set_nombre_producto(producto_id, finales["producto"])
            if r.get("state") != "S":
                return {"state": "E", "msg": f"Error al actualizar la descripción en Odoo: {r.get('msg')}"}
            detalle.append(f"Odoo: descripción: {finales['producto']}")
        if not valores_iguales(finales["precio"], actuales["precio"]):
            r = OdooService.set_productos({"id": producto_id, "list_price": finales["precio"]})
            if r.get("state") != "S":
                return {"state": "E", "msg": f"Error al actualizar el precio en Odoo: {r.get('msg')}"}
            detalle.append(f"Odoo: precio venta: {finales['precio']}")
        if not (valores_iguales(finales["min"], actuales["min"]) and valores_iguales(finales["max"], actuales["max"])):
            r = OdooService.set_rutas({"id": ruta_id, "product_id": producto_id, "location_id": 8,
                                       "product_min_qty": finales["min"], "product_max_qty": finales["max"]})
            if r.get("state") != "S":
                return {"state": "E", "msg": f"Error al actualizar mín/máx en Odoo: {r.get('msg')}"}
            ruta_id = r.get("id") or ruta_id
            detalle.append(f"Odoo: mín/máx: {finales['min']}/{finales['max']}")
        return {"state": "S", "ruta_id": ruta_id}

    @staticmethod
    def _registrar_linea_proveedor(producto_id, tarifa, partner_id, codigo, precio, secuencia, detalle):
        """
        Crea o completa la línea de proveedor (pestaña Compra) de `partner_id`
        en el producto, con `codigo` como código del proveedor. Un precio 0 no
        pisa un precio real ya registrado.
        """
        codigo = (codigo or "").strip()
        cambios = {}
        if not tarifa or _norm(tarifa.get("product_code")) != _norm(codigo):
            cambios["product_code"] = codigo
        if (precio or 0) > 0 and (not tarifa or not valores_iguales(tarifa["price"], precio)):
            cambios["price"] = precio
        if tarifa and not cambios:
            return {"state": "S", "id": tarifa["id"]}

        r = OdooService.set_tarifas({
            "id": tarifa["id"] if tarifa else None, "product_tmpl_id": producto_id, "partner_id": partner_id,
            "price": cambios.get("price", None if tarifa else 0), "sequence": secuencia,
            "product_code": codigo,
        })
        if r.get("state") != "S":
            return {"state": "E", "msg": f"Error al registrar el proveedor en Odoo: {r.get('msg')}"}
        nombre = _nombre_proveedor(partner_id)
        if tarifa:
            detalle.append(f"Odoo: línea de {nombre} actualizada (código {codigo}"
                           + (f", precio compra {precio})" if "price" in cambios else ")"))
        else:
            detalle.append(f"Odoo: {nombre} agregado como proveedor (código {codigo}, precio compra {precio or 0})")
        return {"state": "S", "id": r.get("id") or (tarifa or {}).get("id")}

    @staticmethod
    def _cambios_planilla(filas, finales, advertencias):
        """Celdas a escribir para dejar `filas` con los valores `finales`. Las fórmulas no se tocan."""
        cambios = []
        for f in filas:
            for clave, etiqueta, encabezado in CAMPOS_COMPARTIDOS:
                if clave not in finales:
                    continue
                columna = f["columnas"].get(encabezado)
                if columna is None or valores_iguales(f[clave], finales[clave]):
                    continue
                if encabezado in f["formulas"]:
                    advertencias.append(f"'{f['hoja']}' fila {f['fila']}: {etiqueta} es fórmula, no se modificó.")
                    continue
                valor = finales[clave] if clave == "producto" else _numero_planilla(finales[clave])
                cambios.append((f["hoja"], f["fila"], columna, valor))
        return cambios

    @staticmethod
    def _escribir_planilla(cambios, producto, detalle, advertencias):
        try:
            GoogleService.actualizar_celdas_tabla_base(cambios)
            if cambios:
                hojas_editadas = sorted({c[0] for c in cambios})
                detalle.append(f"Planilla: {len(cambios)} celdas actualizadas en {', '.join(hojas_editadas)}")
        except Exception as e:
            logger.error("Error escribiendo la planilla para '%s'.", producto, exc_info=True)
            advertencias.append(f"Odoo quedó actualizado pero falló la escritura en la planilla: {e}")

    @staticmethod
    def _actualizar_local(conflicto, finales, ruta_id, tarifa_id, secuencia):
        fila = conflicto.fila
        producto_id = conflicto.existente["id"]
        nombre_display = f"[{conflicto.existente.get('default_code') or ''}] {finales['producto']}"

        with transaction.atomic():
            OdooProducto.objects.filter(id=producto_id).update(name=finales["producto"], list_price=finales["precio"])
            if ruta_id:
                OdooRuta.objects.update_or_create(id=ruta_id, defaults={
                    "product_tmpl_id": producto_id, "product": nombre_display,
                    "product_min_qty": finales["min"], "product_max_qty": finales["max"],
                })
            OdooTarifa.objects.filter(product_tmpl_id=producto_id).update(product_tmpl=nombre_display)
            if tarifa_id and fila.tb_proveedor_id:
                defaults = {
                    "partner_id": fila.tb_proveedor_id,
                    "partner": getattr(fila.tb_proveedor, "name", "") or "",
                    "product_tmpl_id": producto_id,
                    "product_tmpl": nombre_display,
                    "sequence": secuencia,
                    "product_code": fila.ref_interna,
                }
                if (fila.tb_precio_compra or 0) > 0:
                    defaults["price"] = fila.tb_precio_compra
                OdooTarifa.objects.update_or_create(id=tarifa_id, defaults=defaults)

            refs = [f["ref"] for f in conflicto.filas_vinculadas] + [fila.ref_interna]
            TablaBase.objects.filter(ref_interna__in=refs).update(
                descripcion=finales["producto"], precio=finales["precio"],
                cant_min=finales["min"], cant_max=finales["max"],
            )

            compartidos_comparativa = {
                "producto": finales["producto"], "odoo_producto": finales["producto"], "desc_ok": True,
                "tb_precio": finales["precio"], "odoo_precio": finales["precio"],
                "tb_min": finales["min"], "odoo_min": finales["min"],
                "tb_max": finales["max"], "odoo_max": finales["max"],
            }
            Comparativa.objects.filter(id=fila.id).update(
                producto_id=producto_id, existe=True, ruta_id=ruta_id,
                odoo_barcode=conflicto.existente.get("barcode"),
                tarifa_id=tarifa_id, odoo_codigo_proveedor=fila.ref_interna if tarifa_id else "",
                odoo_precio_compra=fila.tb_precio_compra if tarifa_id else None,
                **compartidos_comparativa,
            )
            Comparativa.objects.filter(producto_id=producto_id).exclude(id=fila.id).update(**compartidos_comparativa)

    # ── Unificar dos productos de Odoo (sincronización de códigos) ─────────

    @staticmethod
    def lineas_a_traspasar(conflicto, conservar):
        """
        Líneas de proveedor que el producto conservado debe tener para seguir
        vinculado a todas las filas del archivado: las líneas del archivado y
        una por cada hoja donde aparece el archivado sin línea propia.

        Returns:
            list[dict]: {partner_id, nombre, codigo, precio, tarifa_k (línea existente en el conservado o None)}
        """
        archivar = EXISTENTE if conservar == FILA else FILA
        k, d = conflicto.lado(conservar), conflicto.lado(archivar)
        ref_d = d["producto"].get("default_code") or ""

        deseadas = {}
        for t in d["tarifas"]:
            deseadas.setdefault(t["partner_id"][0], {
                "nombre": t["partner_id"][1], "codigo": t.get("product_code") or ref_d, "precio": t["price"]})
        for f in d["filas_hoja"]:
            partner_id = id_proveedor(f["proveedor_id"])
            if partner_id and partner_id not in deseadas:
                es_fila = conflicto.fila_hoja and (f["hoja"], f["fila"]) == (conflicto.fila_hoja["hoja"], conflicto.fila_hoja["fila"])
                deseadas[partner_id] = {"nombre": _nombre_proveedor(partner_id), "codigo": f["ref"],
                                        "precio": conflicto.fila.tb_precio_compra if es_fila else 0}

        lineas = []
        for partner_id, datos in deseadas.items():
            tarifa_k = next((t for t in k["tarifas"] if t["partner_id"][0] == partner_id), None)
            lineas.append({"partner_id": partner_id, "tarifa_k": tarifa_k, **datos})
        return lineas

    @staticmethod
    def resolver_unificacion(conflicto, conservar, elecciones, traspasar_stock=True):
        """
        Unifica los dos productos de Odoo que representan lo mismo.

        Args:
            conflicto (ConflictoDuplicado): detectado con detectar_conflictos_barcode
            conservar (str): FILA | EXISTENTE, el producto que queda activo
            elecciones (dict): {clave: FILA | EXISTENTE}, de qué producto se toma cada campo compartido
            traspasar_stock (bool): sumar el stock del archivado al conservado

        Returns:
            dict: {"state": "S" | "W" | "E", "msg": str}
        """
        archivar = EXISTENTE if conservar == FILA else FILA
        k, d = conflicto.lado(conservar), conflicto.lado(archivar)
        k_prod, d_prod = k["producto"], d["producto"]
        if not k_prod.get("id") or not d_prod.get("id"):
            return {"state": "E", "msg": "No se pudo leer uno de los dos productos en Odoo; no se aplicó ningún cambio."}
        k_id, d_id = k_prod["id"], d_prod["id"]
        ref_k, ref_d = k_prod.get("default_code") or "", d_prod.get("default_code") or ""
        finales = {clave: conflicto.valor_lado(elecciones.get(clave, conservar), clave)
                   for clave, _, _ in CAMPOS_COMPARTIDOS}
        detalle, advertencias = [], []

        def error(msg):
            hecho = ("\nAlcanzó a aplicarse: " + "; ".join(detalle)) if detalle else "\nNo se aplicó ningún cambio."
            return {"state": "E", "msg": msg + hecho}

        # 1) Re-ubicar en la planilla las filas de ambos productos
        try:
            error_planilla = DuplicadosManager._releer_planilla(conflicto, [
                conflicto.fila.ref_interna, *refs_producto(k_prod, k["tarifas"]), *refs_producto(d_prod, d["tarifas"])])
        except Exception as e:
            logger.error("Error releyendo la planilla para '%s'.", conflicto.fila.producto, exc_info=True)
            return error(f"No se pudo leer la planilla: {e}")
        if error_planilla:
            return error(error_planilla)
        k, d = conflicto.lado(conservar), conflicto.lado(archivar)
        filas_objetivo = {(f["hoja"], f["fila"]): f for f in [*k["filas_hoja"], *d["filas_hoja"]]}.values()
        if not filas_objetivo:
            advertencias.append("No se encontraron las filas en la planilla; solo se actualizó Odoo.")

        # 2) Stock del archivado al conservado
        stock_d = d_prod.get("qty_available") or 0
        if traspasar_stock and stock_d:
            r = OdooService.set_inventario(k_id, stock_d, ajuste=True, motivo="Unificación de productos duplicados")
            if r.get("state") != "S":
                return error(f"Error al traspasar stock: {r.get('msg')}")
            r = OdooService.set_inventario(d_id, 0, ajuste=False, motivo="Unificación de productos duplicados")
            if r.get("state") != "S":
                return error(f"Error al dejar en 0 el stock de [{ref_d}]: {r.get('msg')}")
            detalle.append(f"Odoo: {stock_d:g} uds de stock traspasadas de [{ref_d}] a [{ref_k}]")

        # 3) Líneas de proveedor: las filas del archivado quedan vinculadas al
        #    conservado por proveedor + código (su REF no cambia).
        secuencia = max([t.get("sequence") or 0 for t in k["tarifas"]] or [0])
        tarifas_registradas = []
        for linea in DuplicadosManager.lineas_a_traspasar(conflicto, conservar):
            tarifa_k = linea["tarifa_k"]
            if tarifa_k and tarifa_k.get("product_code") and _norm(tarifa_k["product_code"]) != _norm(linea["codigo"]):
                advertencias.append(
                    f"{linea['nombre']} ya es proveedor de [{ref_k}] con código {tarifa_k['product_code']}; "
                    f"su fila con REF {linea['codigo']} no quedará vinculada. Revísala en la planilla.")
                continue
            if not tarifa_k:
                secuencia += 1
            r = DuplicadosManager._registrar_linea_proveedor(
                # Si el conservado ya tenía ese proveedor se respeta su precio.
                k_id, tarifa_k, linea["partner_id"], linea["codigo"], 0 if tarifa_k else linea["precio"],
                tarifa_k["sequence"] if tarifa_k else secuencia, detalle)
            if r.get("state") != "S":
                return error(r.get("msg"))
            tarifas_registradas.append({**linea, "id": r["id"], "sequence": tarifa_k["sequence"] if tarifa_k else secuencia})

        # 4) Archivar el duplicado (libera el código de barras)
        r = OdooService.archivar_producto(d_id)
        if r.get("state") != "S":
            return error(r.get("msg"))
        detalle.append(f"Odoo: [{ref_d}] {d_prod.get('name')} archivado")

        # 5) Conservado: código de barras y campos compartidos
        if normalize_barcode(k_prod.get("barcode")) != conflicto.barcode:
            r = OdooService.set_productos({"id": k_id, "barcode": conflicto.barcode})
            if r.get("state") != "S":
                return error(f"Error al asignar el código de barras: {r.get('msg')}")
            detalle.append(f"Odoo: código {conflicto.barcode} asignado a [{ref_k}]")
        r = DuplicadosManager._aplicar_compartidos_odoo(
            k_id, finales, {clave: conflicto.valor_lado(conservar, clave) for clave, _, _ in CAMPOS_COMPARTIDOS},
            (k["ruta"] or {}).get("id"), detalle)
        if r.get("state") != "S":
            return error(r.get("msg"))
        ruta_id = r["ruta_id"]

        # 6) Planilla: todas las filas de ambos quedan con los valores elegidos
        cambios = DuplicadosManager._cambios_planilla(filas_objetivo, finales, advertencias)
        DuplicadosManager._escribir_planilla(cambios, conflicto.fila.producto, detalle, advertencias)

        # 7) Tablas locales
        try:
            DuplicadosManager._actualizar_local_unificacion(
                conflicto, k_prod, d_prod, finales, ruta_id, (d["ruta"] or {}).get("id"), tarifas_registradas,
                stock_d if traspasar_stock else 0, [f["ref"] for f in filas_objetivo],
            )
        except Exception:
            logger.error("Error actualizando tablas locales para '%s'.", conflicto.fila.producto, exc_info=True)
            advertencias.append("No se pudieron actualizar las tablas locales; recarga Odoo y la tabla base.")

        msg = "\n".join([f"Unificado en [{ref_k}] {finales['producto']}", *detalle, *advertencias])
        logger.info("Duplicado unificado: [%s] archivado en favor de [%s]. %s", ref_d, ref_k, msg)
        return {"state": "W" if advertencias else "S", "msg": msg}

    @staticmethod
    def _actualizar_local_unificacion(conflicto, k_prod, d_prod, finales, ruta_id, ruta_d_id,
                                      tarifas_registradas, stock_traspasado, refs_filas):
        k_id, d_id = k_prod["id"], d_prod["id"]
        nombre_display = f"[{k_prod.get('default_code') or ''}] {finales['producto']}"
        stock_k = (k_prod.get("qty_available") or 0) + stock_traspasado

        with transaction.atomic():
            OdooProducto.objects.filter(id=d_id).delete()
            OdooProducto.objects.filter(id=k_id).update(
                name=finales["producto"], list_price=finales["precio"], barcode=conflicto.barcode, qty_available=stock_k,
            )
            if ruta_d_id:
                OdooRuta.objects.filter(id=ruta_d_id).delete()
            if ruta_id:
                OdooRuta.objects.update_or_create(id=ruta_id, defaults={
                    "product_tmpl_id": k_id, "product": nombre_display,
                    "product_min_qty": finales["min"], "product_max_qty": finales["max"],
                })
            OdooTarifa.objects.filter(product_tmpl_id=d_id).delete()
            for t in tarifas_registradas:
                defaults = {"partner_id": t["partner_id"], "partner": t["nombre"], "product_tmpl_id": k_id,
                            "sequence": t["sequence"], "product_code": t["codigo"]}
                if (t["precio"] or 0) > 0:
                    defaults["price"] = t["precio"]
                OdooTarifa.objects.update_or_create(id=t["id"], defaults=defaults)
            OdooTarifa.objects.filter(product_tmpl_id=k_id).update(product_tmpl=nombre_display)

            refs = [r for r in {*refs_filas, k_prod.get("default_code"), d_prod.get("default_code")} if r]
            TablaBase.objects.filter(ref_interna__in=refs).update(
                descripcion=finales["producto"], precio=finales["precio"],
                cant_min=finales["min"], cant_max=finales["max"],
            )
            Comparativa.objects.filter(producto_id__in=[k_id, d_id]).update(
                producto_id=k_id, existe=True, desc_ok=True, ruta_id=ruta_id,
                producto=finales["producto"], odoo_producto=finales["producto"],
                tb_precio=finales["precio"], odoo_precio=finales["precio"],
                tb_min=finales["min"], odoo_min=finales["min"], tb_max=finales["max"], odoo_max=finales["max"],
                odoo_barcode=conflicto.barcode, odoo_stock=stock_k,
            )
