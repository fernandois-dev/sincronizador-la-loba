"""
Formulario "Datos para Mercado Libre" de la vista previa.

Muestra los datos que pide la categoría (los obligatorios, los del set estándar
de [MERCADOLIBRE_COLUMNAS] y los que ya tienen valor), con las opciones que
acepta Mercado Libre, y los guarda en la pestaña FICHAS ML de la Tabla Base
(modules/mercadolibre/fichas.py). Así no hace falta crear una columna
"<DATO> ML" por cada dato en cada pestaña de proveedor.

Los datos que vienen de una columna "<DATO> ML" de la pestaña del proveedor se
muestran bloqueados: la planilla manda (para cambiarlos, cambiar la celda o
borrar la columna).
"""
from __future__ import annotations

import asyncio

import flet as ft

from logger_config import get_logger
from modules.mercadolibre import catalogo, fichas
from modules.mercadolibre.publicador import normalizar_nombre

logger = get_logger(__name__)

# Datos que el Gestor completa solo (marca, SKU, código de barras, paquete…): no se piden.
AUTOMATICOS = {
    "BRAND", "SELLER_SKU", "GTIN", "EMPTY_GTIN_REASON", "MODEL", "ITEM_CONDITION",
    "SELLER_PACKAGE_WEIGHT", "SELLER_PACKAGE_LENGTH", "SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_HEIGHT",
    "SELLER_PACKAGE_TYPE",
}


def _tags(a: dict) -> dict:
    return a.get("tags") or {}


def obligatorio(a: dict) -> bool:
    t = _tags(a)
    return bool(t.get("required") or t.get("catalog_required"))


def condicional(a: dict) -> bool:
    return bool(_tags(a).get("conditional_required"))


def visible(a: dict) -> bool:
    t = _tags(a)
    return a.get("id") not in AUTOMATICOS and not (t.get("hidden") or t.get("read_only") or t.get("fixed"))


def datos_a_mostrar(atributos_cat: list[dict], valores: dict, estandar: list[str]) -> tuple[list[dict], list[dict]]:
    """(principales, opcionales): los principales son obligatorios, condicionales, del set
    estándar o con valor; los opcionales, el resto de lo que se puede completar."""
    con_valor = {normalizar_nombre(d) for d in valores}
    std = {normalizar_nombre(d) for d in estandar}
    principales, opcionales = [], []
    for a in atributos_cat:
        if not visible(a):
            continue
        nombre = normalizar_nombre(a.get("name", ""))
        if (obligatorio(a) or condicional(a) or nombre in std or nombre in con_valor
                or normalizar_nombre(a["id"]) in con_valor):
            principales.append(a)
        else:
            opcionales.append(a)
    # obligatorios primero
    principales.sort(key=lambda a: (not obligatorio(a), not condicional(a)))
    return principales, opcionales


class FormularioDatosML:
    """Tarjeta con el formulario. `tarjeta(titulo, icono, controles)` es el contenedor
    con el estilo de la vista previa; `al_guardar(faltan)` se llama después de guardar."""

    def __init__(self, page: ft.Page, p, atributos_cat: list[dict], tarjeta, al_guardar=None):
        self.page = page
        self.p = p
        self.atributos_cat = atributos_cat or []
        self.al_guardar = al_guardar
        self.valores = p.datos_ml
        self.origen = p.origen_datos_ml
        self._por_clave = {normalizar_nombre(d): d for d in self.valores}
        self.estandar = [d for d, _ in catalogo.columnas_estandar(p.categoria_id)] if p.categoria_id else []
        self.defectos = {normalizar_nombre(d): v for d, v in catalogo.columnas_estandar(p.categoria_id) if v} \
            if p.categoria_id else {}
        self.campos: dict[str, ft.Control] = {}      # nombre ML → control
        self.textos: dict[str, str] = {}             # texto escrito en desplegables editables
        self.estado = ft.Row([], spacing=8, visible=False)
        self.boton_guardar = ft.FilledButton("Guardar datos", icon=ft.Icons.SAVE, on_click=self._guardar)
        self.mostrar_opcionales = ft.Switch(label="Mostrar datos opcionales", value=False,
                                            on_change=self._alternar_opcionales)
        self.filas_opcionales: list[ft.Control] = []
        controles = self._controles()
        # sin `tarjeta`: columna con scroll (para usarlo dentro de una pestaña)
        self.control = (tarjeta("Datos para Mercado Libre", ft.Icons.FACT_CHECK_OUTLINED, controles) if tarjeta
                        else ft.Column(controles, spacing=10, scroll=ft.ScrollMode.AUTO))

    # ── armado ──
    def _valor_actual(self, a: dict) -> tuple[str, str]:
        """(valor, origen) del dato: lo guardado o, si no hay, el valor por defecto de la categoría."""
        for clave in (normalizar_nombre(a.get("name", "")), normalizar_nombre(a["id"])):
            dato = self._por_clave.get(clave)
            if dato is not None:
                return self.valores[dato], self.origen.get(dato, "ficha")
        defecto = self.defectos.get(normalizar_nombre(a.get("name", "")))
        return (defecto, fichas.ORIGEN_DEFECTO) if defecto else ("", "")

    def _campo(self, a: dict, valor: str, bloqueado: bool, ayuda: str | None = None) -> ft.Control:
        nombre = a.get("name", a["id"])
        opciones = [o.get("name", "") for o in (a.get("values") or []) if o.get("name")]
        tipo = a.get("value_type")
        unidades = [u["id"] for u in a.get("allowed_units") or []]
        if opciones and tipo in ("list", "boolean", "string"):
            libre = tipo == "string"   # admite texto propio además de la lista
            if valor and valor not in opciones:
                opciones = [valor] + opciones
            campo = ft.Dropdown(
                value=valor or None, options=[ft.DropdownOption(o) for o in opciones], dense=True,
                text_size=13, width=320, menu_height=320, editable=True, enable_filter=True,
                hint_text="Escribe o elige" if libre else "Elige una opción", disabled=bloqueado,
                helper_text=ayuda)
            if libre:
                self.textos[nombre] = valor

                def al_escribir(e, nombre=nombre):
                    self.textos[nombre] = e.control.text if hasattr(e.control, "text") else (e.data or "")
                campo.on_text_change = al_escribir
        else:
            sufijo = unidades[0] if unidades else None
            campo = ft.TextField(value=valor, dense=True, text_size=13, width=320, disabled=bloqueado,
                                 helper=ayuda,
                                 suffix=sufijo,
                                 hint_text=f"Número en {sufijo}" if sufijo else
                                 ("Número" if tipo == "number" else None))
        self.campos[nombre] = campo
        return campo

    def _fila(self, a: dict) -> ft.Control:
        valor, origen = self._valor_actual(a)
        bloqueado = origen == "planilla"
        if origen == "planilla":
            ayuda = f"Desde la columna {normalizar_nombre(a.get('name', ''))} ML de la planilla"
        elif origen == fichas.ORIGEN_DEFECTO:
            ayuda = "Valor por defecto de la categoría"
        else:
            ayuda = None
        nombre = ft.Text(spans=[
            ft.TextSpan(a.get("name", a["id"])),
            *([ft.TextSpan(" *", style=ft.TextStyle(color=ft.Colors.RED_700, weight=ft.FontWeight.BOLD))]
              if obligatorio(a) else
              [ft.TextSpan(" *", style=ft.TextStyle(color=ft.Colors.AMBER_800, weight=ft.FontWeight.BOLD))]
              if condicional(a) else []),
        ], size=13, weight=ft.FontWeight.W_500)
        return ft.Row([ft.Container(nombre, width=200, padding=ft.Padding.only(top=10)),
                       self._campo(a, valor, bloqueado, ayuda)],
                      spacing=12, vertical_alignment=ft.CrossAxisAlignment.START)

    def _controles(self) -> list[ft.Control]:
        if not self.p.categoria_id:
            return [ft.Text("Elige primero la categoría (columna CATEGORIA ML).", size=12)]
        if not self.atributos_cat:
            return [ft.Text("No se pudieron leer los datos de la categoría en Mercado Libre.", size=12,
                            color=ft.Colors.RED_700)]
        principales, opcionales = datos_a_mostrar(self.atributos_cat, self.valores, self.estandar)
        filas = [self._fila(a) for a in principales]
        self.filas_opcionales = [self._fila(a) for a in opcionales]
        for f in self.filas_opcionales:
            f.visible = False
        tenue = ft.Colors.ON_SURFACE_VARIANT
        leyenda = ft.Text(spans=[
            ft.TextSpan("*", style=ft.TextStyle(color=ft.Colors.RED_700, weight=ft.FontWeight.BOLD)),
            ft.TextSpan(" obligatorio   "),
            ft.TextSpan("*", style=ft.TextStyle(color=ft.Colors.AMBER_800, weight=ft.FontWeight.BOLD)),
            ft.TextSpan(" puede ser obligatorio según otros datos"),
        ], size=11, color=tenue)
        nota = ft.Text("Se guardan en la pestaña FICHAS ML de la Tabla Base, compartida entre los PC.",
                       size=11, color=tenue)
        return [
            leyenda,
            *(filas or [ft.Text("Esta categoría no pide datos adicionales.", size=12)]),
            *([self.mostrar_opcionales] if self.filas_opcionales else []),
            *self.filas_opcionales,
            ft.Row([self.boton_guardar, self.estado], spacing=12, wrap=True,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            nota,
        ]

    # ── acciones ──
    def _alternar_opcionales(self, e=None):
        for f in self.filas_opcionales:
            f.visible = bool(self.mostrar_opcionales.value)
        self.page.update()

    def valores_formulario(self) -> tuple[dict[str, str], dict[str, str]]:
        """(ficha, origenes) a guardar: lo escrito en el formulario, sin lo que viene de la
        planilla y sin los valores por defecto que no se cambiaron (esos se aplican solos)."""
        ficha, origenes = {}, {}
        for a in self.atributos_cat:
            nombre = a.get("name", a["id"])
            campo = self.campos.get(nombre)
            if campo is None or campo.disabled:
                continue
            valor = (campo.value or "").strip() if campo.value is not None else ""
            if not valor and nombre in self.textos:
                valor = (self.textos.get(nombre) or "").strip()
            if not valor:
                continue
            if self.defectos.get(normalizar_nombre(nombre)) == valor:
                continue
            ficha[nombre] = valor
            origenes[nombre] = fichas.ORIGEN_MANUAL
        return ficha, origenes

    def _avisar(self, texto, color=None, icono=None, cargando=False):
        self.estado.controls = [
            ft.ProgressRing(width=16, height=16, stroke_width=2) if cargando
            else ft.Icon(icono or ft.Icons.INFO_OUTLINE, size=16, color=color),
            ft.Text(texto, size=12, color=color, expand=True, selectable=True),
        ]
        self.estado.visible = True
        self.page.update()

    def _guardar(self, e=None):
        self.page.run_task(self.guardar)

    async def guardar(self):
        ficha, origenes = self.valores_formulario()
        self.boton_guardar.disabled = True
        self._avisar("Guardando en FICHAS ML…", cargando=True)
        try:
            await asyncio.to_thread(fichas.guardar, self.p.ref_interna, ficha, origenes)
            faltan = catalogo.aplicar_ficha(self.p, ficha, self.atributos_cat)
            await asyncio.to_thread(self.p.save)
        except Exception as ex:
            logger.error("No se pudo guardar la ficha ML de %s", self.p.ref_interna, exc_info=True)
            self.boton_guardar.disabled = False
            self._avisar(f"No se pudo guardar: {ex}", color=ft.Colors.RED_700, icono=ft.Icons.ERROR_OUTLINE)
            return
        self.boton_guardar.disabled = False
        if faltan:
            self._avisar("Guardado. Todavía faltan: " + ", ".join(faltan), color=ft.Colors.AMBER_900,
                         icono=ft.Icons.WARNING_AMBER)
        else:
            self._avisar("Guardado en FICHAS ML. Ya están todos los datos obligatorios.",
                         color=ft.Colors.GREEN_700, icono=ft.Icons.CHECK_CIRCLE)
        if self.al_guardar:
            self.al_guardar(faltan)
