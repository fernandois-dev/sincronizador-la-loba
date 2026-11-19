import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo
from components.loading import Loading
from modules.servidor.reportes.bajo_stock import obtener_datos_bajo_stock, generar_html, _clp
from modules.servidor.reportes.scheduler import ejecutar_reporte, _semana_actual
from modules.servidor.odoo import OdooService


def _badge_chip(riesgo: str) -> ft.Container:
    if riesgo == "CRITICO":
        return ft.Container(
            content=ft.Text("⚠ CRÍTICO", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
            bgcolor=ft.Colors.RED_600,
            border_radius=ft.BorderRadius.all(12),
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        )
    return ft.Container(
        content=ft.Text("↑ SOLICITAR", size=10, color=ft.Colors.WHITE, weight=ft.FontWeight.BOLD),
        bgcolor=ft.Colors.AMBER_700,
        border_radius=ft.BorderRadius.all(12),
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


class BajoStockPage(PaginaFija, ft.Column):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.loading = Loading(self.page, open=False)
        self._datos: dict = {}
        self._ultimo_resultado: str = ""
        self.expand = True
        self.spacing = 0
        self._build_ui()
        self.page.run_task(self._cargar_datos)

    # ── Construcción UI ───────────────────────────────────────────────────────

    def _build_ui(self):
        self._estado_lbl = ft.Text("", size=12, color=ft.Colors.GREY_600, italic=True)
        self._semana_lbl = ft.Text("", size=12, color=ft.Colors.GREY_500)

        self._btn_enviar = ft.Button(
            content="Enviar reporte ahora",
            icon=ft.Icons.SEND,
            bgcolor=ft.Colors.BLUE_700,
            color=ft.Colors.WHITE,
            on_click=self._on_enviar,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
        )
        self._btn_forzar = ft.OutlinedButton(
            content="Forzar reenvío",
            icon=ft.Icons.REFRESH,
            on_click=self._on_forzar,
            tooltip="Envía aunque ya se haya enviado esta semana",
        )
        self._btn_preview = ft.OutlinedButton(
            content="Vista previa HTML",
            icon=ft.Icons.PREVIEW,
            on_click=self._on_preview,
        )

        self._contenido = ft.Column(
            controls=[self._placeholder("Cargando datos…", ft.Icons.HOURGLASS_TOP)],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=16,
        )

        self.controls = [
            self._build_header(),
            ft.Container(content=self._contenido, expand=True, padding=ft.Padding.all(20)),
        ]

    def _build_header(self):
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.Icon(ft.Icons.INVENTORY_2, size=22, color=ft.Colors.ORANGE_700),
                    ft.Text("Reporte Bajo Stock — Favoritos",
                            size=18, weight=ft.FontWeight.BOLD, color=ft.Colors.ORANGE_700),
                    ft.Container(expand=True),
                    self._semana_lbl,
                    self._estado_lbl,
                    self._btn_preview,
                    self._btn_forzar,
                    self._btn_enviar,
                ],
                spacing=12,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.SURFACE_CONTAINER_LOWEST,
            padding=ft.Padding.symmetric(horizontal=20, vertical=14),
            border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_200)),
        )

    def _placeholder(self, texto, icon):
        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Icon(icon, size=48, color=ft.Colors.GREY_300),
                    ft.Text(texto, size=14, color=ft.Colors.GREY_500, italic=True),
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=12,
            ),
            alignment=ft.Alignment.CENTER,
            expand=True,
            padding=ft.Padding.all(48),
        )

    # ── Carga de datos ────────────────────────────────────────────────────────

    async def _cargar_datos(self):
        try:
            self._datos = await asyncio.to_thread(obtener_datos_bajo_stock)
            self._actualizar_estado_odoo()
            self._render_datos()
        except Exception as exc:
            self._contenido.controls = [
                self._placeholder(f"Error cargando datos: {exc}", ft.Icons.ERROR_OUTLINE)
            ]
            try:
                self._contenido.update()
            except Exception:
                pass

    def _actualizar_estado_odoo(self):
        try:
            from modules.servidor.reportes.scheduler import _reporte_habilitado
            habilitado = _reporte_habilitado()

            last = OdooService.get_config_param("gestor_la_loba.bajo_stock_last_sent") or "nunca"
            semana = _semana_actual()
            enviado = last == semana

            if not habilitado:
                self._estado_lbl.value = "⏸ Reporte desactivado"
                self._estado_lbl.color = ft.Colors.GREY_500
            elif enviado:
                self._estado_lbl.value = "✅ Enviado esta semana"
                self._estado_lbl.color = ft.Colors.GREEN_700
            else:
                self._estado_lbl.value = "📭 Pendiente de envío"
                self._estado_lbl.color = ft.Colors.ORANGE_700

            self._semana_lbl.value = f"Semana {semana}"
            self._btn_enviar.disabled = enviado or not habilitado
        except Exception:
            pass

    def _render_datos(self):
        if not self._datos:
            self._contenido.controls = [
                self._placeholder(
                    "✅ Todos los productos favoritos tienen stock suficiente.",
                    ft.Icons.CHECK_CIRCLE_OUTLINE,
                )
            ]
        else:
            cards = []
            for proveedor, productos in self._datos.items():
                cards.append(self._build_proveedor_card(proveedor, productos))
            self._contenido.controls = cards

        try:
            self._contenido.update()
            self._estado_lbl.update()
            self._semana_lbl.update()
            self._btn_enviar.update()
        except Exception:
            pass

    def _build_proveedor_card(self, proveedor: str, productos: list) -> ft.Container:
        subtotal = sum(float(p.get("subtotal", 0) or 0) for p in productos)
        n_criticos = sum(1 for p in productos if p["riesgo"] == "CRITICO")

        filas = []
        for p in productos:
            fila_color = ft.Colors.RED_50 if p["riesgo"] == "CRITICO" else ft.Colors.AMBER_50
            filas.append(
                ft.Container(
                    content=ft.Row(
                        controls=[
                            ft.Container(
                                content=ft.Text(p["producto"], size=12, max_lines=2,
                                                overflow=ft.TextOverflow.ELLIPSIS),
                                expand=4,
                            ),
                            ft.Container(content=_badge_chip(p["riesgo"]), expand=2,
                                         alignment=ft.Alignment.CENTER),
                            ft.Container(
                                content=ft.Text(str(int(p["stock"])), size=13,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.RED_700),
                                expand=1, alignment=ft.Alignment.CENTER,
                            ),
                            ft.Container(
                                content=ft.Text(f"{int(p['stock_min'])} / {int(p['stock_max'])}",
                                                size=12, color=ft.Colors.GREY_600),
                                expand=2, alignment=ft.Alignment.CENTER,
                            ),
                            ft.Container(
                                content=ft.Text(str(int(p["cantidad_sugerida"])), size=13,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.BLUE_700),
                                expand=1, alignment=ft.Alignment.CENTER,
                            ),
                            ft.Container(
                                content=ft.Text(_clp(p["precio_compra"]), size=12,
                                                color=ft.Colors.ON_SURFACE_VARIANT),
                                expand=2, alignment=ft.Alignment.CENTER_RIGHT,
                            ),
                            ft.Container(
                                content=ft.Text(_clp(p["subtotal"]), size=13,
                                                weight=ft.FontWeight.BOLD,
                                                color=ft.Colors.GREEN_700),
                                expand=2, alignment=ft.Alignment.CENTER_RIGHT,
                            ),
                        ],
                        spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=fila_color,
                    padding=ft.Padding.symmetric(horizontal=14, vertical=10),
                    border=ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.GREY_200)),
                )
            )

        header_tabla = ft.Container(
            content=ft.Row(
                controls=[
                    ft.Container(content=ft.Text("Producto", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREY_600), expand=4),
                    ft.Container(content=ft.Text("Estado", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREY_600), expand=2,
                                 alignment=ft.Alignment.CENTER),
                    ft.Container(content=ft.Text("Stock", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREY_600), expand=1,
                                 alignment=ft.Alignment.CENTER),
                    ft.Container(content=ft.Text("Mín/Máx", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREY_600), expand=2,
                                 alignment=ft.Alignment.CENTER),
                    ft.Container(content=ft.Text("A comprar", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.BLUE_700), expand=1,
                                 alignment=ft.Alignment.CENTER),
                    ft.Container(content=ft.Text("P. compra", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREY_600), expand=2,
                                 alignment=ft.Alignment.CENTER_RIGHT),
                    ft.Container(content=ft.Text("Subtotal", size=11, weight=ft.FontWeight.BOLD,
                                                 color=ft.Colors.GREEN_700), expand=2,
                                 alignment=ft.Alignment.CENTER_RIGHT),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ft.Colors.BLUE_50,
            padding=ft.Padding.symmetric(horizontal=14, vertical=8),
        )

        badge_criticos = ft.Container(
            content=ft.Text(f"⚠ {n_criticos} crítico{'s' if n_criticos != 1 else ''}",
                            size=11, color=ft.Colors.WHITE),
            bgcolor=ft.Colors.RED_600,
            border_radius=ft.BorderRadius.all(10),
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
            visible=n_criticos > 0,
        )

        return ft.Container(
            content=ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Row(
                            controls=[
                                ft.Icon(ft.Icons.STORE, size=18, color=ft.Colors.WHITE),
                                ft.Text(proveedor, size=15, weight=ft.FontWeight.BOLD,
                                        color=ft.Colors.WHITE),
                                badge_criticos,
                                ft.Container(expand=True),
                                ft.Text(f"Compra sugerida: {_clp(subtotal)}",
                                        size=13, color=ft.Colors.WHITE,
                                        weight=ft.FontWeight.W_600),
                            ],
                            spacing=10,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        gradient=ft.LinearGradient(
                            colors=[ft.Colors.BLUE_800, ft.Colors.BLUE_500],
                            begin=ft.Alignment.CENTER_LEFT,
                            end=ft.Alignment.CENTER_RIGHT,
                        ),
                        padding=ft.Padding.symmetric(horizontal=16, vertical=14),
                        border_radius=ft.BorderRadius.only(top_left=10, top_right=10),
                    ),
                    header_tabla,
                    ft.Column(controls=filas, spacing=0),
                ],
                spacing=0,
            ),
            border=ft.Border.all(1, ft.Colors.BLUE_200),
            border_radius=ft.BorderRadius.all(10),
            shadow=ft.BoxShadow(blur_radius=8, spread_radius=0,
                                color=ft.Colors.with_opacity(0.08, ft.Colors.BLACK),
                                offset=ft.Offset(0, 3)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )

    # ── Handlers de botones ───────────────────────────────────────────────────

    def _on_enviar(self, e):
        self._lanzar_envio(forzar=False)

    def _on_forzar(self, e):
        self._lanzar_envio(forzar=True)

    def _lanzar_envio(self, forzar: bool):
        self._btn_enviar.disabled = True
        self._btn_forzar.disabled = True
        self._btn_enviar.update()
        self._btn_forzar.update()

        def _cb(resultado):
            color = ft.Colors.GREEN_700 if resultado["state"] == "S" else ft.Colors.RED_700
            abrir_dialogo(self.page, ft.SnackBar(
                content=ft.Text(resultado["msg"]),
                bgcolor=color,
            ))
            self._actualizar_estado_odoo()
            try:
                self._btn_forzar.disabled = False
                self._btn_forzar.update()
                self._estado_lbl.update()
                self._semana_lbl.update()
                self._btn_enviar.update()
            except Exception:
                pass

        ejecutar_reporte(forzar=forzar, callback=_cb)

    def _on_preview(self, e):
        if not self._datos:
            abrir_dialogo(self.page, ft.SnackBar(content=ft.Text("Sin datos para previsualizar.")))
            return
        html = generar_html(self._datos)
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Vista previa del correo (HTML)"),
            content=ft.Container(
                content=ft.Column(
                    controls=[
                        ft.Text(html[:3000] + ("…" if len(html) > 3000 else ""),
                                selectable=True, size=11, font_family="Roboto Mono"),
                    ],
                    scroll=ft.ScrollMode.AUTO,
                ),
                width=640, height=480,
            ),
            actions=[ft.TextButton("Cerrar", on_click=lambda e: cerrar_dialogo(self.page, dialog))],
        )
        abrir_dialogo(self.page, dialog)
