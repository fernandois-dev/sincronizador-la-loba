import asyncio
from datetime import date
from typing import Optional
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, abrir_unico, cerrar_dialogo, guardar_archivo, montar_componente
from logger_config import get_logger
logger = get_logger(__name__)
from django.db.models import Q, F, Sum
from components.chips import ChipComponent
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_recargar_tb
from components.loading import Loading
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.models import Comparativa, HojasSeleccionadas, MovimientoProductoMes, OdooProducto, OdooTarifa
from modules.servidor.odoo import OdooService
from utilities import pendientes
from modules.servidor.components import tarjetas_dashboard as tarjetas
from modules.servidor.components.tarjetas_dashboard import (
    TarjetaCompras, TarjetaStockCritico, TarjetaTopProductos, TarjetaVentasHoy, TarjetaVentasSemana,
    clp as _clp,
)

# ── Design tokens ─────────────────────────────────────────────────────────────
_BG_PAGE        = ft.Colors.SURFACE_CONTAINER
_BG_CARD        = ft.Colors.SURFACE_CONTAINER_LOWEST
_ACCENT_STOCK = tarjetas.ACENTO_STOCK
_ACCENT_COMPRAS = tarjetas.ACENTO_COMPRAS
_ACCENT_VENTAS = tarjetas.ACENTO_VENTAS
_ACCENT_SEMANA = tarjetas.ACENTO_SEMANA
_ACCENT_TOP_PROD = tarjetas.ACENTO_TOP
_SHADOW = ft.BoxShadow(blur_radius=10, spread_radius=0,
                       color=ft.Colors.with_opacity(0.07, ft.Colors.BLACK),
                       offset=ft.Offset(0, 3))


def _section_label(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Container(width=3, height=14, bgcolor=ft.Colors.GREY_400,
                             border_radius=ft.BorderRadius.all(2)),
                ft.Text(text.upper(), size=11, weight=ft.FontWeight.W_600,
                        color=ft.Colors.GREY_500),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.only(top=6, bottom=2),
    )


_LOCATION_ALIASES = {
    "virtual": "Virtual",
    "customers": "Cliente",
    "suppliers": "Proveedor",
    "inventory": "Inventario",
    "transit": "Tránsito",
    "stock": "Stock",
    "input": "Entrada",
    "output": "Salida",
    "quality control": "Control Calidad",
    "packing zone": "Empaque",
    "production": "Producción",
    "scrap": "Desecho",
}


def _short_location(loc) -> str:
    """Devuelve el nombre corto y legible de una ubicación de Odoo."""
    if isinstance(loc, (list, tuple)):
        name = str(loc[1]) if len(loc) > 1 else ""
    else:
        name = str(loc or "")
    # Tomar solo el último segmento después de "/"
    part = name.split("/")[-1].strip()
    return _LOCATION_ALIASES.get(part.lower(), part) or name


class InicioPage(PaginaFija, ft.Container):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.params = params
        self.expand = True

        self.primary_color = ft.Colors.BLUE_700
        self.secondary_color = ft.Colors.BLUE_100
        self.accent_color = ft.Colors.ORANGE_600

        self.loading = Loading(self.page, open=False)

        self.component_chips: Optional[ft.Row] = ChipComponent(page=self.page)
        self.btn_cargar_tb = self.build_btn_cargar_tb()
        self.btn_refresh_tb = self.build_btn_refresh_tb()
        self.btn_cargar_odoo = self.build_btn_cargar_odoo()

        self.build_diferencias()
        self.quick_actions = ft.Container()
        self.quick_actions.content = self.build_quick_actions()

        # ── Contenedores (con estilo de card) ──────────────────────────────────
        self.ventas_hoy_container = ft.Container(expand=True)
        self.stock_critico_container = ft.Container(expand=True)
        self.compras_proveedor_container = ft.Container(expand=True)
        self.grafico_semana_container = ft.Container(expand=True)
        self.top_productos_container = ft.Container(expand=True)
        for _c, _accent in [
            (self.stock_critico_container,     _ACCENT_STOCK),
            (self.compras_proveedor_container, _ACCENT_COMPRAS),
            (self.ventas_hoy_container,        _ACCENT_VENTAS),
            (self.grafico_semana_container,    _ACCENT_SEMANA),
            (self.top_productos_container,     _ACCENT_TOP_PROD),
        ]:
            _c.bgcolor = _BG_CARD
            _c.border_radius = ft.BorderRadius.all(12)
            _c.border = ft.Border.only(top=ft.BorderSide(3, _accent))
            _c.shadow = _SHADOW
            _c.clip_behavior = ft.ClipBehavior.ANTI_ALIAS

        self._montar_tarjetas()

        self.content = self.build_page()
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))

    def build_diferencias(self):
        self.count_precios_distintos = self.get_count_precios_distintos()
        self.count_barcode_pendientes = self.get_count_barcode_pendientes()
        self.count_descripciones_distintas = self.get_count_descripciones_distintas()
        self.count_nuevos_productos = self.get_count_nuevos_productos()
        self.count_rutas_abastecimiento = self.get_count_rutas_abastecimiento()
        self.count_proveedores_pendientes = self.get_count_proveedores_pendientes()
        self.count_favoritos = self.get_count_favoritos_por_proveedores_seleccionados()
        self.count_desactivados = self.get_count_desactivados_por_proveedores_seleccionados()
        self.count_compras_pendientes = self.get_count_compras_pendientes()

    def get_count_compras_pendientes(self):
        return pendientes.compras()

    def _get_proveedores_seleccionados_ids(self):
        return list(
            HojasSeleccionadas.objects.exclude(proveedor_id__isnull=True)
            .values_list("proveedor_id", flat=True)
            .distinct()
        )

    def get_count_favoritos_por_proveedores_seleccionados(self):
        proveedor_ids = self._get_proveedores_seleccionados_ids()
        if not proveedor_ids:
            return 0
        product_ids = OdooTarifa.objects.filter(partner_id__in=proveedor_ids).values_list("product_tmpl_id", flat=True)
        return OdooProducto.objects.filter(id__in=product_ids, favorito=True).distinct().count()

    def get_count_desactivados_por_proveedores_seleccionados(self):
        proveedor_ids = self._get_proveedores_seleccionados_ids()
        if not proveedor_ids:
            return 0
        product_ids = OdooTarifa.objects.filter(partner_id__in=proveedor_ids).values_list("product_tmpl_id", flat=True)
        return OdooProducto.objects.filter(id__in=product_ids, activo=False).distinct().count()

    # ─── Datos para tablas del dashboard ──────────────────────────────────────

    def _get_stock_critico(self):
        proveedor_ids = self._get_proveedores_seleccionados_ids()
        qs = Comparativa.objects.filter(existe=True).filter(
            odoo_stock__lt=F("tb_min"),
            tb_min__gt=0,
        )
        if proveedor_ids:
            qs = qs.filter(tb_proveedor_id__in=proveedor_ids)
        items = list(qs.order_by("odoo_stock").values(
            "producto", "odoo_stock", "tb_min", "tb_max", "producto_id"
        )[:50])
        # Anotar favorito desde OdooProducto
        product_ids = [i["producto_id"] for i in items if i.get("producto_id")]
        favoritos = set(
            OdooProducto.objects.filter(id__in=product_ids, favorito=True)
            .values_list("id", flat=True)
        )
        for item in items:
            item["favorito"] = item.get("producto_id") in favoritos
        return items

    # ─── Construcción de la página ─────────────────────────────────────────────

    def build_page(self):
        return ft.Column(
            controls=[
                self.build_main_content(),
                self.build_footer(),
            ],
            expand=True,
            spacing=0,
            alignment=ft.MainAxisAlignment.START,
            scroll=ft.ScrollMode.AUTO,
        )

    def build_main_content(self):
        return ft.Container(
            content=ft.Column(
                controls=[
                    # ── Toolbar ───────────────────────────────────────────
                    ft.Container(
                        content=ft.Row(
                            height=40,
                            controls=[
                                ft.Row(
                                    controls=[
                                        ft.Container(expand=True),
                                        self.btn_cargar_tb,
                                        self.btn_refresh_tb,
                                        self.btn_cargar_odoo,
                                    ],
                                    spacing=3,
                                    expand=True,
                                ),
                            ],
                            alignment=ft.MainAxisAlignment.START,
                            spacing=10,
                        ),
                        bgcolor=_BG_CARD,
                        border_radius=ft.BorderRadius.all(12),
                        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                        shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                            color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                                            offset=ft.Offset(0, 2)),
                    ),
                    # ── Chips tabla base ──────────────────────────────────
                    ft.Container(
                        content=self.component_chips,
                        bgcolor=_BG_CARD,
                        border_radius=ft.BorderRadius.all(12),
                        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                        shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                            color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                                            offset=ft.Offset(0, 2)),
                    ),
                    # ── Sincronización ────────────────────────────────────
                    _section_label("Sincronización"),
                    ft.Container(
                        content=self.quick_actions,
                        bgcolor=_BG_CARD,
                        border_radius=ft.BorderRadius.all(12),
                        padding=ft.Padding.symmetric(horizontal=14, vertical=12),
                        shadow=ft.BoxShadow(blur_radius=6, spread_radius=0,
                                            color=ft.Colors.with_opacity(0.05, ft.Colors.BLACK),
                                            offset=ft.Offset(0, 2)),
                    ),
                    # ── Inventario ────────────────────────────────────────
                    _section_label("Inventario"),
                    ft.Row(
                        controls=[
                            self.stock_critico_container,
                            self.compras_proveedor_container,
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    # ── Ventas ────────────────────────────────────────────
                    _section_label("Ventas"),
                    ft.Row(
                        controls=[
                            self.ventas_hoy_container,
                            self.grafico_semana_container,
                        ],
                        spacing=16,
                        vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    # ── Top Productos ──────────────────────────────────────
                    _section_label("Más Vendidos"),
                    self.top_productos_container,
                ],
                spacing=12,
                expand=True,
            ),
            bgcolor=_BG_PAGE,
            padding=ft.Padding.all(20),
            expand=True,
        )

    # ─── Acciones rápidas compactas ────────────────────────────────────────────

    def build_quick_actions(self):
        return ft.Row(
            controls=[
                self._build_compact_action(
                    "Precios",
                    ft.Icons.ATTACH_MONEY,
                    ft.Colors.GREEN_600,
                    lambda e: self.navigate_to("sincronizacion/precio"),
                    pending_count=self.count_precios_distintos,
                ),
                self._build_compact_action(
                    "Barcode",
                    ft.Icons.QR_CODE,
                    self.accent_color,
                    lambda e: self.navigate_to("sincronizacion/barcode"),
                    pending_count=self.count_barcode_pendientes,
                ),
                self._build_compact_action(
                    "Descripciones",
                    ft.Icons.DESCRIPTION,
                    ft.Colors.INDIGO_600,
                    lambda e: self.navigate_to("sincronizacion/descripcion"),
                    pending_count=self.count_descripciones_distintas,
                ),
                self._build_compact_action(
                    "Nuevos",
                    ft.Icons.NEW_RELEASES,
                    self.accent_color,
                    lambda e: self.navigate_to("sincronizacion/nuevos_productos"),
                    pending_count=self.count_nuevos_productos,
                ),
                self._build_compact_action(
                    "Abastecimiento",
                    ft.Icons.DIRECTIONS,
                    self.accent_color,
                    lambda e: self.navigate_to("sincronizacion/abastecimiento"),
                    pending_count=self.count_rutas_abastecimiento,
                ),
                self._build_compact_action(
                    "Proveedores",
                    ft.Icons.LOCAL_SHIPPING,
                    ft.Colors.TEAL_600,
                    lambda e: self.navigate_to("sincronizacion/proveedores"),
                    pending_count=self.count_proveedores_pendientes,
                ),
                self._build_compact_action(
                    "Favoritos",
                    ft.Icons.STAR,
                    ft.Colors.AMBER_600,
                    lambda e: self.navigate_to("sincronizacion/favorito"),
                    pending_count=self.count_favoritos,
                    alert_on_pending=False,
                ),
                self._build_compact_action(
                    "Desactivados",
                    ft.Icons.CANCEL,
                    ft.Colors.RED_600,
                    lambda e: self.navigate_to("sincronizacion/desactivados"),
                    pending_count=self.count_desactivados,
                    alert_on_pending=False,
                ),
                self._build_compact_action(
                    "Compras",
                    ft.Icons.SHOPPING_CART,
                    ft.Colors.BLUE_700,
                    lambda e: self.page.custom_go("/compras/orden_compra"),
                    pending_count=self.count_compras_pendientes,
                ),
            ],
            wrap=True,
            spacing=8,
            run_spacing=8,
        )

    def _build_compact_action(self, title, icon, color, on_click, pending_count=None, alert_on_pending=True):
        has_alert = alert_on_pending and (pending_count or 0) > 0
        badge_color = (ft.Colors.RED_600 if has_alert
                       else ft.Colors.BLUE_600 if not alert_on_pending
                       else ft.Colors.GREEN_600)
        badge_text = str(pending_count) if (pending_count or 0) > 0 else "✓"

        controls = [
            ft.Icon(icon, size=16, color=color),
            ft.Text(title, size=12, weight=ft.FontWeight.W_500, color=ft.Colors.ON_SURFACE),
        ]
        if pending_count is not None:
            controls.append(
                ft.Container(
                    content=ft.Text(badge_text, size=10, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    bgcolor=badge_color,
                    border_radius=ft.BorderRadius.all(10),
                    padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                )
            )

        return ft.Container(
            content=ft.Row(controls=controls, spacing=6, tight=True),
            padding=ft.Padding.symmetric(horizontal=14, vertical=9),
            border=ft.Border.all(1, ft.Colors.with_opacity(0.5, color) if has_alert else ft.Colors.GREY_200),
            border_radius=ft.BorderRadius.all(8),
            bgcolor=ft.Colors.with_opacity(0.05, color) if has_alert else ft.Colors.SURFACE_CONTAINER_LOWEST,
            on_click=on_click,
            ink=True,
            shadow=ft.BoxShadow(
                spread_radius=0,
                blur_radius=4,
                color=ft.Colors.with_opacity(0.08, ft.Colors.GREY),
                offset=ft.Offset(0, 2),
            ),
        )

    # ─── Stock Crítico ─────────────────────────────────────────────────────────

    def _show_movimientos_modal(self, producto_nombre):
        content_col = ft.Column(
            controls=[
                ft.Row(
                    controls=[ft.ProgressRing(width=20, height=20, stroke_width=2), ft.Text("Consultando Odoo...", size=12)],
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
            try:
                moves = await asyncio.to_thread(OdooService.get_movimientos_producto, producto_nombre)
                if not moves:
                    rows = [ft.DataRow(cells=[
                        ft.DataCell(ft.Text("Sin movimientos", color=ft.Colors.GREY_500, italic=True)),
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

    # ─── Compras del proveedor ─────────────────────────────────────────────────

    def _show_detalle_compra_modal(self, oc: dict):
        def _fmt_fecha(s):
            d = str(s)[:10]
            try:
                y, m, day = d.split("-")
                return f"{day}-{m}-{y}"
            except Exception:
                return d

        nombre_oc = oc.get("name", "OC")
        fecha = _fmt_fecha(oc.get("date_order", ""))
        total = _clp(oc.get("amount_total", 0))
        sin_iva = _clp(oc.get("amount_untaxed", 0))

        lineas_data = []

        content_col = ft.Column(
            controls=[
                ft.Row(controls=[
                    ft.ProgressRing(width=20, height=20, stroke_width=2, color=_ACCENT_COMPRAS),
                    ft.Text("Consultando Odoo...", size=12),
                ], spacing=8),
            ],
            scroll=ft.ScrollMode.AUTO,
        )

        def _exportar_excel(e=None):
            if not lineas_data:
                abrir_dialogo(self.page, ft.SnackBar(
                    content=ft.Text("No hay datos para exportar"),
                    bgcolor=ft.Colors.ORANGE_700,
                ))
                return

            safe_name = nombre_oc.replace("/", "_").replace("\\", "_")

            def on_save_result(ev: ft.FilePickerResultEvent):
                if not ev.path:
                    return
                try:
                    import openpyxl
                    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

                    wb = openpyxl.Workbook()
                    ws = wb.active
                    ws.title = safe_name[:31]

                    header_font = Font(bold=True, color="FFFFFF", size=11)
                    header_fill = PatternFill("solid", fgColor="1565C0")
                    header_align = Alignment(horizontal="center", vertical="center")
                    thin = Side(style="thin", color="CCCCCC")
                    border = Border(left=thin, right=thin, top=thin, bottom=thin)

                    headers = ["Producto", "Cantidad", "Precio Unitario", "Subtotal"]
                    ws.append(headers)
                    for col_idx, _ in enumerate(headers, 1):
                        cell = ws.cell(row=1, column=col_idx)
                        cell.font = header_font
                        cell.fill = header_fill
                        cell.alignment = header_align
                        cell.border = border

                    data_align_right = Alignment(horizontal="right")
                    data_align_left = Alignment(horizontal="left")
                    for ln in lineas_data:
                        producto = (
                            ln["product_id"][1]
                            if isinstance(ln.get("product_id"), (list, tuple))
                            else (ln.get("name", "") or "")
                        )
                        qty = ln.get("product_qty", 0)
                        price = ln.get("price_unit", 0)
                        subtotal = qty * price
                        row_idx = ws.max_row + 1
                        ws.append([producto, qty, price, subtotal])
                        ws.cell(row=row_idx, column=1).alignment = data_align_left
                        for c in range(2, 5):
                            ws.cell(row=row_idx, column=c).alignment = data_align_right
                            ws.cell(row=row_idx, column=c).border = border
                        ws.cell(row=row_idx, column=1).border = border

                    ws.column_dimensions["A"].width = 40
                    ws.column_dimensions["B"].width = 12
                    ws.column_dimensions["C"].width = 18
                    ws.column_dimensions["D"].width = 18

                    # Totals row
                    total_row = ws.max_row + 1
                    ws.cell(row=total_row, column=1, value="TOTAL")
                    ws.cell(row=total_row, column=1).font = Font(bold=True)
                    ws.cell(row=total_row, column=4, value=oc.get("amount_total", 0))
                    ws.cell(row=total_row, column=4).font = Font(bold=True, color="1565C0")
                    ws.cell(row=total_row, column=4).alignment = data_align_right

                    wb.save(ev.path)
                    abrir_dialogo(self.page, ft.SnackBar(
                        content=ft.Text(f"Exportado: {ev.path}"),
                        bgcolor=ft.Colors.GREEN_700,
                    ))
                except ImportError:
                    abrir_dialogo(self.page, ft.SnackBar(
                        content=ft.Text("Instalar openpyxl: pip install openpyxl"),
                        bgcolor=ft.Colors.ORANGE_700,
                    ))
                except Exception as ex:
                    abrir_dialogo(self.page, ft.SnackBar(
                        content=ft.Text(f"Error al exportar: {ex}"),
                        bgcolor=ft.Colors.RED_700,
                    ))

            guardar_archivo(self.page, on_save_result, 
                dialog_title="Guardar detalle de compra",
                file_name=f"{safe_name}.xlsx",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["xlsx"],
            )

        btn_export = ft.IconButton(
            icon=ft.Icons.TABLE_VIEW,
            icon_size=18,
            tooltip="Exportar a Excel",
            icon_color=ft.Colors.GREEN_700,
            disabled=True,
            on_click=_exportar_excel,
        )

        # Resumen en el título
        resumen = ft.Row(controls=[
            ft.Container(
                content=ft.Text(f"Sin IVA: {sin_iva}", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                bgcolor=ft.Colors.SURFACE_CONTAINER,
                border_radius=ft.BorderRadius.all(8),
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            ),
            ft.Container(
                content=ft.Text(f"Total: {total}", size=11,
                                color=_ACCENT_COMPRAS, weight=ft.FontWeight.W_600),
                bgcolor=ft.Colors.with_opacity(0.08, _ACCENT_COMPRAS),
                border_radius=ft.BorderRadius.all(8),
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            ),
        ], spacing=8)

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Column(controls=[
                ft.Row(controls=[
                    ft.Icon(ft.Icons.RECEIPT_LONG, color=_ACCENT_COMPRAS, size=18),
                    ft.Text(f"{nombre_oc}  ·  {fecha}", size=14, weight=ft.FontWeight.BOLD, expand=True),
                    btn_export,
                ], spacing=8),
                resumen,
            ], spacing=6, tight=True),
            content=ft.Container(content=content_col, width=600, height=380),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)

        async def _fetch():
            try:
                result = await asyncio.to_thread(OdooService.obtiene_detalle_compra_odoo, oc["id"])
                lineas = result.get("detalle", []) if result.get("state") == "S" else []
                lineas_data.extend(lineas)
                if not lineas:
                    rows = [ft.DataRow(cells=[
                        ft.DataCell(ft.Text("Sin líneas", color=ft.Colors.GREY_500, italic=True)),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")),
                    ])]
                else:
                    rows = [
                        ft.DataRow(cells=[
                            ft.DataCell(ft.Text(
                                ln["product_id"][1] if isinstance(ln.get("product_id"), (list, tuple))
                                else (ln.get("name", "") or ""),
                                size=11,
                            )),
                            ft.DataCell(ft.Text(
                                f"{ln.get('product_qty', 0):g}",
                                size=12,
                            )),
                            ft.DataCell(ft.Text(
                                _clp(ln.get("price_unit", 0)),
                                size=12, color=ft.Colors.ON_SURFACE_VARIANT,
                            )),
                            ft.DataCell(ft.Text(
                                _clp(ln.get("product_qty", 0) * ln.get("price_unit", 0)),
                                size=12, weight=ft.FontWeight.W_500, color=_ACCENT_COMPRAS,
                            )),
                        ])
                        for ln in lineas
                    ]

                tabla = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Producto", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Cant.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                        ft.DataColumn(ft.Text("P. Unit.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                        ft.DataColumn(ft.Text("Subtotal", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                    ],
                    rows=rows,
                    column_spacing=14,
                    heading_row_height=34,
                    data_row_min_height=30,
                    data_row_max_height=34,
                )
                content_col.controls = [ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO)]
                if lineas:
                    btn_export.disabled = False
                    btn_export.update()
            except Exception as ex:
                content_col.controls = [ft.Text(f"Error: {ex}", color=ft.Colors.RED_500, size=12)]
            content_col.update()

        self.page.run_task(_fetch)

    # ─── Ventas de hoy ─────────────────────────────────────────────────────────

    def _show_detalle_venta_modal(self, venta: dict):
        hora = str(venta.get("date_order", ""))[11:16] or "—"
        equipo = venta["team_id"][1] if isinstance(venta.get("team_id"), (list, tuple)) else "—"
        total = _clp(venta.get("amount_total", 0))

        content_col = ft.Column(
            controls=[
                ft.Row(
                    controls=[ft.ProgressRing(width=20, height=20, stroke_width=2),
                               ft.Text("Consultando Odoo...", size=12)],
                    spacing=8,
                )
            ],
            scroll=ft.ScrollMode.AUTO,
        )
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.RECEIPT_LONG, color=_ACCENT_VENTAS),
                    ft.Text(venta.get("name") or f"#{venta.get('id', '')}", size=14, weight=ft.FontWeight.BOLD),
                    ft.Container(
                        content=ft.Text(f"{hora}  ·  {equipo}  ·  {total}", size=11,
                                        color=ft.Colors.with_opacity(0.85, _ACCENT_VENTAS)),
                        bgcolor=ft.Colors.with_opacity(0.1, _ACCENT_VENTAS),
                        border_radius=ft.BorderRadius.all(10),
                        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                    ),
                ],
                spacing=8,
            ),
            content=ft.Container(content=content_col, width=620, height=360),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)

        async def _fetch():
            try:
                lines = await asyncio.to_thread(OdooService.get_detalle_venta, venta["id"])
                if not lines:
                    rows = [ft.DataRow(cells=[
                        ft.DataCell(ft.Text("Sin líneas", color=ft.Colors.GREY_500, italic=True)),
                        ft.DataCell(ft.Text("")), ft.DataCell(ft.Text("")),
                        ft.DataCell(ft.Text("")), ft.DataCell(ft.Text("")),
                    ])]
                else:
                    rows = [
                        ft.DataRow(cells=[
                            ft.DataCell(ft.Text(
                                line["product_id"][1] if isinstance(line.get("product_id"), (list, tuple))
                                else (line.get("name") or "—"),
                                size=11, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                            )),
                            ft.DataCell(ft.Text(f"{line.get('product_uom_qty', 0):g}", size=12,
                                                weight=ft.FontWeight.W_500)),
                            ft.DataCell(ft.Text(_clp(line.get("price_unit", 0)), size=11)),
                            ft.DataCell(ft.Text(
                                f"{line.get('discount', 0):g}%" if line.get("discount") else "—",
                                size=11, color=ft.Colors.ORANGE_700 if line.get("discount") else ft.Colors.GREY_500,
                            )),
                            ft.DataCell(ft.Text(_clp(line.get("price_subtotal", 0)), size=12,
                                                weight=ft.FontWeight.W_500, color=_ACCENT_VENTAS)),
                        ])
                        for line in lines
                    ]
                tabla = ft.DataTable(
                    columns=[
                        ft.DataColumn(ft.Text("Producto", size=12, weight=ft.FontWeight.BOLD)),
                        ft.DataColumn(ft.Text("Cant.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                        ft.DataColumn(ft.Text("P. Unit.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                        ft.DataColumn(ft.Text("Desc.", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                        ft.DataColumn(ft.Text("Subtotal", size=12, weight=ft.FontWeight.BOLD), numeric=True),
                    ],
                    rows=rows,
                    column_spacing=12,
                    heading_row_height=32,
                    data_row_min_height=28,
                    data_row_max_height=40,
                )
                content_col.controls = [ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO)]
            except Exception as ex:
                content_col.controls = [ft.Text(f"Error: {ex}", color=ft.Colors.RED_500, size=12)]
            content_col.update()

        self.page.run_task(_fetch)

    # ─── Gráfico ventas semana ──────────────────────────────────────────────────

    # ─── Top Productos Más Vendidos ────────────────────────────────────────────

    def _get_top_productos_vendidos(self, limite=10):
        proveedor_ids = self._get_proveedores_seleccionados_ids()
        qs = MovimientoProductoMes.objects.all()

        hoy = date.today()
        periodos = []
        for i in range(3):
            m = hoy.month - i
            y = hoy.year
            if m <= 0:
                m += 12
                y -= 1
            periodos.append(Q(anio=y, mes=m))
        qs = qs.filter(periodos[0] | periodos[1] | periodos[2])

        if proveedor_ids:
            product_ids = list(
                Comparativa.objects.filter(
                    existe=True, tb_proveedor_id__in=proveedor_ids
                ).values_list("producto_id", flat=True).distinct()
            )
            if not product_ids:
                return []
            qs = qs.filter(producto_id__in=product_ids)
        return list(
            qs.values("producto_id", "producto_nombre")
            .annotate(total_vendido=Sum("cantidad_vendida"))
            .filter(total_vendido__gt=0)
            .order_by("-total_vendido")[:limite]
        )

    # ─── Tarjetas del dashboard (componentes declarativos) ─────────────────────

    def atajos(self):
        return {"f5": self.recargar_todo}

    def recargar_todo(self):
        """F5: recalcula los pendientes y vuelve a montar las tarjetas cargando todo desde Odoo."""
        self.build_diferencias()
        self.quick_actions.content = self.build_quick_actions()
        self._montar_tarjetas(auto=True)
        self.update()

    def _montar_tarjetas(self, ventas=True, auto=False):
        """Monta las tarjetas @ft.component; cada una maneja su estado y su carga."""
        def proveedor_id():
            ids = self._get_proveedores_seleccionados_ids()
            return ids[0] if ids else None

        def hay_proveedores():
            return bool(self._get_proveedores_seleccionados_ids())

        self.stock_critico_container.content = montar_componente(
            self.page, TarjetaStockCritico, self._get_stock_critico, hay_proveedores,
            al_ver_movimientos=self._show_movimientos_modal,
        )
        self.compras_proveedor_container.content = montar_componente(
            self.page, TarjetaCompras, proveedor_id,
            al_ver_detalle=self._show_detalle_compra_modal,
            al_nueva_compra=lambda: self.page.custom_go("/compras/orden_compra"),
            auto=auto,
        )
        self.top_productos_container.content = montar_componente(
            self.page, TarjetaTopProductos, self._get_top_productos_vendidos, hay_proveedores,
            self._cargar_movimientos_top_odoo,
        )
        if ventas:
            self.ventas_hoy_container.content = montar_componente(
                self.page, TarjetaVentasHoy, al_ver_detalle=self._show_detalle_venta_modal, auto=auto
            )
            self.grafico_semana_container.content = montar_componente(self.page, TarjetaVentasSemana, auto=auto)

    def _cargar_movimientos_top_odoo(self):
        """Trae de Odoo las ventas por producto de los últimos 3 meses a la base local (bloqueante)."""
        import calendar
        from modules.servidor.business_logic import ReporteMovimientosProducto

        hoy = date.today()
        proveedor_ids = self._get_proveedores_seleccionados_ids()
        product_tmpl_ids = list(
            Comparativa.objects.filter(existe=True, tb_proveedor_id__in=proveedor_ids)
            .values_list("producto_id", flat=True).distinct()
        ) if proveedor_ids else None
        logger.info("Top productos: filtrando por %d templates de proveedor",
                    len(product_tmpl_ids) if product_tmpl_ids else 0)

        total_guardados = 0
        for i in range(3):
            m, y = hoy.month - i, hoy.year
            if m <= 0:
                m, y = m + 12, y - 1
            ultimo_dia = hoy.day if (m == hoy.month and y == hoy.year) else calendar.monthrange(y, m)[1]
            logger.info("Top productos: consultando Odoo mes %02d/%d", m, y)
            ventas = OdooService.get_ventas_por_producto_tmpl(
                fecha_desde=date(y, m, 1).strftime("%Y-%m-%d"),
                fecha_hasta=date(y, m, ultimo_dia).strftime("%Y-%m-%d"),
                product_tmpl_ids=product_tmpl_ids,
            )
            for tmpl_id, info in ventas.items():
                ReporteMovimientosProducto.guardar_movimiento(
                    producto_id=tmpl_id, producto_nombre=info["nombre"],
                    mes=m, anio=y, cantidad_vendida=int(info["qty"]),
                )
            total_guardados += len(ventas)
        logger.info("Top productos: %d registros guardados en BD local", total_guardados)

    # ─── Actualización de la vista ─────────────────────────────────────────────

    def update_filtered_view(self):
        self.build_diferencias()
        self.quick_actions.content = self.build_quick_actions()
        self.quick_actions.update()
        pendientes.refrescar(self.page)
        self._montar_tarjetas(ventas=False)
        for c in (self.stock_critico_container, self.compras_proveedor_container, self.top_productos_container):
            c.update()

    # ─── Métodos de datos existentes ──────────────────────────────────────────

    def get_count_precios_distintos(self):
        return pendientes.precios()

    def get_count_descripciones_distintas(self):
        return pendientes.descripciones()

    def get_count_barcode_pendientes(self):
        return pendientes.barcodes()

    def get_count_nuevos_productos(self):
        return pendientes.nuevos_productos()

    def get_count_rutas_abastecimiento(self):
        return pendientes.rutas_abastecimiento()

    def get_count_proveedores_pendientes(self):
        return pendientes.proveedores()

    # ─── Navegación y acciones ─────────────────────────────────────────────────

    def build_btn_cargar_odoo(self):
        return boton_cargar_odoo(lambda e: self.carga_odoo())

    def carga_odoo(self):
        return OdooSyncManager.cargar_datos_odoo_completo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def build_btn_cargar_tb(self):
        return boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base))

    def build_btn_refresh_tb(self):
        return boton_recargar_tb(lambda e: self.recargar_tabla_base())

    def recargar_tabla_base(self):
        hojas = TablaBaseManager.obtener_hojas_seleccionadas()
        if not hojas:
            return
        TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def navigate_to(self, route):
        self.page.custom_go(f"/{route}")

    def eliminar_chip(self, hoja):
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        self.component_chips.remove_chip(hoja)
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    def limpiar_tablas(self):
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view,
        )

    # ─── Footer ────────────────────────────────────────────────────────────────

    def build_footer(self):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Row(controls=[
                        ft.Icon(ft.Icons.STOREFRONT, size=14, color=ft.Colors.GREY_400),
                        ft.Text("Gestor La Loba · Sistema de Gestión", size=11, color=ft.Colors.GREY_500),
                    ], spacing=6),
                    ft.Row(
                        controls=[
                            ft.IconButton(
                                icon=ft.Icons.HELP_OUTLINE,
                                tooltip="Ayuda",
                                icon_size=18,
                                icon_color=ft.Colors.GREY_500,
                                on_click=lambda e: self.show_help(),
                            ),
                            ft.IconButton(
                                icon=ft.Icons.LIST_ALT,
                                tooltip="Ver cambios (Changelog)",
                                icon_size=18,
                                icon_color=ft.Colors.GREY_500,
                                on_click=lambda e: self.show_changelog(),
                            ),
                        ]
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            padding=ft.Padding.symmetric(horizontal=20, vertical=8),
            border=ft.Border.only(top=ft.BorderSide(1, ft.Colors.GREY_200)),
        )

    def show_changelog(self):
        import os
        changelog_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../CHANGELOG.md"))
        changelog_text = "No se pudo leer el changelog."
        try:
            with open(changelog_path, "r", encoding="utf-8") as f:
                changelog_text = f.read()
        except Exception as e:
            changelog_text = f"Error al leer el changelog: {e}"

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Registro de Cambios (Changelog)"),
            content=ft.Container(
                content=ft.Column(
                    controls=[ft.Text(changelog_text, selectable=True, size=13, expand=True)],
                    expand=True,
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=500,
                height=400,
                bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
                padding=ft.Padding.all(20),
                border_radius=ft.BorderRadius.all(10),
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)

    def show_help(self):
        help_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Ayuda - Gestor La Loba"),
            content=ft.Column(
                controls=[
                    ft.Text("🔄 Sincronización de Precios", weight=ft.FontWeight.BOLD),
                    ft.Text("Mantén los precios sincronizados entre tu tabla base y Odoo.", size=12),
                    ft.Divider(),
                    ft.Text("📦 Gestión de Inventario", weight=ft.FontWeight.BOLD),
                    ft.Text("Administra el stock y realiza ajustes de inventario.", size=12),
                    ft.Divider(),
                    ft.Text("📊 Abastecimiento", weight=ft.FontWeight.BOLD),
                    ft.Text("Configura cantidades mínimas y máximas para un mejor control.", size=12),
                ],
                tight=True,
                spacing=10,
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, help_dialog))],
        )
        abrir_dialogo(self.page, help_dialog)
