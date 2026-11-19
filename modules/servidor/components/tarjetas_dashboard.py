"""Tarjetas declarativas del dashboard (Inicio).

Cada tarjeta es un ``@ft.component``: la pantalla se describe a partir del
estado (``ft.use_state``) y Flet la vuelve a dibujar sola cuando el estado
cambia. No hay que guardar referencias a controles ni llamar a ``update()``.

Para incrustar una tarjeta dentro de la página imperativa se usa
``utilities.flet_compat.montar_componente``.
"""
import asyncio

import flet as ft
import flet_charts as fch

from modules.servidor.odoo import OdooService

ALTO_TABLA = 260
ALTO_TOP = 310
ACENTO_STOCK = ft.Colors.ORANGE_700
# Stock (alerta) y ventas (dinero) mantienen colores con significado; el resto
# sale del tema, así cambian junto con el color elegido en el menú.
ACENTO_COMPRAS = ft.Colors.PRIMARY
ACENTO_VENTAS = ft.Colors.GREEN_700
ACENTO_SEMANA = ft.Colors.TERTIARY
ACENTO_TOP = ft.Colors.SECONDARY


def clp(value) -> str:
    """Formato moneda chilena: puntos como separador de miles, sin decimales."""
    try:
        v = int(round(float(value)))
    except (TypeError, ValueError):
        return "$0"
    return "$" + f"{v:,}".replace(",", ".")


# ── Piezas comunes (funciones puras, sin estado) ──────────────────────────────

def cuerpo_centrado(*controles, alto=ALTO_TABLA) -> ft.Container:
    return ft.Container(
        content=ft.Column(
            controls=list(controles),
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=8,
        ),
        height=alto,
        alignment=ft.Alignment.CENTER,
        padding=ft.Padding.all(20),
    )


def encabezado_tarjeta(titulo, icono, acento, subtitulo, acciones=()) -> ft.Container:
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Icon(icono, size=16, color=acento),
                ft.Text(titulo, size=14, weight=ft.FontWeight.BOLD, color=acento),
                ft.Container(
                    content=ft.Text(subtitulo, size=11, color=ft.Colors.with_opacity(0.85, acento)),
                    bgcolor=ft.Colors.with_opacity(0.1, acento),
                    border_radius=ft.BorderRadius.all(10),
                    padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                ),
                ft.Container(expand=True),
                *acciones,
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.05, acento),
        padding=ft.Padding.symmetric(horizontal=14, vertical=10),
    )


def fecha_dmy(valor) -> str:
    """'YYYY-MM-DD ...' → 'DD-MM-YYYY'."""
    d = str(valor or "")[:10]
    try:
        y, m, dia = d.split("-")
        return f"{dia}-{m}-{y}"
    except ValueError:
        return d


def tarjeta(encabezado, cuerpo) -> ft.Column:
    return ft.Column(controls=[encabezado, cuerpo], spacing=0, expand=True)


def boton_recargar(on_click, acento, tooltip="Cargar desde Odoo", cargando=False, icono=ft.Icons.REFRESH):
    return ft.IconButton(
        icon=icono, icon_size=18, tooltip=tooltip, on_click=on_click,
        icon_color=acento, disabled=cargando,
        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
    )


def usar_carga(obtener, auto=False):
    """Hook: estado de una carga lenta (Odoo) que corre fuera del loop.

    Devuelve ``(vista, recargar)``. ``vista["estado"]`` es "inicial",
    "cargando", "ok" (con ``vista["datos"]``) o "error" (con ``vista["error"]``).
    Con ``auto=True`` carga apenas se monta la tarjeta (F5 en el Inicio).
    """
    vista, set_vista = ft.use_state({"estado": "inicial"})

    async def recargar(e=None):
        if vista["estado"] == "cargando":
            return
        set_vista({"estado": "cargando"})
        try:
            datos = await asyncio.to_thread(obtener)
            set_vista({"estado": "ok", "datos": datos})
        except Exception as ex:
            set_vista({"estado": "error", "error": str(ex)})

    async def al_montar():
        if auto:
            await recargar()

    ft.use_effect(al_montar, [])
    return vista, recargar


def esqueleto(alto=ALTO_TABLA, filas=None):
    """Silueta animada de una tabla mientras llegan los datos (Shimmer)."""
    filas = filas or max(3, int((alto - 24) // 34))

    def barra(ancho=None, expand=False, h=12):
        return ft.Container(height=h, width=ancho, expand=expand, bgcolor=ft.Colors.ON_SURFACE,
                            border_radius=ft.BorderRadius.all(6))

    return ft.Container(
        content=ft.Shimmer(
            base_color=ft.Colors.with_opacity(0.08, ft.Colors.ON_SURFACE),
            highlight_color=ft.Colors.with_opacity(0.22, ft.Colors.ON_SURFACE),
            content=ft.Column(
                controls=[ft.Row([barra(70, h=14), barra(expand=True, h=14), barra(60, h=14)], spacing=16)]
                + [ft.Row([barra(60), barra(expand=True), barra(70)], spacing=16) for _ in range(filas - 1)],
                spacing=20,
            ),
        ),
        height=alto,
        padding=ft.Padding.symmetric(horizontal=16, vertical=14),
    )


def cuerpo_de_carga(vista, acento, icono, texto_inicial, alto=ALTO_TABLA, texto_error="Error al conectar con Odoo"):
    """Cuerpo para los estados inicial / cargando / error (None si hay datos)."""
    estado = vista["estado"]
    if estado == "inicial":
        return cuerpo_centrado(
            ft.Icon(icono, size=32, color=ft.Colors.OUTLINE_VARIANT),
            ft.Text(texto_inicial, size=12, color=ft.Colors.ON_SURFACE_VARIANT, italic=True,
                    text_align=ft.TextAlign.CENTER),
            alto=alto,
        )
    if estado == "cargando":
        return esqueleto(alto)
    if estado == "error":
        return cuerpo_centrado(
            ft.Icon(ft.Icons.ERROR_OUTLINE, size=28, color=ft.Colors.ERROR),
            ft.Text(texto_error, size=12, color=ft.Colors.ERROR),
            ft.Text(vista.get("error", "")[:120], size=11, color=ft.Colors.ERROR,
                    italic=True, text_align=ft.TextAlign.CENTER),
            alto=alto,
        )
    return None


SUBTITULO_ESTADO = {"inicial": "Odoo", "cargando": "Cargando...", "error": "Error de conexión"}


def tabla_simple(columnas, filas, vacio, numericas=()):
    """DataTable compacta con desplazamiento vertical."""
    if not filas:
        filas = [ft.DataRow(cells=[
            ft.DataCell(ft.Text(vacio if i == 0 else "", color=ft.Colors.ON_SURFACE_VARIANT, italic=True, size=12))
            for i in range(len(columnas))
        ])]
    tabla = ft.DataTable(
        expand=True,
        columns=[
            ft.DataColumn(c if isinstance(c, ft.Control) else ft.Text(c, size=12, weight=ft.FontWeight.BOLD),
                          numeric=i in numericas)
            for i, c in enumerate(columnas)
        ],
        rows=filas,
        column_spacing=14,
        heading_row_height=36,
        data_row_min_height=32,
        data_row_max_height=36,
    )
    return ft.Container(
        content=ft.Column(controls=[ft.Row(controls=[tabla], scroll=ft.ScrollMode.AUTO)],
                          scroll=ft.ScrollMode.AUTO),
        height=ALTO_TABLA,
    )



# ── Ventas de Hoy ─────────────────────────────────────────────────────────────

@ft.component
def TarjetaVentasHoy(al_ver_detalle=None, obtener_ventas=None, auto=False):
    """Ventas del día desde Odoo (POS)."""
    vista, recargar = usar_carga(lambda: (obtener_ventas or OdooService.get_ventas_hoy)(), auto)
    cuerpo = cuerpo_de_carga(vista, ACENTO_VENTAS, ft.Icons.POINT_OF_SALE,
                             "Presiona actualizar para cargar\nlas ventas del día desde Odoo")
    if cuerpo is None:
        datos = vista["datos"]
        ordenes, label = datos.get("ordenes", []), datos.get("label", "")
        if ordenes:
            n = len(ordenes)
            total = sum(v.get("amount_total", 0) for v in ordenes)
            subtitulo = f"{n} venta{'s' if n != 1 else ''} · {clp(total)}  ·  {label}"
        else:
            subtitulo = f"0 ventas · {label}" if label else "0 ventas"
        cuerpo = tabla_simple(
            ["Orden", "Hora", "Equipo", "Total"],
            [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(v.get("name", f"#{v.get('id', '')}"), size=11)),
                        ft.DataCell(ft.Text(str(v.get("date_order") or "")[11:16], size=12)),
                        ft.DataCell(ft.Text(
                            v["team_id"][1] if isinstance(v.get("team_id"), (list, tuple)) else "",
                            size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        )),
                        ft.DataCell(ft.Text(clp(v.get("amount_total", 0)), size=12,
                                            weight=ft.FontWeight.W_500, color=ACENTO_VENTAS)),
                    ],
                    on_select_change=(lambda e, venta=v: al_ver_detalle(venta)) if al_ver_detalle else None,
                )
                for v in ordenes
            ],
            "Sin ventas", numericas=(3,),
        )
    else:
        subtitulo = {"inicial": "POS · Odoo"}.get(vista["estado"], SUBTITULO_ESTADO[vista["estado"]])
    return tarjeta(
        encabezado_tarjeta("Ventas de Hoy", ft.Icons.POINT_OF_SALE, ACENTO_VENTAS, subtitulo,
                           [boton_recargar(recargar, ACENTO_VENTAS, cargando=vista["estado"] == "cargando")]),
        cuerpo,
    )


# ── Compras del proveedor ─────────────────────────────────────────────────────

@ft.component
def TarjetaCompras(obtener_proveedor_id, al_ver_detalle=None, al_nueva_compra=None, auto=False):
    """Órdenes de compra del proveedor de la Tabla Base cargada."""
    vista, recargar = usar_carga(
        lambda: OdooService.listar_ordenes_compra(proveedor_id=obtener_proveedor_id()), auto
    )
    cuerpo = cuerpo_de_carga(vista, ACENTO_COMPRAS, ft.Icons.RECEIPT_LONG,
                             "Presiona actualizar para cargar\nlas compras del proveedor")
    if cuerpo is None:
        compras = vista["datos"] or []
        n = len(compras)
        subtitulo = f"{n} orden{'es' if n != 1 else ''}"
        cuerpo = tabla_simple(
            ["Fecha", "OC", "Sin IVA", "Con IVA"],
            [
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(fecha_dmy(c.get("date_order")), size=11)),
                        ft.DataCell(ft.Text(c.get("name", ""), size=11)),
                        ft.DataCell(ft.Text(clp(c.get("amount_untaxed", 0)), size=12,
                                            color=ft.Colors.ON_SURFACE_VARIANT)),
                        ft.DataCell(ft.Text(clp(c.get("amount_total", 0)), size=12,
                                            weight=ft.FontWeight.W_500, color=ACENTO_COMPRAS)),
                    ],
                    on_select_change=(lambda e, oc=c: al_ver_detalle(oc)) if al_ver_detalle else None,
                )
                for c in compras
            ],
            "Sin compras", numericas=(2, 3),
        )
    else:
        subtitulo = {"inicial": "OC · Odoo"}.get(vista["estado"], SUBTITULO_ESTADO[vista["estado"]])
    acciones = []
    if al_nueva_compra:
        acciones.append(boton_recargar(lambda e: al_nueva_compra(), ACENTO_COMPRAS,
                                       tooltip="Nueva compra", icono=ft.Icons.ADD))
    acciones.append(boton_recargar(recargar, ACENTO_COMPRAS, tooltip="Cargar compras desde Odoo",
                                   cargando=vista["estado"] == "cargando"))
    return tarjeta(
        encabezado_tarjeta("Compras Proveedor", ft.Icons.RECEIPT_LONG, ACENTO_COMPRAS, subtitulo, acciones),
        cuerpo,
    )


# ── Ventas de la semana (gráfico) ─────────────────────────────────────────────

def _punto(x, valor, texto):
    return fch.LineChartDataPoint(
        x=x, y=valor,
        tooltip=fch.LineChartDataPointTooltip(
            text=texto, text_style=ft.TextStyle(size=11, color=ft.Colors.ON_INVERSE_SURFACE),
        ),
    )


def _leyenda(color, texto, punteada=False):
    marca = ft.Container(width=14, height=3, bgcolor=None if punteada else color,
                         border=ft.Border.only(top=ft.BorderSide(2, color)) if punteada else None,
                         border_radius=ft.BorderRadius.all(2))
    return ft.Row([marca, ft.Text(texto, size=11, color=ft.Colors.ON_SURFACE_VARIANT)], spacing=5)


def _variacion(actual, anterior):
    """Chip con el cambio porcentual frente a la semana anterior."""
    if not anterior:
        return ft.Text("sin semana anterior", size=11, color=ft.Colors.ON_SURFACE_VARIANT, italic=True)
    pct = (actual - anterior) / anterior * 100
    sube = pct >= 0
    color = ft.Colors.GREEN_700 if sube else ft.Colors.RED_700
    return ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.TRENDING_UP if sube else ft.Icons.TRENDING_DOWN, size=14, color=color),
            ft.Text(f"{pct:+.0f}% vs semana anterior", size=11, color=color,
                    weight=ft.FontWeight.W_600),
        ], spacing=4, tight=True),
        bgcolor=ft.Colors.with_opacity(0.1, color),
        border_radius=ft.BorderRadius.all(10),
        padding=ft.Padding.symmetric(horizontal=8, vertical=2),
    )


def _grafico_semana(datos):
    """Línea de los últimos 7 días contra los 7 anteriores, con tooltip por día."""
    anterior, actual = datos[:-7], datos[-7:]
    maximo = max((d["total"] for d in datos), default=1) or 1

    serie_actual = fch.LineChartData(
        points=[_punto(i, d["total"], f"{d['fecha']}\n{clp(d['total'])}") for i, d in enumerate(actual)],
        color=ACENTO_SEMANA, stroke_width=3, curved=True, prevent_curve_over_shooting=True,
        point=True,
        below_line_bgcolor=ft.Colors.with_opacity(0.12, ACENTO_SEMANA),
    )
    series = [serie_actual]
    if anterior:
        series.insert(0, fch.LineChartData(
            points=[_punto(i, d["total"], f"Sem. anterior {d['fecha']}\n{clp(d['total'])}")
                    for i, d in enumerate(anterior)],
            color=ft.Colors.with_opacity(0.55, ft.Colors.ON_SURFACE_VARIANT), stroke_width=2,
            curved=True, prevent_curve_over_shooting=True, dash_pattern=[6, 4],
        ))

    chart = fch.LineChart(
        data_series=series,
        left_axis=fch.ChartAxis(label_size=44, show_labels=True),
        bottom_axis=fch.ChartAxis(
            labels=[fch.ChartAxisLabel(value=i, label=ft.Text(d["fecha"], size=10, color=ft.Colors.ON_SURFACE_VARIANT))
                    for i, d in enumerate(actual)],
            label_size=28,
        ),
        horizontal_grid_lines=fch.ChartGridLines(
            interval=maximo / 4, color=ft.Colors.with_opacity(0.15, ACENTO_SEMANA), width=1,
        ),
        tooltip=fch.LineChartTooltip(bgcolor=ft.Colors.with_opacity(0.95, ft.Colors.INVERSE_SURFACE), max_width=180),
        min_x=0, max_x=6, min_y=0, max_y=maximo * 1.15,
        expand=True,
    )
    total, total_ant = sum(d["total"] for d in actual), sum(d["total"] for d in anterior)
    return ft.Container(
        content=ft.Column(
            controls=[
                # Filas con wrap=True: sin hijos con expand (Flutter lo rechaza y deja el cuadro gris).
                ft.Row(controls=[
                    ft.Text(f"Total 7 días: {clp(total)}", size=12, color=ACENTO_SEMANA, weight=ft.FontWeight.W_600),
                    _variacion(total, total_ant),
                ], spacing=10, run_spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
                ft.Row(controls=[
                    _leyenda(ACENTO_SEMANA, "Esta semana"),
                    *([_leyenda(ft.Colors.ON_SURFACE_VARIANT, "Semana anterior", punteada=True)] if anterior else []),
                ], spacing=12, run_spacing=2, wrap=True),
                ft.Container(content=chart, expand=True),
            ],
            spacing=8,
            expand=True,
        ),
        height=ALTO_TABLA,
        padding=ft.Padding.symmetric(horizontal=12, vertical=10),
    )


@ft.component
def TarjetaVentasSemana(auto=False):
    """Ventas de los últimos 7 días contra los 7 anteriores."""
    vista, recargar = usar_carga(lambda: OdooService.get_ventas_dias(14), auto)
    cuerpo = cuerpo_de_carga(vista, ACENTO_SEMANA, ft.Icons.SHOW_CHART,
                             "Presiona actualizar para cargar\nlas ventas de la semana",
                             texto_error="Error al cargar ventas semanales")
    if cuerpo is None:
        cuerpo = _grafico_semana(vista["datos"] or [])
        subtitulo = "Últimos 7 días"
    else:
        subtitulo = SUBTITULO_ESTADO[vista["estado"]]
    return tarjeta(
        encabezado_tarjeta("Ventas Semanales", ft.Icons.SHOW_CHART, ACENTO_SEMANA, subtitulo,
                           [boton_recargar(recargar, ACENTO_SEMANA, tooltip="Cargar ventas semanales desde Odoo",
                                           cargando=vista["estado"] == "cargando")]),
        cuerpo,
    )


# ── Stock crítico (datos locales) ─────────────────────────────────────────────

def _boton_opcion(texto, activo, acento, on_click, icono=None):
    color = acento if activo else ft.Colors.ON_SURFACE_VARIANT
    controles = [ft.Icon(icono, size=13, color=color)] if icono else []
    controles.append(ft.Text(texto, size=11, color=color,
                             weight=ft.FontWeight.BOLD if activo else ft.FontWeight.NORMAL))
    return ft.TextButton(
        content=ft.Row(controls=controles, spacing=3, tight=True),
        on_click=on_click,
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=6, vertical=2)),
    )


@ft.component
def TarjetaStockCritico(obtener_items, hay_proveedores, al_ver_movimientos=None):
    """Productos bajo el mínimo (Tabla Base vs Odoo local), con orden por stock o favoritos."""
    orden, set_orden = ft.use_state("stock")
    items = obtener_items()
    if orden == "favorito":
        items = sorted(items, key=lambda x: (not x.get("favorito", False), x.get("odoo_stock", 0)))
    else:
        items = sorted(items, key=lambda x: x.get("odoo_stock", 0))

    n_fav = sum(1 for i in items if i.get("favorito"))
    if hay_proveedores():
        subtitulo = f"{len(items)} bajo mínimo · {n_fav} favorito{'s' if n_fav != 1 else ''}"
    else:
        subtitulo = "Carga una tabla base para ver stock"

    acciones = []
    if items:
        acciones.append(ft.Row(
            controls=[
                ft.Text("Orden:", size=11, color=ft.Colors.ON_SURFACE_VARIANT),
                _boton_opcion("Stock", orden == "stock", ACENTO_STOCK,
                              lambda e: set_orden("stock"), ft.Icons.ARROW_UPWARD),
                _boton_opcion("Favoritos", orden == "favorito", ACENTO_STOCK,
                              lambda e: set_orden("favorito"), ft.Icons.STAR),
            ],
            spacing=2,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ))

    filas = [
        ft.DataRow(
            cells=[
                ft.DataCell(ft.Icon(
                    ft.Icons.STAR if it.get("favorito") else ft.Icons.STAR_BORDER, size=16,
                    color=ft.Colors.AMBER_600 if it.get("favorito") else ft.Colors.OUTLINE_VARIANT,
                )),
                ft.DataCell(ft.Text(str(it["odoo_stock"]), size=12, color=ft.Colors.RED_700,
                                    weight=ft.FontWeight.BOLD)),
                ft.DataCell(ft.Text(f"{it['tb_min']} / {it['tb_max']}", size=12,
                                    color=ft.Colors.ON_SURFACE_VARIANT)),
                ft.DataCell(ft.Text(it["producto"] or "", size=12)),
            ],
            on_select_change=(lambda e, p=it["producto"]: al_ver_movimientos(p)) if al_ver_movimientos else None,
        )
        for it in items
    ]
    cuerpo = tabla_simple(
        [ft.Icon(ft.Icons.STAR, size=14, color=ft.Colors.AMBER_400), "Stock", "Mín / Máx", "Producto"],
        filas, "Sin stock crítico", numericas=(1, 2),
    )
    return tarjeta(
        encabezado_tarjeta("Stock Crítico", ft.Icons.WARNING_AMBER_ROUNDED, ACENTO_STOCK, subtitulo, acciones),
        cuerpo,
    )


# ── Productos más vendidos ────────────────────────────────────────────────────

def _fila_top(i, d, es_favorito, max_qty, al_cambiar_favorito):
    tmpl_id = d.get("producto_id")
    qty = d["total_vendido"] or 0
    es_primero = i == 0
    return ft.Container(
        content=ft.Row(
            controls=[
                ft.Text(f"#{i + 1}", size=11, width=28, text_align=ft.TextAlign.RIGHT,
                        color=ft.Colors.AMBER_600 if es_primero else ft.Colors.ON_SURFACE_VARIANT,
                        weight=ft.FontWeight.BOLD if es_primero else ft.FontWeight.NORMAL),
                ft.IconButton(
                    icon=ft.Icons.STAR if es_favorito else ft.Icons.STAR_BORDER,
                    icon_color=ft.Colors.AMBER_500 if es_favorito else ft.Colors.OUTLINE_VARIANT,
                    icon_size=16,
                    tooltip="Quitar favorito" if es_favorito else "Marcar como favorito",
                    on_click=lambda e: al_cambiar_favorito(tmpl_id),
                    style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                    width=28, height=28,
                ),
                ft.Text(d["producto_nombre"] or "—", size=12, overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                        weight=ft.FontWeight.W_500 if es_primero else ft.FontWeight.NORMAL, expand=True),
                ft.ProgressBar(value=qty / max_qty, width=90, height=10, bgcolor=ft.Colors.SURFACE_CONTAINER,
                               color=ACENTO_TOP if es_primero else ft.Colors.with_opacity(0.65, ACENTO_TOP)),
                ft.Text(f"{qty:,}".replace(",", ".") + " un.", size=12, width=80, text_align=ft.TextAlign.RIGHT,
                        color=ACENTO_TOP, weight=ft.FontWeight.BOLD if es_primero else ft.FontWeight.W_500),
            ],
            spacing=8,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.Padding.symmetric(horizontal=14, vertical=4),
        bgcolor=ft.Colors.with_opacity(0.04, ACENTO_TOP) if i % 2 == 0 else ft.Colors.SURFACE_CONTAINER_LOWEST,
    )


@ft.component
def TarjetaTopProductos(obtener_top, hay_proveedores, cargar_desde_odoo):
    """Ranking de los últimos 3 meses (base local) con favoritos de Odoo.

    obtener_top(limite) → lista local; cargar_desde_odoo() trae los movimientos
    de Odoo a la base local (lento, corre en un hilo).
    """
    limite, set_limite = ft.use_state(10)
    version, set_version = ft.use_state(0)          # sube tras cargar desde Odoo
    carga, set_carga = ft.use_state({"estado": "ok"})
    favoritos, set_favoritos = ft.use_state({})     # {tmpl_id: bool}

    data = obtener_top(limite)
    ids = tuple(d["producto_id"] for d in data if d.get("producto_id"))

    async def traer_favoritos():
        if not ids:
            return
        try:
            filas = await asyncio.to_thread(OdooService.get_favoritos_por_ids, list(ids))
            set_favoritos({r["id"]: bool(r.get("is_favorite")) for r in filas})
        except Exception:
            pass

    ft.use_effect(traer_favoritos, [ids])

    async def cargar(e=None):
        if carga["estado"] == "cargando":
            return
        set_carga({"estado": "cargando"})
        try:
            await asyncio.to_thread(cargar_desde_odoo)
            set_carga({"estado": "ok"})
            set_version(lambda v: v + 1)
        except Exception as ex:
            set_carga({"estado": "error", "error": str(ex)})

    async def cambiar_favorito(tmpl_id):
        nuevo = not favoritos.get(tmpl_id, False)
        set_favoritos({**favoritos, tmpl_id: nuevo})
        await asyncio.to_thread(OdooService.set_priority_productos, tmpl_id, nuevo)

    estado = carga["estado"]
    if estado in ("cargando", "error"):
        cuerpo = cuerpo_de_carga(carga, ACENTO_TOP, ft.Icons.TRENDING_UP, "", alto=ALTO_TOP,
                                 texto_error="Error al cargar desde Odoo")
        subtitulo = "Cargando..." if estado == "cargando" else "Error"
    elif not hay_proveedores():
        cuerpo = cuerpo_centrado(
            ft.Icon(ft.Icons.TRENDING_UP, size=36, color=ft.Colors.OUTLINE_VARIANT),
            ft.Text("Carga una tabla base para ver los productos más vendidos", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT, italic=True, text_align=ft.TextAlign.CENTER),
            alto=ALTO_TOP,
        )
        subtitulo = "Sin datos"
    elif not data:
        cuerpo = cuerpo_centrado(
            ft.Icon(ft.Icons.INVENTORY_2, size=36, color=ft.Colors.OUTLINE_VARIANT),
            ft.Text("Sin movimientos en los últimos 3 meses · Presiona ↓ para cargar desde Odoo", size=12,
                    color=ft.Colors.ON_SURFACE_VARIANT, italic=True, text_align=ft.TextAlign.CENTER),
            alto=ALTO_TOP,
        )
        subtitulo = "Sin ventas · últimos 3 meses"
    else:
        max_qty = max(d["total_vendido"] for d in data) or 1
        cuerpo = ft.Container(
            content=ft.Column(
                controls=[_fila_top(i, d, favoritos.get(d.get("producto_id"), False), max_qty, cambiar_favorito)
                          for i, d in enumerate(data)],
                spacing=0, scroll=ft.ScrollMode.AUTO,
            ),
            height=ALTO_TOP,
        )
        subtitulo = f"Top {len(data)} · últimos 3 meses"

    def boton_limite(n):
        activo = limite == n
        return ft.TextButton(
            content=str(n),
            on_click=lambda e: set_limite(n),
            style=ft.ButtonStyle(
                color=ft.Colors.ON_SECONDARY if activo else ft.Colors.with_opacity(0.6, ACENTO_TOP),
                bgcolor=ACENTO_TOP if activo else ft.Colors.TRANSPARENT,
                padding=ft.Padding.symmetric(horizontal=8, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
                text_style=ft.TextStyle(size=11, weight=ft.FontWeight.BOLD if activo else ft.FontWeight.NORMAL),
            ),
        )

    return tarjeta(
        encabezado_tarjeta(
            "Productos Más Vendidos", ft.Icons.TRENDING_UP, ACENTO_TOP, subtitulo,
            [boton_limite(10), boton_limite(30), boton_limite(50),
             boton_recargar(cargar, ACENTO_TOP, tooltip="Cargar últimos 3 meses desde Odoo",
                            cargando=estado == "cargando", icono=ft.Icons.CLOUD_DOWNLOAD)],
        ),
        cuerpo,
    )
