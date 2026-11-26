"""
Catálogo de Mercado Libre armado desde la Tabla Base.

La clienta marca en sus pestañas de proveedor la casilla ML y completa PESO GR.
Este módulo:
  1. Lee de todas las pestañas las filas con ML marcado (columnas buscadas por nombre).
  2. Si CATEGORIA ML / MARCA / TITULO ML están vacías, PROPONE un valor
     (sin IA: reglas por pestaña, lista de marcas, diccionario de abreviaturas
     y el predictor de categorías de Mercado Libre).
  3. Calcula el precio ML para recibir lo mismo que VENTA FLB, con la comisión
     real de la categoría consultada a Mercado Libre.
  4. Cuenta las fotos en la carpeta de Drive (REF-1.jpg, REF-2.jpg...) y el stock en Odoo.
  5. Junta los datos de la categoría (Material, Forma…): columnas "<DATO> ML" de la
     pestaña, luego la pestaña FICHAS ML (mercadolibre/fichas.py), luego los valores
     por defecto de [MERCADOLIBRE_COLUMNAS]; y avisa los obligatorios que faltan.
  6. Marca lo que falta para poder publicar.

Lo que dice la planilla siempre manda: una propuesta solo se usa si la celda está vacía,
y al aprobarla se escribe en la planilla.

Configuración opcional en server_settings.cfg (utilities/carpeta_datos.py):

    [MERCADOLIBRE]
    carpeta_fotos_id = <id de la carpeta compartida de Drive>
    tipo_publicacion = gold_special        ; Clásica (gold_pro = Premium)
    stock_reserva = 0                      ; unidades que no se ofrecen en ML
    marcas = TRUPER, CAIMI, ...            ; marcas extra a reconocer en PRODUCTO
    descripcion_ia = comercial             ; o "datos": solo datos conocidos, sin usos

    [MERCADOLIBRE_CATEGORIAS]
    ; pestaña de proveedor = categoría ML (para cuando el predictor se equivoca)
    ESPUMA BASE 2026 = MLC435303
"""
from __future__ import annotations

import configparser
import json
import math
import re
from collections import Counter

from logger_config import get_logger
from utilities import carpeta_datos
from modules.mercadolibre import fichas
from modules.mercadolibre.client import MercadoLibreClient, MercadoLibreError, SITE_ID

logger = get_logger(__name__)

FILA_ENCABEZADOS = 3
COL_ML, COL_PESO, COL_CATEGORIA, COL_MARCA, COL_TITULO = "ML", "PESO GR", "CATEGORIA ML", "MARCA", "TITULO ML"
# Toda otra columna que termine en " ML" es un dato de la categoría (FORMA ML, LARGO ML, VOLTAJE ML…)
COLS_ML_RESERVADAS = {"ML", "CATEGORIA ML", "CATEGORÍA ML", "TITULO ML", "TÍTULO ML", "DESCRIPCION ML", "DESCRIPCIÓN ML",
                      "RECARGO ML"}
# Recargo solo para Mercado Libre (embalaje, bolsa…): monto en pesos ("1500") o % del precio local ("5%").
# Se suma a lo que debe recibir La Loba; comisión y envío se calculan sobre ese total.
COL_RECARGO = "RECARGO ML"
COL_DESCRIPCION = "DESCRIPCION ML"   # texto plano; la IA propone si está vacía (también vale "DESCRIPCIÓN ML")
COL_MEDIDAS = "MEDIDAS PAQUETE"   # "LxAxH" en cm del paquete ya embalado, p. ej. 150x40x40
UMBRAL_ENVIO_GRATIS = 19990       # desde este precio ML obliga a ofrecer envío gratis (tarifa más alta)
DIVISOR_VOLUMETRICO = 4000        # peso volumétrico (kg) = largo × ancho × alto (cm) / 4000
MAX_TITULO = 60
VALORES_SI = {"TRUE", "SI", "SÍ", "X", "✓", "✔", "1"}

ESTADO_LISTO = "Listo para publicar"
ESTADO_REVISAR = "Revisar propuestas"
ESTADO_FALTAN = "Faltan datos"
ESTADO_SIN_STOCK = "Sin stock"
ESTADO_PUBLICADO = "Publicado en ML"
ESTADO_PAUSADO = "Pausado en ML"
ESTADO_EN_REVISION = "En revisión en ML"

MARCAS_BASE = [
    "TRUPER", "PRETUL", "STANLEY", "BOSCH", "MAKITA", "DEWALT", "BLACK+DECKER", "BAHCO", "TOTAL",
    "INGCO", "UYUSTOOLS", "3M", "SIKA", "SOQUINA", "SIPALAC", "KROMACOL", "CAIMI",
    "LOCTITE", "WD-40", "TOPEX", "IRWIN", "TRAMONTINA", "FORCE", "FRAS-LE", "JURID",
    "TEXTAR", "FERODO", "BREMBO", "TRW", "COBREQ", "GTX",
]

# Abreviaturas frecuentes en PRODUCTO → texto para el título. Se aplican como palabra completa.
ABREVIATURAS = {
    "GOLI.": "Golilla", "PLAN.": "Plana", "CORRI.": "Corriente", "TUE.": "Tuerca", "HEX.": "Hexagonal",
    "AUTOPERF.": "Autoperforante", "T.": "Tornillo", "C/GOL.": "con Golilla", "C/": "con ", "P/": "para ",
    "S/": "sin ", "DEL.": "Delantera", "TRAS.": "Trasera", "DELANT.": "Delantera", "PQ": "Paquete",
    "U": "unidades", "UDS": "unidades", "ROLL": "Rollo", "MT": "m", "MTS": "m", "MTRS": "m", "LT": "L",
    "LTS": "L", "GR": "g", "GRS": "g", "KG": "kg", "KGS": "kg", "CM": "cm", "MM": "mm", "ML": "ml",
}
UNIDADES = {"cm", "mm", "m", "kg", "g", "L", "ml"}
PALABRAS_MINUSCULA = {"de", "del", "la", "el", "para", "con", "sin", "y", "en", "a", "x", "por"}


# ── configuración ──────────────────────────────────────────────────────────────
def config_ml() -> dict:
    parser = configparser.ConfigParser()
    parser.optionxform = str  # respetar mayúsculas de los nombres de pestaña
    carpeta_datos.leer_ini(parser, str(carpeta_datos.ruta("server_settings.cfg")))
    sec = parser["MERCADOLIBRE"] if parser.has_section("MERCADOLIBRE") else {}
    extras = [m.strip().upper() for m in str(sec.get("marcas", "")).split(",") if m.strip()]
    categorias = {}
    if parser.has_section("MERCADOLIBRE_CATEGORIAS"):
        categorias = {k.strip().upper(): v.strip() for k, v in parser["MERCADOLIBRE_CATEGORIAS"].items() if v.strip()}
    try:
        reserva = int(sec.get("stock_reserva", 0) or 0)
    except ValueError:
        reserva = 0
    try:
        umbral = int(sec.get("umbral_envio_gratis", UMBRAL_ENVIO_GRATIS) or UMBRAL_ENVIO_GRATIS)
    except ValueError:
        umbral = UMBRAL_ENVIO_GRATIS
    return {
        "umbral_envio_gratis": umbral,
        "carpeta_fotos_id": str(sec.get("carpeta_fotos_id", "") or "").strip(),
        "tipo_publicacion": str(sec.get("tipo_publicacion", "gold_special") or "gold_special").strip(),
        "stock_reserva": reserva,
        "marcas": list(dict.fromkeys(extras + MARCAS_BASE)),
        "categorias_por_hoja": categorias,
        "descripcion_ia": str(sec.get("descripcion_ia", "comercial") or "comercial").strip().lower(),
    }


# ── utilidades ─────────────────────────────────────────────────────────────────
def _txt(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def _txt_lineas(v) -> str:
    """Como _txt pero conserva los saltos de línea (para la descripción)."""
    lineas = [" ".join(l.split()) for l in str(v if v is not None else "").splitlines()]
    return "\n".join(lineas).strip()


def _norm(v) -> str:
    s = _txt(v).upper()
    if s.endswith(".0") and s[:-2].isdigit():
        s = s[:-2]
    return s


def _num(v):
    if v in (None, "", " - ", "-"):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("$", "").replace(" ", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    elif s.count(".") >= 1 and len(s.split(".")[-1]) == 3:
        s = s.replace(".", "")  # 12.990 → 12990
    try:
        return float(s)
    except ValueError:
        return None


def _es_si(v) -> bool:
    return v is True or _norm(v) in VALORES_SI


def calcular_recargo(valor, precio_local) -> int:
    """'1500' / '$1.500' → 1500; '5%' → 5 % del precio local; vacío o inválido → 0."""
    texto = str(valor if valor is not None else "").strip()
    if not texto:
        return 0
    if texto.endswith("%"):
        pct = _num(texto[:-1])
        return int(round((precio_local or 0) * pct / 100)) if pct else 0
    monto = _num(texto)
    return int(round(monto)) if monto and monto > 0 else 0


def normalizar_medidas(v) -> str:
    """'150 x 40 X 40' / '150*40*40' → '150x40x40'. Vacío si no son 3 números."""
    nums = re.findall(r"\d+(?:[.,]\d+)?", str(v or ""))
    if len(nums) != 3:
        return ""
    return "x".join(str(int(round(float(n.replace(",", "."))))) for n in nums)


# ── lectura de la Tabla Base ───────────────────────────────────────────────────
def leer_marcados() -> list[dict]:
    """Filas con la casilla ML marcada en cualquier pestaña de la Tabla Base."""
    from modules.servidor.google_sheet import _get_workbook

    wb = _get_workbook("workbook_table_base")
    hojas = [ws.title for ws in wb.worksheets()]
    vrs = wb.values_batch_get([f"'{h}'!A1:BZ" for h in hojas],
                              params={"valueRenderOption": "UNFORMATTED_VALUE"}).get("valueRanges", [])
    filas_ml = []
    for hoja, vr in zip(hojas, vrs):
        valores = vr.get("values", [])
        if len(valores) < FILA_ENCABEZADOS:
            continue
        cols = {}
        for i, h in enumerate(valores[FILA_ENCABEZADOS - 1]):
            cols.setdefault(_norm(h), i)
        if COL_ML not in cols or "PRODUCTO" not in cols:
            continue
        if COL_DESCRIPCION not in cols and "DESCRIPCIÓN ML" in cols:
            cols[COL_DESCRIPCION] = cols["DESCRIPCIÓN ML"]

        def celda(row, nombre):
            i = cols.get(nombre)
            return row[i] if i is not None and i < len(row) else ""

        for n, row in enumerate(valores[FILA_ENCABEZADOS:], start=FILA_ENCABEZADOS + 1):
            if not _es_si(celda(row, COL_ML)):
                continue
            filas_ml.append({
                "hoja": hoja,
                "fila": n,
                "ref": _norm(celda(row, "REF INTERNA")),
                "barcode": _norm(celda(row, "CODIGO BARRAS")),
                "producto": _txt(celda(row, "PRODUCTO")),
                "precio": _num(celda(row, "VENTA FLB")),
                "peso": _num(celda(row, COL_PESO)),
                "medidas": normalizar_medidas(celda(row, COL_MEDIDAS)),
                "recargo_txt": celda(row, COL_RECARGO),
                "tiene_col_medidas": COL_MEDIDAS in cols,
                "categoria": _norm(celda(row, COL_CATEGORIA)),
                "marca": _txt(celda(row, COL_MARCA)),
                "titulo": _txt(celda(row, COL_TITULO)),
                "descripcion": _txt_lineas(celda(row, COL_DESCRIPCION)),
                "atributos": {h[:-3].strip(): _txt(celda(row, h)) for h in cols
                              if h.endswith(" ML") and h not in COLS_ML_RESERVADAS and _txt(celda(row, h))},
                # columnas 1-based para escribir propuestas aprobadas (None si la pestaña no la tiene)
                "col_categoria": cols[COL_CATEGORIA] + 1 if COL_CATEGORIA in cols else None,
                "col_marca": cols[COL_MARCA] + 1 if COL_MARCA in cols else None,
                "col_titulo": cols[COL_TITULO] + 1 if COL_TITULO in cols else None,
                "col_descripcion": cols[COL_DESCRIPCION] + 1 if COL_DESCRIPCION in cols else None,
                "tiene_col_peso": COL_PESO in cols,
            })
    logger.info("Productos marcados con ML en la Tabla Base: %d", len(filas_ml))
    return filas_ml


# ── propuestas ─────────────────────────────────────────────────────────────────
def proponer_marca(producto: str, marcas: list[str]) -> str:
    texto = f" {producto.upper()} "
    for m in marcas:
        if re.search(rf"(?<![A-Z0-9]){re.escape(m)}(?![A-Z0-9])", texto):
            return m if len(m) <= 3 or not m.isalpha() else m.title()
    return "Genérica"


def proponer_titulo(producto: str, marca: str = "") -> str:
    s = _txt(producto)
    if "ESPUMA" in s.upper():
        s = re.sub(r"\bD\s?(\d+)\b", r"Densidad \1", s, flags=re.I)
    s = re.sub(r"(\d)\s*(CM|MM|MTS?|KGS?|GRS?|LTS?|ML)\b", r"\1 \2", s, flags=re.I)  # 2CM → 2 CM
    s = re.sub(r"\.(?=[A-Za-zÁÉÍÓÚÑáéíóúñ])", ". ", s)  # GOLI.PLAN.CORRI. → GOLI. PLAN. CORRI.
    s = re.sub(r"\./(?=\S)", ". ", s)                  # C/GOL./EPDM → C/GOL. EPDM
    palabras = []
    for tok in s.split(" "):
        clave = tok.upper()
        if clave in ABREVIATURAS:
            palabras.append(ABREVIATURAS[clave])
            continue
        # abreviaturas pegadas a la palabra siguiente, p. ej. "C/GOL."
        for abrev, largo in ABREVIATURAS.items():
            if abrev.endswith("/") and clave.startswith(abrev) and len(clave) > len(abrev):
                resto = tok[len(abrev):]
                palabras.append(largo.strip())
                tok, clave = resto, resto.upper()
                break
        if any(c.isdigit() for c in tok) or tok in UNIDADES:
            palabras.append(tok.lower() if clave in ("CM", "MM", "KG", "ML") else tok)
        elif marca and clave == marca.upper():
            palabras.append(marca)
        elif clave.lower() in PALABRAS_MINUSCULA and palabras:
            palabras.append(clave.lower())
        elif len(clave) <= 2 and clave.isalpha():
            palabras.append(clave)  # siglas cortas: NC, PU, HD…
        else:
            palabras.append(tok.capitalize())
    titulo = " ".join(p for p in palabras if p).replace("  ", " ").strip()
    if marca and marca != "Genérica" and marca.upper() not in titulo.upper():
        titulo = f"{titulo} {marca}"
    if titulo:
        titulo = titulo[0].upper() + titulo[1:]
    if len(titulo) > MAX_TITULO:
        titulo = titulo[:MAX_TITULO].rsplit(" ", 1)[0]
    return titulo


class _CacheML:
    """Cachea consultas a la API durante una carga (categorías y comisiones)."""

    def __init__(self, ml: MercadoLibreClient, tipo_publicacion: str):
        self.ml = ml
        self.tipo = tipo_publicacion
        self._categorias: dict[str, str] = {}
        self._comisiones: dict[tuple, dict] = {}
        self._envios: dict[tuple, dict] = {}
        self._atributos: dict[str, list] = {}
        self._defectos: dict[str, list] = {}
        self._uid = None

    def nombre_categoria(self, cat_id: str) -> str:
        if cat_id not in self._categorias:
            try:
                c = self.ml.get(f"/categories/{cat_id}", auth=False)
                ruta = [p["name"] for p in c.get("path_from_root", [])]
                self._categorias[cat_id] = " > ".join(ruta[-2:]) if ruta else c.get("name", "")
            except MercadoLibreError:
                self._categorias[cat_id] = ""
        return self._categorias[cat_id]

    def atributos(self, cat_id: str) -> list[dict]:
        """Datos que pide la categoría (lista de /categories/{id}/attributes); [] si falla."""
        if cat_id not in self._atributos:
            try:
                self._atributos[cat_id] = self.ml.get(f"/categories/{cat_id}/attributes", auth=False) or []
            except MercadoLibreError:
                self._atributos[cat_id] = []
        return self._atributos[cat_id]

    def por_defecto(self, cat_id: str) -> list[tuple[str, str]]:
        """Valores por defecto de la categoría en [MERCADOLIBRE_COLUMNAS] (solo los que tienen valor)."""
        if cat_id not in self._defectos:
            self._defectos[cat_id] = [(d, v) for d, v in columnas_estandar(cat_id) if v]
        return self._defectos[cat_id]

    def predecir(self, texto: str) -> str:
        try:
            sug = self.ml.predecir_categoria(texto, limite=1)
            return sug[0]["category_id"] if sug else ""
        except MercadoLibreError:
            return ""

    def envio(self, medidas: str, peso: float, precio: int) -> int:
        """
        Lo que Mercado Libre le descuenta a La Loba por el envío de un paquete (medidas cm, peso g).
        Se cobra en TODAS las ventas con Envíos de Mercado Libre, también bajo el umbral de envío
        gratis (ahí es una tarifa menor, aunque el comprador pague su parte). La consulta ya
        aplica la reputación y los descuentos de la cuenta.
        """
        return envio_vendedor(self.ml, medidas, peso, precio, self.tipo, cache=self._envios,
                              uid=self._uid_actual())["costo"]

    def _uid_actual(self):
        if not self._uid:
            self._uid = self.ml.usuario_actual()["id"]
        return self._uid

    def comision(self, cat_id: str, precio: int) -> dict:
        clave = (cat_id, precio)
        if clave not in self._comisiones:
            r = self.ml.get(f"/sites/{SITE_ID}/listing_prices",
                            params={"price": precio, "category_id": cat_id, "listing_type_id": self.tipo})
            self._comisiones[clave] = r
        return self._comisiones[clave]


def peso_facturable(medidas: str, peso_gr: float | None) -> tuple[float, bool] | None:
    """(kg que cobra ML, True si manda el volumétrico) para 'LxAxH' cm y peso en gramos; None si faltan."""
    nums = [float(x) for x in (medidas or "").split("x") if x]
    if len(nums) != 3 or not peso_gr:
        return None
    volumetrico = nums[0] * nums[1] * nums[2] / DIVISOR_VOLUMETRICO
    real = float(peso_gr) / 1000
    return (volumetrico, True) if volumetrico > real else (real, False)


def envio_vendedor(ml: MercadoLibreClient, medidas: str, peso: float, precio: int, tipo: str,
                   cache: dict | None = None, uid=None) -> dict:
    """
    Costo de envío para el vendedor según Mercado Libre (/users/{id}/shipping_options/free):
    {"costo": lo que se descuenta (redondeado hacia arriba), "tarifa": sin descuento,
     "descuento": tasa 0–1, "peso_cobrado_g": peso que usó ML}. Sin indicar free_shipping,
    ML responde lo que corresponde al precio: bajo el umbral la tarifa sin envío gratis,
    desde el umbral la del envío gratis obligatorio.
    """
    clave = (medidas, int(peso), int(precio), tipo)
    if cache is not None and clave in cache:
        return cache[clave]
    uid = uid or ml.usuario_actual()["id"]
    r = ml.get(f"/users/{uid}/shipping_options/free", params={
        "dimensions": f"{medidas},{int(peso)}", "item_price": int(precio), "listing_type_id": tipo,
        "mode": "me2", "condition": "new", "logistic_type": "xd_drop_off", "verbose": "true"})
    cob = r["coverage"]["all_country"]
    desc = cob.get("discount") or {}
    costo = int(math.ceil(float(cob["list_cost"]) - 1e-6))
    det = {"costo": costo, "tarifa": int(round(desc.get("promoted_amount") or costo)),
           "descuento": float(desc.get("rate") or 0), "peso_cobrado_g": cob.get("billable_weight")}
    if cache is not None:
        cache[clave] = det
    return det


def monto_comision(respuesta: dict) -> int:
    """
    Comisión NORMAL por venta (el % de la categoría, p. ej. 16 % en Cojines): viene en
    sale_fee_details.gross_amount. Es lo que se cobraría sin descuentos.
    """
    detalle = respuesta.get("sale_fee_details") or {}
    return int(round(max(respuesta.get("sale_fee_amount") or 0, detalle.get("gross_amount") or 0)))


def comision_vigente(respuesta: dict) -> int:
    """
    Comisión que Mercado Libre cobra HOY (sale_fee_amount): ya trae los descuentos de la
    cuenta. Desde nov-2026 La Loba tiene 100 % de descuento en Clásica, así que es $0
    (el simulador de costos de ML muestra lo mismo).
    """
    if respuesta.get("sale_fee_amount") is None:
        return monto_comision(respuesta)
    return int(round(respuesta.get("sale_fee_amount") or 0))


def desglose_precio(cache: _CacheML, cat_id: str, precio: int, medidas: str = "",
                    peso: float | None = None) -> dict:
    """
    Lo que pasa con una venta a `precio` en Mercado Libre, con lo que ML cobra hoy:
    {"precio", "comision" (hoy), "comision_normal", "envio" (None si faltan medidas o peso),
     "recibe" (con la comisión de hoy), "recibe_normal" (si ML cobrara la comisión normal)}.
    """
    r = cache.comision(cat_id, int(precio))
    envio = cache.envio(medidas, peso, int(precio)) if (medidas and peso) else None
    hoy, normal = comision_vigente(r), monto_comision(r)
    return {"precio": int(precio), "comision": hoy, "comision_normal": normal, "envio": envio,
            "recibe": int(precio) - hoy - (envio or 0), "recibe_normal": int(precio) - normal - (envio or 0)}


def precio_para_recibir(cache: _CacheML, objetivo: float, cat_id: str, medidas: str = "",
                        peso: float | None = None, comision_normal: bool = False) -> dict:
    """
    Precio en ML (terminado en 90) para recibir al menos `objetivo` después de la comisión
    (la de hoy, o la normal si comision_normal) y del envío. Devuelve desglose_precio().
    """
    def neto(d):
        return d["recibe_normal"] if comision_normal else d["recibe"]

    p = float(objetivo)
    for _ in range(8):  # punto fijo: comisión y envío dependen del precio
        d = desglose_precio(cache, cat_id, max(int(round(p)), 1), medidas, peso)
        nuevo = objetivo + (d["precio"] - neto(d))
        if abs(nuevo - p) < 1:
            break
        p = nuevo
    precio = _redondear(p)
    for _ in range(40):  # por si el redondeo cambió de tramo (comisión o envío)
        d = desglose_precio(cache, cat_id, precio, medidas, peso)
        if neto(d) >= objetivo:
            break
        precio += 100
    # bajar si sobra (al cruzar un tramo hacia abajo el envío puede ser menor)
    while precio > 100:
        menor = desglose_precio(cache, cat_id, precio - 100, medidas, peso)
        if neto(menor) < objetivo:
            break
        precio, d = precio - 100, menor
    return d


def _redondear(p: float) -> int:
    return int(math.ceil((p + 10) / 100.0) * 100 - 10)  # terminación 90


def calcular_precio_ml(cache: _CacheML, precio_local: float, cat_id: str, medidas: str = "",
                       peso: float | None = None, umbral: int = UMBRAL_ENVIO_GRATIS) -> tuple[int, int, int | None]:
    """
    Precio ML automático: lo justo para que, descontadas la comisión que Mercado Libre cobra
    HOY y el costo de envío (se cobra en todas las ventas, también bajo el umbral), La Loba
    reciba al menos PRECIO LOCAL. Devuelve (precio_ml, comision_hoy, envio); envio es None
    si faltan medidas o peso. `umbral` queda por compatibilidad: ML ya aplica la tarifa de
    cada precio. Para elegir otro precio está la calculadora de la vista previa.
    """
    d = precio_para_recibir(cache, precio_local, cat_id, medidas, peso)
    return d["precio"], d["comision"], d["envio"]


# ── fotos y stock ──────────────────────────────────────────────────────────────
def contar_fotos(carpeta_id: str) -> Counter:
    """{REF: cantidad de fotos} según los nombres REF-1.jpg, REF-2.png… de la carpeta."""
    conteo = Counter()
    if not carpeta_id:
        return conteo
    from modules.servidor.google_sheet import drive_service

    token = None
    while True:
        r = drive_service.files().list(
            q=f"'{carpeta_id}' in parents and trashed = false and mimeType contains 'image/'",
            fields="nextPageToken, files(name)", pageSize=1000, pageToken=token,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        for f in r.get("files", []):
            m = re.match(r"^(.+)-(\d+)\.[A-Za-z0-9]+$", f["name"].strip())
            if m:
                conteo[_norm(m.group(1))] += 1
        token = r.get("nextPageToken")
        if not token:
            return conteo


def stock_odoo(refs: list[str]) -> dict:
    """{REF: (product_id, qty_available)} desde Odoo por referencia interna."""
    from modules.servidor.odoo import OdooService

    refs = sorted({r for r in refs if r})
    if not refs:
        return {}
    res = {}
    for p in OdooService.get_productos_odoo_by_refs(refs):
        res.setdefault(_norm(p.get("default_code")), (p["id"], p.get("qty_available") or 0))
    return res


# ── armado del catálogo ────────────────────────────────────────────────────────
def construir_catalogo() -> tuple[list[dict], list[str]]:
    """
    Devuelve (productos, avisos). Cada producto es un dict con los campos de ProductoML.
    """
    cfg = config_ml()
    avisos = []
    filas = leer_marcados()
    if not filas:
        return [], ["No hay productos con la casilla ML marcada en la Tabla Base."]

    ml = MercadoLibreClient()
    cache = _CacheML(ml, cfg["tipo_publicacion"])
    try:
        fotos = contar_fotos(cfg["carpeta_fotos_id"])
    except Exception as e:  # carpeta no compartida, id mal escrito…
        logger.error("No se pudo leer la carpeta de fotos: %s", e, exc_info=True)
        fotos = Counter()
        avisos.append("No se pudo leer la carpeta de fotos de Drive (¿está compartida con la cuenta del sincronizador?).")
    if not cfg["carpeta_fotos_id"]:
        avisos.append("Falta configurar la carpeta de fotos (carpeta_fotos_id en [MERCADOLIBRE]).")
    try:
        stock = stock_odoo([f["ref"] for f in filas])
    except Exception as e:
        logger.error("No se pudo leer el stock de Odoo: %s", e, exc_info=True)
        stock = {}
        avisos.append("No se pudo consultar el stock en Odoo.")

    try:
        todas_las_fichas = fichas.leer_todas()
    except Exception as e:
        logger.error("No se pudo leer la pestaña %s: %s", fichas.HOJA, e, exc_info=True)
        todas_las_fichas = {}
        avisos.append(f"No se pudo leer la pestaña {fichas.HOJA} de la Tabla Base.")

    vistos = Counter(f["ref"] for f in filas if f["ref"])
    productos = []
    for f in filas:
        pend = []
        # categoría: planilla > regla por pestaña > predictor de ML
        cat, cat_prop = f["categoria"], False
        if not cat:
            cat = cfg["categorias_por_hoja"].get(f["hoja"].strip().upper(), "")
            if not cat:
                marca_tmp = f["marca"] or proponer_marca(f["producto"], cfg["marcas"])
                cat = cache.predecir(f["titulo"] or proponer_titulo(f["producto"], marca_tmp))
            cat_prop = bool(cat)
        marca, marca_prop = f["marca"], False
        if not marca:
            marca, marca_prop = proponer_marca(f["producto"], cfg["marcas"]), True
        titulo, titulo_prop = f["titulo"], False
        if not titulo:
            titulo, titulo_prop = proponer_titulo(f["producto"], marca), True

        precio_ml = comision = comision_normal = envio = 0
        ficha, precio_fijo = fichas.separar_precio(todas_las_fichas.get(f["ref"], {}))
        recargo = calcular_recargo(f.get("recargo_txt"), f["precio"])
        if not f["precio"]:
            pend.append("sin VENTA FLB")
        elif cat:
            try:
                if precio_fijo:  # lo eligió el usuario con la calculadora
                    d = desglose_precio(cache, cat, precio_fijo, f["medidas"], f["peso"])
                else:
                    d = precio_para_recibir(cache, f["precio"] + recargo, cat, f["medidas"], f["peso"])
                precio_ml, comision, comision_normal, envio = d["precio"], d["comision"], d["comision_normal"], d["envio"]
                if envio is None:
                    envio = 0
                    if not f["medidas"]:
                        pend.append("sin MEDIDAS PAQUETE (costo de envío no incluido en el precio)"
                                    if f["tiene_col_medidas"] else
                                    "la hoja no tiene columna MEDIDAS PAQUETE (costo de envío no incluido en el precio)")
            except (MercadoLibreError, KeyError) as e:
                pend.append("categoría inválida")
                logger.warning("No se pudo calcular precio ML de %s (%s): %s", f["ref"], cat, e)
        if not cat:
            pend.append("sin categoría")
        if not f["tiene_col_peso"]:
            pend.append("la hoja no tiene columna PESO GR")
        elif not f["peso"]:
            pend.append("sin peso")
        n_fotos = fotos.get(f["ref"], 0) if f["ref"] else 0
        if not n_fotos:
            pend.append("sin fotos")
        if not f["ref"]:
            pend.append("sin REF INTERNA")
        odoo = stock.get(f["ref"])
        if f["ref"] and not odoo:
            pend.append("no existe en Odoo")
        if f["ref"] and vistos[f["ref"]] > 1:
            pend.append("REF marcada en varias hojas")
        if titulo and len(titulo) > MAX_TITULO:
            pend.append(f"título > {MAX_TITULO} caracteres")
        sin_col = [n for n, c in ((COL_CATEGORIA, f["col_categoria"]), (COL_MARCA, f["col_marca"]),
                                  (COL_TITULO, f["col_titulo"])) if c is None]
        if sin_col:
            pend.append("la hoja no tiene columna " + ", ".join(sin_col))

        # datos de la categoría: columnas "<DATO> ML" > FICHAS ML > valores por defecto
        atributos, origen = fichas.combinar(f["atributos"], ficha,
                                            cache.por_defecto(cat) if cat else [])
        if cat:
            faltan_datos = datos_obligatorios_faltantes(cache.atributos(cat), atributos, f, marca, cfg)
            if faltan_datos:
                pend.append(PREFIJO_FALTAN_DATOS + ", ".join(faltan_datos))

        cantidad = (odoo[1] if odoo else 0) - cfg["stock_reserva"]
        if pend:
            estado = ESTADO_FALTAN
        elif cantidad <= 0:
            estado = ESTADO_SIN_STOCK
        elif cat_prop or marca_prop or titulo_prop:
            estado = ESTADO_REVISAR
        else:
            estado = ESTADO_LISTO

        productos.append({
            "estado": estado,
            "pendientes": ", ".join(pend)[:255],
            "hoja": f["hoja"][:150],
            "fila": f["fila"],
            "ref_interna": f["ref"],
            "barcode": f["barcode"],
            "producto": f["producto"][:255],
            "precio_local": int(round(f["precio"] or 0)),
            "recargo_ml": recargo,
            "precio_ml": precio_ml,
            "precio_ml_fijo": bool(precio_fijo and precio_ml),
            "comision": comision,
            "comision_normal": comision_normal,
            "stock": int(odoo[1]) if odoo else None,
            "peso_gr": int(f["peso"]) if f["peso"] else None,
            "medidas_paquete": f["medidas"],
            "envio": envio or 0,
            "fotos": n_fotos,
            "categoria_id": cat,
            "categoria_nombre": cache.nombre_categoria(cat) if cat else "",
            "categoria_propuesta": cat_prop,
            "marca": marca[:100],
            "marca_propuesta": marca_prop,
            "titulo": titulo[:255],
            "titulo_propuesta": titulo_prop,
            "descripcion": f["descripcion"],
            "col_categoria": f["col_categoria"],
            "col_marca": f["col_marca"],
            "col_titulo": f["col_titulo"],
            "col_descripcion": f["col_descripcion"],
            "atributos_ml": json.dumps(atributos, ensure_ascii=False),
            "atributos_origen": json.dumps(origen, ensure_ascii=False),
            "odoo_id": odoo[0] if odoo else None,
        })
    if vincular_publicaciones(ml, productos):
        avisos.append("No se pudo revisar en Mercado Libre qué productos ya están publicados.")
    return productos, avisos


def datos_obligatorios_faltantes(atributos_cat: list[dict], valores: dict, fila: dict, marca: str,
                                 cfg: dict) -> list[str]:
    """Nombres de los datos obligatorios de la categoría que no se sabe completar
    (los mismos que mostraría la simulación), para avisar antes de simular."""
    if not atributos_cat:
        return []
    from types import SimpleNamespace
    from modules.mercadolibre.publicador import armar_item

    p = SimpleNamespace(
        marca=marca, ref_interna=fila["ref"], barcode=fila["barcode"], titulo="", categoria_id="",
        precio_ml=0, stock=0, peso_gr=int(fila["peso"]) if fila["peso"] else None,
        medidas_paquete=fila["medidas"], atributos_ml=json.dumps(valores, ensure_ascii=False))
    _, faltantes, _ = armar_item(p, [], atributos_cat, cfg)
    return faltantes


PREFIJO_FALTAN_DATOS = "faltan datos ML: "


def aplicar_ficha(p, ficha: dict[str, str], atributos_cat: list[dict]) -> list[str]:
    """Después de guardar la ficha de p (ProductoML) en FICHAS ML, recalcula sus datos,
    los obligatorios que faltan y el estado, sin volver a cargar toda la Tabla Base.
    No guarda en la base: eso lo hace quien llama. Devuelve los datos que siguen faltando."""
    cfg = config_ml()
    origen = p.origen_datos_ml
    planilla = {d: v for d, v in p.datos_ml.items() if origen.get(d) == "planilla"}
    defectos = [(d, v) for d, v in columnas_estandar(p.categoria_id) if v] if p.categoria_id else []
    valores, origen = fichas.combinar(planilla, ficha, defectos)
    p.atributos_ml = json.dumps(valores, ensure_ascii=False)
    p.atributos_origen = json.dumps(origen, ensure_ascii=False)

    fila = {"ref": p.ref_interna, "barcode": p.barcode, "peso": p.peso_gr, "medidas": p.medidas_paquete}
    faltan = datos_obligatorios_faltantes(atributos_cat, valores, fila, p.marca, cfg) if p.categoria_id else []
    # "faltan datos ML: …" es siempre lo último de los pendientes (ver construir_catalogo)
    previos = (p.pendientes or "").split(PREFIJO_FALTAN_DATOS)[0]
    pend = [x.strip() for x in previos.split(", ") if x.strip()]
    if faltan:
        pend.append(PREFIJO_FALTAN_DATOS + ", ".join(faltan))
    p.pendientes = ", ".join(pend)[:255]
    if p.estado in (ESTADO_FALTAN, ESTADO_LISTO, ESTADO_REVISAR, ESTADO_SIN_STOCK):
        cantidad = (p.stock or 0) - cfg["stock_reserva"]
        if pend:
            p.estado = ESTADO_FALTAN
        elif cantidad <= 0:
            p.estado = ESTADO_SIN_STOCK
        elif p.categoria_propuesta or p.marca_propuesta or p.titulo_propuesta:
            p.estado = ESTADO_REVISAR
        else:
            p.estado = ESTADO_LISTO
    return faltan


def vincular_publicaciones(ml: MercadoLibreClient, productos: list[dict]) -> int:
    """
    Busca en Mercado Libre la publicación de cada producto por SKU (= REF INTERNA) y
    completa ml_item_id / ml_estado / ml_link. Si está publicado, el estado de la fila
    pasa a Publicado / Pausado / En revisión. Devuelve cuántas búsquedas fallaron.
    """
    from modules.mercadolibre.publicador import ESTADOS_ML, publicacion_vigente

    por_estado = {"active": ESTADO_PUBLICADO, "paused": ESTADO_PAUSADO, "under_review": ESTADO_EN_REVISION}
    fallas = 0
    for p in productos:
        p.setdefault("ml_item_id", ""); p.setdefault("ml_estado", ""); p.setdefault("ml_link", "")
        if not p.get("ref_interna"):
            continue
        try:
            pub = publicacion_vigente(ml, p["ref_interna"])
        except Exception as e:
            fallas += 1
            logger.warning("No se pudo buscar la publicación de %s: %s", p["ref_interna"], e)
            continue
        if pub:
            p["ml_item_id"] = pub["id"]
            p["ml_estado"] = ESTADOS_ML.get(pub.get("status"), pub.get("status") or "")
            p["ml_link"] = pub.get("permalink") or ""
            p["estado"] = por_estado.get(pub.get("status"), p["estado"])
    return fallas


def cambios_por_aprobar(productos) -> list[tuple]:
    """
    Celdas a escribir en la planilla para aprobar las propuestas de los productos dados.
    Devuelve [(hoja, fila, columna, valor)]; solo celdas que hoy están vacías (propuestas).
    """
    cambios = []
    for p in productos:
        for propuesta, col, valor in ((p.categoria_propuesta, p.col_categoria, p.categoria_id),
                                      (p.marca_propuesta, p.col_marca, p.marca),
                                      (p.titulo_propuesta, p.col_titulo, p.titulo),
                                      (p.descripcion_propuesta, p.col_descripcion, p.descripcion)):
            if propuesta and col and valor:
                cambios.append((p.hoja, p.fila, col, valor))
    return cambios


def conservar_descripciones(productos: list[dict], previas: dict) -> int:
    """
    Al recargar la tabla se pierden las descripciones propuestas por IA que aún no se
    aprobaron. `previas` es {(hoja, ref): descripción} de antes de recargar; se reponen
    solo donde la planilla sigue sin descripción. Devuelve cuántas se repusieron.
    """
    repuestas = 0
    for p in productos:
        previa = previas.get((p["hoja"], p["ref_interna"]))
        if previa and not p["descripcion"]:
            p["descripcion"], p["descripcion_propuesta"] = previa, True
            if p["estado"] == ESTADO_LISTO:
                p["estado"] = ESTADO_REVISAR
            repuestas += 1
    return repuestas


# ── set estándar de columnas por categoría ────────────────────────────────────
def columnas_estandar(categoria_id: str) -> list[tuple[str, str]]:
    """[(dato, valor_por_defecto)] de [MERCADOLIBRE_COLUMNAS] para la categoría ('' = sin valor por defecto)."""
    parser = configparser.ConfigParser()
    parser.optionxform = str
    carpeta_datos.leer_ini(parser, str(carpeta_datos.ruta("server_settings.cfg")))
    if not parser.has_section("MERCADOLIBRE_COLUMNAS"):
        return []
    linea = next((v for k, v in parser["MERCADOLIBRE_COLUMNAS"].items() if k.strip().upper() == categoria_id.upper()), "")
    columnas = []
    for parte in linea.split(","):
        if parte.strip():
            dato, _, defecto = parte.partition("=")
            columnas.append((dato.strip(), defecto.strip()))
    return columnas


def preparar_columnas(hoja: str, categoria_id: str | None = None, filas_extra: int = 300) -> dict:
    """
    Agrega a la pestaña las columnas "<DATO> ML" del set estándar de la categoría que todavía no
    tiene, a la derecha de la última columna. Pone listas desplegables con las opciones de ML,
    una nota con la unidad en las medidas, y el valor por defecto solo en celdas vacías de las
    filas de esa categoría. No toca ninguna otra celda.
    """
    from gspread.utils import rowcol_to_a1
    from modules.mercadolibre.publicador import normalizar_nombre
    from modules.servidor.google_sheet import _get_workbook

    ws = _get_workbook("workbook_table_base").worksheet(hoja)
    valores = ws.get(f"A{FILA_ENCABEZADOS}:BZ", value_render_option="UNFORMATTED_VALUE")
    encabezados = [_norm(h) for h in valores[0]] if valores else []
    filas = valores[1:]
    i_cat = encabezados.index(COL_CATEGORIA) if COL_CATEGORIA in encabezados else None
    if not categoria_id:
        cats = Counter(_norm(r[i_cat]) for r in filas if i_cat is not None and len(r) > i_cat and _norm(r[i_cat]))
        categoria_id = cats.most_common(1)[0][0] if cats else ""
    estandar = columnas_estandar(categoria_id)
    if not estandar:
        return {"categoria": categoria_id, "agregadas": [], "existentes": [],
                "error": f"No hay set estándar para {categoria_id} en [MERCADOLIBRE_COLUMNAS]."}

    atributos = MercadoLibreClient().get(f"/categories/{categoria_id}/attributes", auth=False)
    por_nombre = {normalizar_nombre(a["name"]): a for a in atributos}
    ultima = max((i for i, h in enumerate(encabezados) if h), default=-1) + 1  # 0-based → siguiente libre
    ultima_fila = FILA_ENCABEZADOS + max((i for i, r in enumerate(filas, start=1) if any(str(c).strip() for c in r)), default=0)
    hasta = ultima_fila + filas_extra
    existentes_norm = {normalizar_nombre(h[:-3]) for h in encabezados if h.endswith(" ML")}

    agregadas, existentes, desconocidas, celdas, reqs = [], [], [], [], []
    sid = ws.id
    for dato, defecto in estandar:
        if normalizar_nombre(dato) in existentes_norm:
            existentes.append(dato)
            continue
        a = por_nombre.get(normalizar_nombre(dato))
        if not a:
            desconocidas.append(dato)
            continue
        col = ultima + len(agregadas)          # 0-based
        encabezado = f"{normalizar_nombre(dato)} ML"
        celdas.append({"range": rowcol_to_a1(FILA_ENCABEZADOS, col + 1), "values": [[encabezado]]})
        opciones = [o["name"] for o in (a.get("values") or [])]
        if opciones and a.get("value_type") in ("list", "string", "boolean"):
            reqs.append({"setDataValidation": {
                "range": {"sheetId": sid, "startRowIndex": FILA_ENCABEZADOS, "endRowIndex": hasta,
                          "startColumnIndex": col, "endColumnIndex": col + 1},
                "rule": {"condition": {"type": "ONE_OF_LIST", "values": [{"userEnteredValue": o} for o in opciones[:500]]},
                         "showCustomUi": True, "strict": a.get("value_type") != "string"}}})
        unidades = [u["id"] for u in a.get("allowed_units") or []]
        nota = f"{a['name']} ({a['id']}) en Mercado Libre."
        if unidades:
            nota += f" Número en {unidades[0]} (ej. 190); también se acepta '190 {unidades[0]}'."
        elif opciones:
            nota += " Elige una opción de la lista."
        reqs.append({"updateCells": {"range": {"sheetId": sid, "startRowIndex": FILA_ENCABEZADOS - 1,
                                               "endRowIndex": FILA_ENCABEZADOS, "startColumnIndex": col,
                                               "endColumnIndex": col + 1},
                                     "rows": [{"values": [{"note": nota}]}], "fields": "note"}})
        if defecto and i_cat is not None:
            for n, r in enumerate(filas, start=FILA_ENCABEZADOS + 1):
                if len(r) > i_cat and _norm(r[i_cat]) == categoria_id.upper():
                    celdas.append({"range": rowcol_to_a1(n, col + 1), "values": [[defecto]]})
        agregadas.append(encabezado)

    if agregadas:
        if ultima + len(agregadas) > ws.col_count:
            ws.add_cols(ultima + len(agregadas) - ws.col_count)
        ws.batch_update(celdas, value_input_option="RAW")
        if reqs:
            ws.spreadsheet.batch_update({"requests": reqs})
    logger.info("Columnas ML en '%s' (%s): agregadas %s, ya existían %s", hoja, categoria_id, agregadas, existentes)
    return {"categoria": categoria_id, "agregadas": agregadas, "existentes": existentes,
            "desconocidas": desconocidas, "error": None}
