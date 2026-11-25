"""
Fichas ML: los datos de la categoría de Mercado Libre de cada producto
(Material del relleno, Forma, Cantidad de envases…) en una sola pestaña de la
Tabla Base, en vez de una columna "<DATO> ML" por dato en cada pestaña de
proveedor.

La pestaña FICHAS ML la escribe el Gestor (formulario "Datos para Mercado
Libre" de la vista previa). Es compartida: la ven todos los PC y el servidor.
Se puede leer y corregir a mano, una fila por dato:

    REF INTERNA | DATO                  | VALOR      | ORIGEN      | ACTUALIZADO
    ALG0001     | Material del relleno  | Poliéster  | manual      | 2026-11-25 18:40
    ALG0001     | Cantidad de envases   | 1          | por defecto | 2026-11-25 18:40

Orden de prioridad al publicar (ver catalogo.construir_catalogo):
  1. columnas "<DATO> ML" de la pestaña del proveedor (compatibilidad: si están, mandan)
  2. FICHAS ML
  3. valor por defecto de la categoría en [MERCADOLIBRE_COLUMNAS] de server_settings.cfg
"""
from __future__ import annotations

from datetime import datetime

from logger_config import get_logger

logger = get_logger(__name__)

HOJA = "FICHAS ML"
ENCABEZADOS = ["REF INTERNA", "DATO", "VALOR", "ORIGEN", "ACTUALIZADO"]
ORIGEN_MANUAL = "manual"
ORIGEN_DEFECTO = "por defecto"


def _clave(texto: str) -> str:
    """Nombre de dato normalizado (sin tildes, mayúsculas): 'Material del relleno' = 'MATERIAL DEL RELLENO'."""
    from modules.mercadolibre.publicador import normalizar_nombre
    return normalizar_nombre(texto)


def _hoja(crear: bool = False):
    """La pestaña FICHAS ML de la Tabla Base (None si no existe y crear=False)."""
    import gspread
    from modules.servidor.google_sheet import _get_workbook

    wb = _get_workbook("workbook_table_base")
    try:
        return wb.worksheet(HOJA)
    except gspread.WorksheetNotFound:
        if not crear:
            return None
    ws = wb.add_worksheet(title=HOJA, rows=500, cols=len(ENCABEZADOS))
    ws.update(range_name="A1", values=[ENCABEZADOS], value_input_option="RAW")
    try:
        ws.freeze(rows=1)
    except Exception:  # solo estética
        pass
    logger.info("Pestaña %s creada en la Tabla Base.", HOJA)
    return ws


def _filas(ws) -> list[list[str]]:
    valores = ws.get_all_values() if ws else []
    return [(f + [""] * len(ENCABEZADOS))[:len(ENCABEZADOS)] for f in valores[1:] if any(c.strip() for c in f)]


def leer_todas() -> dict[str, dict[str, str]]:
    """{REF: {dato: valor}} de toda la pestaña (vacío si todavía no existe)."""
    from modules.servidor.google_sheet import _reintentar_si_se_corta

    fichas: dict[str, dict[str, str]] = {}
    for ref, dato, valor, *_ in _reintentar_si_se_corta(lambda: _filas(_hoja())):
        ref, dato, valor = ref.strip().upper(), dato.strip(), valor.strip()
        if ref and dato and valor:
            fichas.setdefault(ref, {})[dato] = valor
    return fichas


def guardar(ref: str, valores: dict[str, str], origenes: dict[str, str] | None = None) -> int:
    """Reemplaza la ficha de un producto por `valores` ({dato: valor}; los vacíos se borran).

    Las filas de los otros productos no se tocan. Devuelve cuántos datos quedaron.
    """
    from modules.servidor.google_sheet import _reintentar_si_se_corta

    ref = ref.strip().upper()
    if not ref:
        raise ValueError("El producto no tiene REF INTERNA.")
    origenes = origenes or {}
    ahora = datetime.now().strftime("%Y-%m-%d %H:%M")
    nuevas = [[ref, dato, str(valor).strip(), origenes.get(dato, ORIGEN_MANUAL), ahora]
              for dato, valor in valores.items() if str(valor).strip()]

    def escribir():
        ws = _hoja(crear=True)
        otras = [f for f in _filas(ws) if f[0].strip().upper() != ref]
        filas = sorted(otras + nuevas, key=lambda f: (f[0].strip().upper(), _clave(f[1])))
        if len(filas) + 1 > ws.row_count:
            ws.add_rows(len(filas) + 1 - ws.row_count + 100)
        ws.update(range_name="A1", values=[ENCABEZADOS] + filas, value_input_option="RAW")
        ws.batch_clear([f"A{len(filas) + 2}:E"])

    _reintentar_si_se_corta(escribir)
    logger.info("Ficha ML de %s guardada en %s: %d datos.", ref, HOJA, len(nuevas))
    return len(nuevas)


def combinar(planilla: dict[str, str], ficha: dict[str, str],
             por_defecto: list[tuple[str, str]]) -> tuple[dict[str, str], dict[str, str]]:
    """Une las tres fuentes de datos de un producto.

    Devuelve (valores, origen) con origen[dato] = "planilla" | "ficha" | "por defecto".
    Un mismo dato escrito distinto ('MATERIAL DEL RELLENO' en la columna, 'Material del
    relleno' en la ficha) cuenta como uno solo y gana la fuente de mayor prioridad.
    """
    valores: dict[str, str] = {}
    origen: dict[str, str] = {}
    vistos: set[str] = set()
    for fuente, datos in (("planilla", planilla.items()), ("ficha", ficha.items()),
                          (ORIGEN_DEFECTO, por_defecto)):
        for dato, valor in datos:
            if not str(valor).strip() or _clave(dato) in vistos:
                continue
            vistos.add(_clave(dato))
            valores[dato] = str(valor).strip()
            origen[dato] = fuente
    return valores, origen
