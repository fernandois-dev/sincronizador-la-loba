import datetime
import os
import re
import tempfile
import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo, tarea_async
from components.custom_buttons import boton_cargar_odoo
from components.generic_inputs import GenericSearchField
from components.loading import Loading
from modules.servidor.data_manage import DataManage
from modules.servidor.models import OdooProducto
from modules.servidor.odoo import OdooService

# ── Design tokens ─────────────────────────────────────────────────────────────
_PAGE_BG   = ft.Colors.SURFACE_CONTAINER
_CARD_BG   = ft.Colors.SURFACE_CONTAINER_LOWEST
_BORDER    = ft.Colors.GREY_200
_SHADOW    = ft.BoxShadow(
    blur_radius=16, spread_radius=0,
    color=ft.Colors.with_opacity(0.07, ft.Colors.BLACK),
    offset=ft.Offset(0, 4),
)
_RADIUS = 12

_RIESGO = {
    "CRITICO":  {"bg": ft.Colors.RED_600,   "light": "#FEF2F2", "border": ft.Colors.RED_200,   "text": ft.Colors.RED_700,   "label": "⚠ Crítico"},
    "SOLICITAR":{"bg": ft.Colors.AMBER_600,  "light": "#FFFBEB", "border": ft.Colors.AMBER_200, "text": ft.Colors.AMBER_700, "label": "↑ Solicitar"},
    "OK":       {"bg": ft.Colors.GREEN_600,
                 "light": "#F0FDF4", "border": ft.Colors.GREEN_200,  "text": ft.Colors.GREEN_700,  "label": "✓ OK"},
}


def _clp(value) -> str:
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return "$0"
    return "$" + f"{v:,}".replace(",", ".")


def _pill(text: str, bgcolor, text_color=ft.Colors.WHITE, size=10) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=size, color=text_color, weight=ft.FontWeight.W_600),
        bgcolor=bgcolor,
        border_radius=ft.BorderRadius.all(99),
        padding=ft.Padding.symmetric(horizontal=10, vertical=3),
    )


def _col_header(label: str, expand: int, align=ft.Alignment.CENTER_LEFT) -> ft.Container:
    return ft.Container(
        content=ft.Text(
            label.upper(), size=10,
            weight=ft.FontWeight.W_700,
            color=ft.Colors.GREY_500,
        ),
        expand=expand,
        alignment=align,
    )


class AjusteStockFavoritosPage(PaginaFija, ft.Column):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.loading = Loading(self.page, open=False)

        self.proveedor_id = None
        self.solo_favoritos = True
        self.estados_activos = {"CRITICO", "SOLICITAR"}
        self.orden_actual = "estado"
        self.editing_id = None
        self.datos_raw: list = []
        self.datos_agrupados: dict = {}
        self.tf_stock = None
        self.tf_min = None
        self.tf_max = None
        self._editing_item = None
        self.data_proveedores = []
        self._texto_busqueda = ""

        self._load_proveedores()
        self.expand = True
        self.spacing = 0
        self._build_ui()
        self._cargar_datos()

    def _load_proveedores(self):
        try:
            self.data_proveedores = DataManage.get_proveedores_con_productos()
        except Exception:
            self.data_proveedores = []

    # ── UI ────────────────────────────────────────────────────────────────────

    def _build_ui(self):
        self._filtro_proveedor = GenericSearchField(
            name="proveedor",
            page=self.page,
            label="Proveedor",
            width=240,
            on_change=self._on_proveedor_change,
            handle_search=self._buscar_proveedor,
        )

        self._sw_favoritos = ft.Switch(
            label="Solo favoritos",
            value=True,
            thumb_icon=ft.Icons.STAR,
            active_color=ft.Colors.AMBER_600,
            on_change=self._on_favoritos_change,
        )

        self._chip_critico   = self._make_chip("CRÍTICO",   True,  ft.Colors.RED_600,   "CRITICO")
        self._chip_solicitar = self._make_chip("SOLICITAR", True,  ft.Colors.AMBER_600, "SOLICITAR")
        self._chip_ok        = self._make_chip("OK",        False, ft.Colors.GREEN_600, "OK")

        self._dd_orden = ft.Dropdown(
            label="Ordenar",
            width=190,
            text_size=12,
            value="estado",
            options=[
                ft.DropdownOption("estado",      "Estado (Crítico → OK)"),
                ft.DropdownOption("stock",       "Stock (menor → mayor)"),
                ft.DropdownOption("descripcion", "Descripción (A → Z)"),
            ],
            on_select=self._on_orden_change,
        )

        self._btn_cargar = boton_cargar_odoo(
            lambda e: self._cargar_datos(),
            tooltip="Consultar datos desde Odoo",
            height=42,
        )

        self._tf_busqueda = ft.TextField(
            hint_text="Buscar producto en el listado…",
            prefix_icon=ft.Icons.SEARCH,
            expand=True,
            height=42,
            text_size=13,
            border_radius=ft.BorderRadius.all(8),
            border_color=ft.Colors.GREY_300,
            focused_border_color=ft.Colors.ORANGE_400,
            content_padding=ft.Padding.symmetric(horizontal=12, vertical=0),
            on_change=self._on_busqueda_change,
            suffix=ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_size=16,
                icon_color=ft.Colors.GREY_400,
                tooltip="Limpiar búsqueda",
                on_click=self._limpiar_busqueda,
            ),
        )

        self._contenido = ft.Column(
            controls=[self._placeholder_loading()],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        )

        self.controls = [
            self._build_header(),
            ft.Container(
                content=self._contenido,
                expand=True,
                padding=ft.Padding.all(20),
                bgcolor=_PAGE_BG,
            ),
        ]

    # ── Chip builder ──────────────────────────────────────────────────────────

    def _make_chip(self, label: str, selected: bool, color: str, estado_key: str) -> ft.Container:
        def on_click(e, est=estado_key):
            sel = e.control.data.get("selected", False)
            e.control.data["selected"] = not sel
            self._on_estado_change(est, not sel)
            self._refresh_chip(e.control)

        chip = ft.Container(
            content=ft.Text(
                f"✓  {label}" if selected else f"   {label}",
                size=11,
                color=ft.Colors.WHITE if selected else ft.Colors.GREY_600,
                weight=ft.FontWeight.W_600,
            ),
            data={"selected": selected, "color": color, "label": label},
            bgcolor=color if selected else ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.Border.all(1.5, color if selected else ft.Colors.GREY_300),
            padding=ft.Padding.symmetric(horizontal=14, vertical=7),
            border_radius=ft.BorderRadius.all(99),
            on_click=on_click,
            ink=True,
        )
        return chip

    def _refresh_chip(self, chip: ft.Container):
        sel   = chip.data.get("selected", False)
        color = chip.data.get("color", ft.Colors.GREY_400)
        label = chip.data.get("label", "")
        chip.bgcolor = color if sel else ft.Colors.SURFACE_CONTAINER_LOWEST
        chip.border  = ft.Border.all(1.5, color if sel else ft.Colors.GREY_300)
        chip.content.color = ft.Colors.WHITE if sel else ft.Colors.GREY_600
        chip.content.value = f"✓  {label}" if sel else f"   {label}"
        chip.update()

    # ── Header ────────────────────────────────────────────────────────────────

    def _build_header(self):
        def _label(text):
            return ft.Text(text, size=10, color=ft.Colors.GREY_400,
                           weight=ft.FontWeight.W_600)

        def _divider_v():
            return ft.Container(
                width=1, height=28,
                bgcolor=ft.Colors.GREY_200,
                margin=ft.Margin.symmetric(horizontal=4),
            )

        # ── Fila 1: título + búsqueda + acciones ──────────────────────────────
        fila_titulo = ft.Row(
            controls=[
                # Acento naranja
                ft.Container(
                    width=4, height=32,
                    bgcolor=ft.Colors.ORANGE_600,
                    border_radius=ft.BorderRadius.all(4),
                ),
                # Título
                ft.Column(
                    controls=[
                        ft.Text("Ajuste de Stock", size=16,
                                weight=ft.FontWeight.BOLD,
                                color=ft.Colors.ON_SURFACE),
                        ft.Text("Favoritos · inventario físico",
                                size=10, color=ft.Colors.GREY_400,
                                weight=ft.FontWeight.W_500),
                    ],
                    spacing=0,
                ),
                ft.Container(width=16),
                # Buscador dinámico (ocupa el espacio disponible)
                self._tf_busqueda,
                ft.Container(width=8),
                # Botón cargar Odoo
                self._btn_cargar,
                # Botón imprimir
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Icon(ft.Icons.PRINT_OUTLINED, size=16,
                                    color=ft.Colors.GREY_600),
                            ft.Text("PDF", size=12, color=ft.Colors.GREY_600,
                                    weight=ft.FontWeight.W_500),
                        ],
                        spacing=4,
                        tight=True,
                    ),
                    padding=ft.Padding.symmetric(horizontal=12, vertical=8),
                    border=ft.Border.all(1, ft.Colors.GREY_300),
                    border_radius=ft.BorderRadius.all(8),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
                    tooltip="Imprimir listado PDF",
                    on_click=lambda e: self.imprimir_listado(),
                    ink=True,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        # ── Fila 2: barra de filtros compacta ─────────────────────────────────
        fila_filtros = ft.Container(
            content=ft.Row(
                controls=[
                    # Proveedor
                    ft.Column(
                        controls=[_label("PROVEEDOR"), self._filtro_proveedor],
                        spacing=3,
                    ),
                    _divider_v(),
                    # Estado chips
                    ft.Column(
                        controls=[
                            _label("MOSTRAR ESTADO"),
                            ft.Row(
                                controls=[
                                    self._chip_critico,
                                    self._chip_solicitar,
                                    self._chip_ok,
                                ],
                                spacing=6,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                        ],
                        spacing=3,
                    ),
                    _divider_v(),
                    # Favoritos switch
                    ft.Column(
                        controls=[
                            _label("FILTRO"),
                            self._sw_favoritos,
                        ],
                        spacing=0,
                    ),
                    _divider_v(),
                    # Ordenar
                    ft.Column(
                        controls=[_label("ORDENAR POR"), self._dd_orden],
                        spacing=3,
                    ),
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            padding=ft.Padding.symmetric(horizontal=24, vertical=10),
            border=ft.Border.only(
                top=ft.BorderSide(1, _BORDER),
                bottom=ft.BorderSide(1, _BORDER),
            ),
        )

        return ft.Column(
            controls=[
                ft.Container(
                    content=fila_titulo,
                    bgcolor=_CARD_BG,
                    padding=ft.Padding.symmetric(horizontal=24, vertical=14),
                    shadow=ft.BoxShadow(
                        blur_radius=6, spread_radius=0,
                        color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                        offset=ft.Offset(0, 2),
                    ),
                ),
                fila_filtros,
            ],
            spacing=0,
        )

    # ── Empty / loading states ─────────────────────────────────────────────────

    def _placeholder_loading(self):
        return self._state_card(
            ft.Icons.HOURGLASS_TOP, "Cargando datos…", ft.Colors.BLUE_200, ft.Colors.BLUE_50,
        )

    def _placeholder_empty(self, msg="Sin productos con los filtros seleccionados."):
        return self._state_card(
            ft.Icons.CHECK_CIRCLE_OUTLINE, msg, ft.Colors.GREEN_400, ft.Colors.GREEN_50,
        )

    def _placeholder_error(self, msg):
        return self._state_card(
            ft.Icons.ERROR_OUTLINE, msg, ft.Colors.RED_300, ft.Colors.RED_50,
        )

    def _state_card(self, icon, msg, icon_color, bg):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Icon(icon, size=40, color=icon_color),
                        bgcolor=bg,
                        border_radius=ft.BorderRadius.all(50),
                        padding=ft.Padding.all(20),
                    ),
                    ft.Text(
                        msg, size=14, color=ft.Colors.GREY_600,
                        text_align=ft.TextAlign.CENTER,
                    ),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=16,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
            padding=ft.Padding.all(60),
        )

    # ── Filter handlers ───────────────────────────────────────────────────────

    def _buscar_proveedor(self, text):
        return [
            {"id": p.id, "name": p.name}
            for p in self.data_proveedores
            if text.lower() in p.name.lower()
        ]

    def _on_proveedor_change(self, e=None, value=None):
        if value:
            self.proveedor_id = value
        elif e and e.control.data:
            self.proveedor_id = e.control.data
        else:
            self.proveedor_id = None

    def _on_favoritos_change(self, e):
        self.solo_favoritos = e.control.value

    def _on_estado_change(self, estado: str, activo: bool):
        if activo:
            self.estados_activos.add(estado)
        else:
            self.estados_activos.discard(estado)

    def _on_orden_change(self, e):
        self.orden_actual = e.control.value

    def _on_busqueda_change(self, e):
        self._texto_busqueda = (e.control.value or "").strip().lower()
        self._aplicar_filtros_y_render()

    def _limpiar_busqueda(self, e=None):
        self._texto_busqueda = ""
        self._tf_busqueda.value = ""
        self._tf_busqueda.update()
        self._aplicar_filtros_y_render()

    # ── Data ──────────────────────────────────────────────────────────────────

    @tarea_async
    async def _cargar_datos(self):
        try:
            self.loading.show("Cargando datos de stock…")
            await asyncio.sleep(0.05)
            proveedor_id = self.proveedor_id["id"] if self.proveedor_id else None
            favorito = True if self.solo_favoritos else None
            self.datos_raw = await asyncio.to_thread(DataManage.reporte_stock, proveedor_id, favorito=favorito)
            self._aplicar_filtros_y_render()
        except Exception as exc:
            self._contenido.controls = [self._placeholder_error(f"Error: {exc}")]
            try:
                self._contenido.update()
            except Exception:
                pass
        finally:
            self.loading.hide()

    def _aplicar_filtros_y_render(self):
        filtrado = [r for r in self.datos_raw if r.get("riesgo") in self.estados_activos]

        if self._texto_busqueda:
            filtrado = [
                r for r in filtrado
                if self._texto_busqueda in (r.get("producto") or "").lower()
            ]

        _orden_riesgo = {"CRITICO": 0, "SOLICITAR": 1, "OK": 2}
        if self.orden_actual == "estado":
            filtrado.sort(key=lambda x: _orden_riesgo.get(x.get("riesgo", "OK"), 3))
        elif self.orden_actual == "stock":
            filtrado.sort(key=lambda x: float(x.get("stock") or 0))
        elif self.orden_actual == "descripcion":
            def _natural(s):
                return [int(c) if c.isdigit() else c.lower()
                        for c in re.split(r'(\d+)', s or '')]
            filtrado.sort(key=lambda x: _natural(x.get("producto") or ""))

        self.datos_agrupados = {}
        for r in filtrado:
            prov = r.get("proveedor") or "Sin Proveedor"
            self.datos_agrupados.setdefault(prov, []).append(r)

        self._render_datos()

    def _render_datos(self):
        if not self.datos_agrupados:
            self._contenido.controls = [self._placeholder_empty()]
        else:
            self._contenido.controls = [
                self._build_proveedor_card(prov, prods)
                for prov, prods in self.datos_agrupados.items()
            ]
        try:
            self._contenido.update()
        except Exception:
            pass

    # ── Card por proveedor ────────────────────────────────────────────────────

    def _build_proveedor_card(self, proveedor: str, productos: list) -> ft.Container:
        n_criticos  = sum(1 for p in productos if p.get("riesgo") == "CRITICO")
        n_solicitar = sum(1 for p in productos if p.get("riesgo") == "SOLICITAR")
        total_compra = sum(
            max(0, (p.get("stock_max") or 0) - (p.get("stock") or 0)) * (p.get("precio_compra") or 0)
            for p in productos
        )

        # Badges de resumen en el header
        badges = [ft.Container(
            content=ft.Text(
                f"{len(productos)} producto{'s' if len(productos) != 1 else ''}",
                size=11, color=ft.Colors.with_opacity(0.85, ft.Colors.WHITE),
                weight=ft.FontWeight.W_500,
            ),
        )]
        if n_criticos:
            badges.append(_pill(f"⚠ {n_criticos} crítico{'s' if n_criticos != 1 else ''}", ft.Colors.with_opacity(0.25, ft.Colors.WHITE)))
        if n_solicitar:
            badges.append(_pill(f"↑ {n_solicitar} por solicitar", ft.Colors.with_opacity(0.18, ft.Colors.WHITE)))

        header_card = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(
                        content=ft.Icon(ft.Icons.STOREFRONT_OUTLINED, size=20, color=ft.Colors.WHITE),
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
                        border_radius=ft.BorderRadius.all(8),
                        padding=ft.Padding.all(6),
                    ),
                    ft.Column(
                        controls=[
                            ft.Text(proveedor, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                            ft.Row(controls=badges, spacing=8),
                        ],
                        spacing=2,
                        expand=True,
                    ),
                    ft.Column(
                        controls=[
                            ft.Text("Compra estimada", size=10, color=ft.Colors.with_opacity(0.7, ft.Colors.WHITE)),
                            ft.Text(_clp(total_compra), size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                        spacing=1,
                    ),
                ],
                spacing=14,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            gradient=ft.LinearGradient(
                colors=[ft.Colors.BLUE_900, ft.Colors.BLUE_700],
                begin=ft.Alignment.CENTER_LEFT,
                end=ft.Alignment.CENTER_RIGHT,
            ),
            padding=ft.Padding.symmetric(horizontal=20, vertical=16),
            border_radius=ft.BorderRadius.only(top_left=_RADIUS, top_right=_RADIUS),
        )

        # Header de columnas
        col_headers = ft.Container(
            content=ft.Row(
                controls=[
                    _col_header("Producto",   4, ft.Alignment.CENTER_LEFT),
                    _col_header("Estado",     2, ft.Alignment.CENTER),
                    _col_header("Stock",      1, ft.Alignment.CENTER_RIGHT),
                    _col_header("Mín",        1, ft.Alignment.CENTER_RIGHT),
                    _col_header("Máx",        1, ft.Alignment.CENTER_RIGHT),
                    _col_header("A comprar",  2, ft.Alignment.CENTER_RIGHT),
                    _col_header("P. compra",  2, ft.Alignment.CENTER_RIGHT),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
            padding=ft.Padding.symmetric(horizontal=20, vertical=10),
            border=ft.Border.only(
                bottom=ft.BorderSide(1, _BORDER),
                top=ft.BorderSide(1, _BORDER),
            ),
        )

        filas = ft.Column(
            controls=[self._build_fila(p) for p in productos],
            spacing=0,
        )

        return ft.Container(
            content=ft.Column(
                controls=[header_card, col_headers, filas],
                spacing=0,
            ),
            bgcolor=_CARD_BG,
            border=ft.Border.all(1, ft.Colors.BLUE_100),
            border_radius=ft.BorderRadius.all(_RADIUS),
            shadow=_SHADOW,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    # ── Fila de producto ──────────────────────────────────────────────────────

    def _build_fila(self, p: dict) -> ft.Container:
        riesgo     = p.get("riesgo", "OK")
        is_editing = self.editing_id == p.get("id")
        cant_sug   = max(0, (p.get("stock_max") or 0) - (p.get("stock") or 0))
        r_cfg      = _RIESGO.get(riesgo, _RIESGO["OK"])

        if is_editing:
            return self._build_fila_editando(p, r_cfg)

        # Barra de color lateral según riesgo
        barra = ft.Container(width=4, bgcolor=r_cfg["bg"])

        badge = ft.Container(
            content=ft.Text(
                r_cfg["label"], size=10,
                color=r_cfg["bg"], weight=ft.FontWeight.W_700,
            ),
            bgcolor=ft.Colors.with_opacity(0.12, r_cfg["bg"]),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.3, r_cfg["bg"])),
            border_radius=ft.BorderRadius.all(99),
            padding=ft.Padding.symmetric(horizontal=9, vertical=3),
        )

        star = ft.Icon(ft.Icons.STAR_ROUNDED, color=ft.Colors.AMBER_500, size=14) if p.get("favorito") else ft.Container(width=14)

        nombre = ft.Row(
            controls=[
                star,
                ft.Text(
                    p.get("producto", ""), size=12,
                    max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                    expand=True, color=ft.Colors.ON_SURFACE,
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        def _num(val, color=ft.Colors.ON_SURFACE_VARIANT, bold=False, size=12):
            return ft.Text(
                str(int(val)) if val is not None else "—",
                size=size, color=color,
                weight=ft.FontWeight.BOLD if bold else ft.FontWeight.NORMAL,
                text_align=ft.TextAlign.RIGHT,
            )

        row = ft.Row(
            controls=[
                ft.Container(content=nombre, expand=4),
                ft.Container(content=badge,  expand=2, alignment=ft.Alignment.CENTER),
                ft.Container(content=_num(p.get("stock"), r_cfg["text"] if riesgo != "OK" else ft.Colors.GREY_800, bold=True, size=13), expand=1, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(content=_num(p.get("stock_min"), ft.Colors.GREY_500), expand=1, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(content=_num(p.get("stock_max"), ft.Colors.GREY_500), expand=1, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(content=_num(cant_sug, ft.Colors.BLUE_700, bold=True), expand=2, alignment=ft.Alignment.CENTER_RIGHT),
                ft.Container(
                    content=ft.Text(_clp(p.get("precio_compra", 0)), size=12, color=ft.Colors.GREY_600, text_align=ft.TextAlign.RIGHT),
                    expand=2, alignment=ft.Alignment.CENTER_RIGHT,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        return ft.Container(
            content=ft.Row(
                controls=[barra, ft.Container(content=row, expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=12))],
                spacing=0,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            border=ft.Border.only(bottom=ft.BorderSide(1, _BORDER)),
            on_click=lambda e, prod=p: self._on_click_fila(prod),
            ink=True,
        )

    def _build_fila_editando(self, p: dict, r_cfg: dict) -> ft.Container:
        def _tf(val, ref_name):
            field = ft.TextField(
                value=str(int(val or 0)),
                height=36,
                text_size=13,
                content_padding=ft.Padding.symmetric(horizontal=8, vertical=0),
                keyboard_type=ft.KeyboardType.NUMBER,
                text_align=ft.TextAlign.RIGHT,
                border_color=ft.Colors.BLUE_400,
                focused_border_color=ft.Colors.BLUE_700,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
                border_radius=ft.BorderRadius.all(6),
                filled=True,
            )
            setattr(self, ref_name, field)
            return field

        self._editing_item = p
        self.tf_stock = _tf(p.get("stock"), "tf_stock")
        self.tf_min   = _tf(p.get("stock_min"), "tf_min")
        self.tf_max   = _tf(p.get("stock_max"), "tf_max")

        star = ft.Icon(ft.Icons.STAR_ROUNDED, color=ft.Colors.AMBER_500, size=14) if p.get("favorito") else ft.Container(width=14)

        nombre = ft.Row(
            controls=[
                star,
                ft.Text(
                    p.get("producto", ""), size=12, expand=True,
                    color=ft.Colors.ON_SURFACE, max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
            ],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        producto_nombre = p.get("producto", "")
        acciones = ft.Row(
            controls=[
                ft.Container(
                    content=ft.Icon(ft.Icons.CHECK_ROUNDED, size=16, color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.GREEN_600,
                    border_radius=ft.BorderRadius.all(6),
                    padding=ft.Padding.all(6),
                    tooltip="Guardar cambios",
                    on_click=lambda e: self._on_guardar(),
                    ink=True,
                ),
                ft.Container(
                    content=ft.Icon(ft.Icons.CLOSE_ROUNDED, size=16, color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.RED_500,
                    border_radius=ft.BorderRadius.all(6),
                    padding=ft.Padding.all(6),
                    tooltip="Cancelar edición",
                    on_click=lambda e: self._on_cancelar(),
                    ink=True,
                ),
                ft.Container(
                    content=ft.Icon(ft.Icons.SWAP_VERT, size=16, color=ft.Colors.WHITE),
                    bgcolor=ft.Colors.BLUE_600,
                    border_radius=ft.BorderRadius.all(6),
                    padding=ft.Padding.all(6),
                    tooltip="Ver historial de movimientos",
                    on_click=lambda e, nombre=producto_nombre: self._show_movimientos_modal(nombre),
                    ink=True,
                ),
            ],
            spacing=6,
            alignment=ft.MainAxisAlignment.CENTER,
        )

        row = ft.Row(
            controls=[
                ft.Container(content=nombre,        expand=4),
                ft.Container(content=acciones,       expand=2, alignment=ft.Alignment.CENTER),
                ft.Container(content=self.tf_stock,  expand=1),
                ft.Container(content=self.tf_min,    expand=1),
                ft.Container(content=self.tf_max,    expand=1),
                ft.Container(
                    content=ft.Text("—", size=12, color=ft.Colors.GREY_400, text_align=ft.TextAlign.RIGHT),
                    expand=2, alignment=ft.Alignment.CENTER_RIGHT,
                ),
                ft.Container(
                    content=ft.Text(_clp(p.get("precio_compra", 0)), size=12, color=ft.Colors.GREY_500, text_align=ft.TextAlign.RIGHT),
                    expand=2, alignment=ft.Alignment.CENTER_RIGHT,
                ),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

        barra_edit = ft.Container(width=4, bgcolor=ft.Colors.BLUE_600)

        return ft.Container(
            content=ft.Row(
                controls=[
                    barra_edit,
                    ft.Container(content=row, expand=True, padding=ft.Padding.symmetric(horizontal=16, vertical=10)),
                ],
                spacing=0,
            ),
            bgcolor=ft.Colors.BLUE_50,
            border=ft.Border.only(
                bottom=ft.BorderSide(1, ft.Colors.BLUE_200),
                top=ft.BorderSide(1, ft.Colors.BLUE_200),
            ),
        )

    # ── Handlers ──────────────────────────────────────────────────────────────

    def _on_click_fila(self, producto: dict):
        if self.editing_id == producto.get("id"):
            return
        self.editing_id = producto.get("id")
        self._render_datos()

    def _on_cancelar(self):
        self.editing_id = None
        self._editing_item = None
        self.tf_stock = self.tf_min = self.tf_max = None
        self._render_datos()

    def _on_guardar(self):
        if not self._editing_item:
            return

        # Validar antes de lanzar el hilo
        try:
            stock_nuevo = float(self.tf_stock.value)
            min_nuevo   = float(self.tf_min.value)
            max_nuevo   = float(self.tf_max.value)
        except (ValueError, AttributeError):
            self._snack("Valores inválidos. Ingresa solo números.", ft.Colors.RED_700)
            return

        if min_nuevo > max_nuevo:
            self._snack("El mínimo no puede ser mayor que el máximo.", ft.Colors.RED_700)
            return

        producto    = self._editing_item
        product_id  = producto.get("id")
        stock_actual = float(producto.get("stock") or 0)

        # Salir del modo edición inmediatamente y mostrar indicador
        self.editing_id = None
        self._editing_item = None
        self.tf_stock = self.tf_min = self.tf_max = None
        self._render_datos()
        self.loading.show("Guardando cambios en Odoo…")

        async def _guardar_en_background():
            errores = []
            try:
                ok = await asyncio.to_thread(DataManage.update_stock_limits, product_id, min_nuevo, max_nuevo)
                if not ok:
                    errores.append("límites de stock")
            except Exception as exc:
                errores.append(f"límites ({exc})")

            if stock_nuevo != stock_actual:
                try:
                    result = await asyncio.to_thread(
                        OdooService.set_inventario,
                        product_id, stock_nuevo, ajuste=False,
                        motivo="Ajuste desde Gestor La Loba",
                    )
                    if result.get("state") != "S":
                        errores.append(f"stock en Odoo: {result.get('msg', '')}")
                    else:
                        OdooProducto.objects.filter(id=product_id).update(qty_available=int(stock_nuevo))
                except Exception as exc:
                    errores.append(f"stock ({exc})")

            self.loading.hide()
            if errores:
                self._snack(f"Error al guardar: {', '.join(errores)}", ft.Colors.RED_700)
            else:
                self._snack("Stock actualizado correctamente", ft.Colors.GREEN_700)
            self._cargar_datos()

        self.page.run_task(_guardar_en_background)

    def _snack(self, msg: str, color=ft.Colors.ON_SURFACE):
        abrir_dialogo(self.page, ft.SnackBar(
            content=ft.Text(msg, color=ft.Colors.WHITE, weight=ft.FontWeight.W_500),
            bgcolor=color,
            behavior=ft.SnackBarBehavior.FLOATING,
            shape=ft.RoundedRectangleBorder(radius=8),
            width=420,
        ))

    def _show_movimientos_modal(self, producto_nombre: str):
        content_col = ft.Column(
            controls=[
                ft.Row(
                    controls=[
                        ft.ProgressRing(width=20, height=20, stroke_width=2),
                        ft.Text("Consultando Odoo...", size=12),
                    ],
                    spacing=8,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.SWAP_VERT, color=ft.Colors.ORANGE_700),
                    ft.Text(f"Movimientos: {producto_nombre[:60]}", size=14, weight=ft.FontWeight.BOLD),
                ],
                spacing=8,
            ),
            content=ft.Container(content=content_col, width=560, height=360),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)

        async def _fetch():
            def _short_location(loc) -> str:
                if not loc:
                    return "—"
                name = loc[1] if isinstance(loc, (list, tuple)) and len(loc) > 1 else str(loc)
                return name.split("/")[-1].strip()

            try:
                moves = await asyncio.to_thread(OdooService.get_movimientos_producto, producto_nombre)
                if not moves:
                    rows = [ft.DataRow(cells=[
                        ft.DataCell(ft.Text("Sin movimientos", color=ft.Colors.GREY_500, italic=True)),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                    ])]
                else:
                    rows = [
                        ft.DataRow(cells=[
                            ft.DataCell(ft.Text(str(m.get("date", ""))[:10], size=11)),
                            ft.DataCell(ft.Text(
                                str(m.get("origin") or "—"),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                color=ft.Colors.BLUE_700,
                            )),
                            ft.DataCell(ft.Text(
                                _short_location(m.get("location_id")),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            )),
                            ft.DataCell(ft.Text(
                                _short_location(m.get("location_dest_id")),
                                size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            )),
                            ft.DataCell(ft.Text(
                                f"{m.get('qty_done', 0):g}",
                                size=12, weight=ft.FontWeight.W_500,
                                color=ft.Colors.GREEN_700 if m.get("qty_done", 0) > 0 else ft.Colors.RED_700,
                            )),
                        ])
                        for m in moves
                    ]
                tabla = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Fecha", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Referencia", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Desde", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Hacia", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Cant.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                    ],
                    rows=rows,
                    column_spacing=12,
                    heading_row_height=32,
                    data_row_min_height=28,
                    data_row_max_height=32,
                )
                content_col.controls = [ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO)]
            except Exception as ex:
                content_col.controls = [ft.Text(f"Error: {ex}", color=ft.Colors.RED_500, size=12)]
            content_col.update()

        self.page.run_task(_fetch)

    # ── Impresión PDF ─────────────────────────────────────────────────────────

    def imprimir_listado(self):
        """Genera un PDF con 2 columnas lado a lado y lo abre con el visor del sistema."""
        try:
            from reportlab.lib.pagesizes import A4
            from reportlab.lib import colors
            from reportlab.lib.units import mm
            from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph
            from reportlab.lib.styles import ParagraphStyle
            from reportlab.lib.enums import TA_CENTER, TA_LEFT
        except ImportError:
            self._snack("Falta instalar reportlab: pip install reportlab", ft.Colors.RED_700)
            return

        # Aplanar productos del listado actual (ya filtrado y ordenado)
        todos = []
        for proveedor, productos in self.datos_agrupados.items():
            for p in productos:
                todos.append({**p, "_proveedor": proveedor})

        if not todos:
            self._snack("No hay productos en el listado actual para imprimir.")
            return

        tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.pdf', prefix='ajuste_favoritos_')
        tmp.close()

        PAGE_W, PAGE_H = A4
        LEFT = RIGHT = 10 * mm
        TOP = 14 * mm
        BOT = 10 * mm
        GAP = 5 * mm   # espacio entre las dos columnas

        doc = SimpleDocTemplate(
            tmp.name, pagesize=A4,
            leftMargin=LEFT, rightMargin=RIGHT,
            topMargin=TOP, bottomMargin=BOT,
        )

        USABLE_W = PAGE_W - LEFT - RIGHT
        # Cada columna ocupa la mitad menos el hueco central
        COL_W = (USABLE_W - GAP) / 2

        # Proporciones dentro de cada columna: 58% desc · 16% stock · 26% físico
        C_N = COL_W * 0.58
        C_S = COL_W * 0.16
        C_F = COL_W * 0.26

        BLUE  = colors.HexColor('#1565C0')
        GREY1 = colors.white
        GREY2 = colors.HexColor('#F5F5F5')
        GRID  = colors.HexColor('#CCCCCC')

        style_cell = ParagraphStyle('cell', fontSize=7.5, fontName='Helvetica', leading=9)
        style_head = ParagraphStyle('head', fontSize=7.5, fontName='Helvetica-Bold',
                                    textColor=colors.white, alignment=TA_CENTER)
        style_title = ParagraphStyle('tit', fontSize=12, fontName='Helvetica-Bold',
                                     alignment=TA_CENTER, spaceAfter=1 * mm)
        style_sub   = ParagraphStyle('sub', fontSize=8, fontName='Helvetica',
                                     alignment=TA_CENTER, spaceAfter=4 * mm,
                                     textColor=colors.grey)

        def _stock_color(val):
            try:
                v = float(val or 0)
            except Exception:
                return colors.black
            return colors.HexColor('#C62828') if v <= 0 else colors.black

        def _build_col_rows(subset):
            """Construye filas [desc, stock, físico] para un subconjunto."""
            rows = [[
                Paragraph('Descripción', style_head),
                Paragraph('Stock', style_head),
                Paragraph('Stock Físico', style_head),
            ]]
            for i, p in enumerate(subset):
                bg = GREY1 if i % 2 == 0 else GREY2
                stock_val = p.get('stock') or 0
                rows.append([
                    Paragraph(p.get('producto') or '', style_cell),
                    str(int(stock_val)),
                    '',
                    bg,           # marcador de color de fila (lo usamos abajo)
                    stock_val,    # para colorear números negativos
                ])
            return rows

        def _build_doble_tabla(izq_rows, der_rows):
            """
            Construye una tabla de 7 columnas:
            [desc_izq, stock_izq, fisico_izq,  GAP,  desc_der, stock_der, fisico_der]
            """
            n = max(len(izq_rows), len(der_rows))

            # Rellenar la columna más corta con filas vacías
            def _empty_row():
                return ['', '', '', colors.white, 0]

            while len(izq_rows) < n:
                izq_rows.append(_empty_row())
            while len(der_rows) < n:
                der_rows.append(_empty_row())

            data = []
            style_cmds = [
                # Cabecera izquierda
                ('BACKGROUND',    (0, 0), (2, 0),  BLUE),
                ('BACKGROUND',    (4, 0), (6, 0),  BLUE),
                # Columna separadora sin bordes
                ('BACKGROUND',    (3, 0), (3, -1), colors.white),
                ('LINEAFTER',     (3, 0), (3, -1), 0, colors.white),
                ('LINEBEFORE',    (3, 0), (3, -1), 0, colors.white),
                # Grid
                ('GRID',   (0, 0), (2, -1), 0.3, GRID),
                ('GRID',   (4, 0), (6, -1), 0.3, GRID),
                ('BOX',    (0, 0), (2, -1), 0.5, GRID),
                ('BOX',    (4, 0), (6, -1), 0.5, GRID),
                # Alineación
                ('ALIGN',  (1, 1), (1, -1), 'CENTER'),
                ('ALIGN',  (5, 1), (5, -1), 'CENTER'),
                ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                ('FONTNAME', (0, 1), (2, -1), 'Helvetica'),
                ('FONTNAME', (4, 1), (6, -1), 'Helvetica'),
                ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                ('TOPPADDING',    (0, 0), (-1, -1), 2),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ('LEFTPADDING',   (0, 1), (0, -1), 4),
                ('LEFTPADDING',   (4, 1), (4, -1), 4),
            ]

            for row_i in range(n):
                li = izq_rows[row_i]
                ld = der_rows[row_i]

                if row_i == 0:
                    # fila de cabecera
                    data.append([li[0], li[1], li[2], '', ld[0], ld[1], ld[2]])
                else:
                    bg_i = li[3]
                    bg_d = ld[3]
                    sv_i = li[4]
                    sv_d = ld[4]
                    data.append([li[0], li[1], li[2], '', ld[0], ld[1], ld[2]])
                    style_cmds += [
                        ('BACKGROUND', (0, row_i), (2, row_i), bg_i),
                        ('BACKGROUND', (4, row_i), (6, row_i), bg_d),
                        ('TEXTCOLOR',  (1, row_i), (1, row_i), _stock_color(sv_i)),
                        ('TEXTCOLOR',  (5, row_i), (5, row_i), _stock_color(sv_d)),
                        ('FONTNAME',   (1, row_i), (1, row_i),
                         'Helvetica-Bold' if float(sv_i or 0) <= 0 else 'Helvetica'),
                        ('FONTNAME',   (5, row_i), (5, row_i),
                         'Helvetica-Bold' if float(sv_d or 0) <= 0 else 'Helvetica'),
                    ]

            col_widths = [C_N, C_S, C_F, GAP, C_N, C_S, C_F]
            t = Table(data, colWidths=col_widths, repeatRows=1)
            t.setStyle(TableStyle(style_cmds))
            return t

        # Partir lista en 2 mitades
        mitad = (len(todos) + 1) // 2
        izq_rows = _build_col_rows(todos[:mitad])
        der_rows = _build_col_rows(todos[mitad:])

        proveedor_label = ", ".join(self.datos_agrupados.keys()) if self.datos_agrupados else ""
        fecha_str = datetime.datetime.now().strftime('%d/%m/%Y %H:%M')

        story = [
            Paragraph('Ajuste de Stock — Favoritos', style_title),
            Paragraph(
                f'{proveedor_label}  ·  {fecha_str}  ·  {len(todos)} productos',
                style_sub,
            ),
            _build_doble_tabla(izq_rows, der_rows),
        ]

        doc.build(story)
        os.startfile(tmp.name)
        self._snack(f"PDF generado — {len(todos)} productos", ft.Colors.GREEN_700)
