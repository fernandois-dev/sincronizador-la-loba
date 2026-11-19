"""
Abre la app y recorre todas las pantallas del menú, sin cliente gráfico.

Detecta los errores que encontramos a mano en la migración a Flet 1.1:
excepciones al construir una página, valores que no se pueden enviar al
cliente y valores con el tipo equivocado (bloques grises).
"""
import asyncio

import pytest

from tests.apoyo import ServicioBloqueado, abrir_app, problemas_en_controles


def _rutas():
    from modules.servidor.routes import routes

    return sorted(routes)


def _sin_errores_de_servicio(registros):
    """Errores del log, sin los que solo dicen que un servicio está bloqueado en la prueba."""
    salida = []
    for r in registros:
        exc = r.exc_info[1] if r.exc_info else None
        if isinstance(exc, ServicioBloqueado) or "bloqueado en pruebas" in r.getMessage():
            continue
        salida.append(f"{r.name}: {r.getMessage()}")
    return salida


def test_arranque(errores_log):
    async def prueba():
        app = await abrir_app()
        await app.terminar()
        assert app.errores_envio == []
        assert problemas_en_controles(app.page) == []

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


@pytest.mark.parametrize("ruta", _rutas())
def test_pantalla(ruta, errores_log):
    async def prueba():
        app = await abrir_app()
        app.ir(ruta)
        await app.terminar()
        _serializar(app.page)
        assert app.errores_envio == [], app.errores_envio
        problemas = problemas_en_controles(app.page)
        assert problemas == [], "\n".join(problemas[:20])

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def test_menu_apunta_a_rutas_existentes():
    from apps.servidor.menudata import MenuData
    from modules.servidor.routes import routes

    faltan = []
    for grupo in MenuData().get_control_groups():
        hijos = getattr(grupo, "children", None) or []
        nombres = [h.name for h in hijos] if hijos else [grupo.name]
        for nombre in nombres:
            if f"/{nombre}" not in routes:
                faltan.append(nombre)
    assert faltan == []


def test_vista_previa_ml(errores_log):
    """Abre la vista previa del primer producto ML (sin fotos: Drive está bloqueado)."""
    from modules.servidor.models import ProductoML

    producto = ProductoML.objects.first()
    if producto is None:
        pytest.skip("La base no tiene productos ML")

    async def prueba():
        app = await abrir_app()
        app.ir("/mercado_libre/productos")
        pagina = app.page.controls[0].control_page.content
        await pagina.vista_previa.ahora(pagina, [producto])
        await app.terminar()
        abiertos = [d for d in app.page._dialogs.controls if d.open]
        assert abiertos, "no se abrió la vista previa"
        assert app.errores_envio == [], app.errores_envio
        problemas = problemas_en_controles(app.page)
        assert problemas == [], "\n".join(problemas[:20])

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def _serializar(control):
    """Serializa el control como lo haría la app al enviarlo al cliente."""
    import msgpack
    from flet.controls.base_control import BaseControl
    from flet.messaging.protocol import configure_encode_object_for_msgpack

    msgpack.packb(control, default=configure_encode_object_for_msgpack(BaseControl))


def test_nueva_compra_con_productos(errores_log):
    """La tabla de Nueva Compra con productos de la Tabla Base (antes fallaba al enviarla)."""
    from modules.servidor.models import Comparativa, DetalleCompra

    productos = list(Comparativa.objects.all()[:3])
    if not productos:
        pytest.skip("La base no tiene productos en la Comparativa")

    async def prueba():
        app = await abrir_app()
        app.ir("/compras/orden_compra")
        pagina = app.page.controls[0].control_page.content
        pagina.table.set_data([DetalleCompra(producto=c, cantidad=1, uds_agrupamiento=0,
                                             precio_unitario=100, total=100) for c in productos])
        pagina.table.build_body()
        _serializar(app.page)
        await app.terminar()

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def test_tarjeta_ventas_hoy_declarativa(errores_log, monkeypatch):
    """La tarjeta @ft.component pasa de inicial a ok al hacer clic, sin update() manual."""
    from modules.servidor.odoo import OdooService

    ventas = {"label": "Hoy", "ordenes": [
        {"id": 1, "name": "POS/001", "date_order": "2026-11-06 10:15:00",
         "team_id": [1, "Tienda"], "amount_total": 12990},
    ]}
    monkeypatch.setattr(OdooService, "get_ventas_hoy", staticmethod(lambda: ventas))

    def textos(c, acc):
        if isinstance(getattr(c, "value", None), str):
            acc.append(c.value)
        for nombre in ("_b", "content", "controls", "rows", "cells"):
            hijo = getattr(c, nombre, None)
            for h in (hijo if isinstance(hijo, list) else [hijo]):
                if h is not None and hasattr(h, "_i"):
                    textos(h, acc)
        return acc

    def boton_recargar(c):
        if getattr(c, "tooltip", None) == "Cargar desde Odoo":
            return c
        for nombre in ("_b", "content", "controls"):
            hijo = getattr(c, nombre, None)
            for h in (hijo if isinstance(hijo, list) else [hijo]):
                if h is not None and hasattr(h, "_i") and (r := boton_recargar(h)):
                    return r

    async def prueba():
        app = await abrir_app()
        app.ir("/inicio")
        pagina = app.page.controls[0].control_page.content
        tarjeta = pagina.ventas_hoy_container.content
        assert "POS · Odoo" in textos(tarjeta, [])
        await app.sesion.dispatch_event(boton_recargar(tarjeta)._i, "click", None)
        for _ in range(30):
            await app.esperar(0.1)
            if "POS/001" in textos(tarjeta, []):
                break
        vistos = textos(tarjeta, [])
        assert "POS/001" in vistos, vistos
        assert any("1 venta" in t for t in vistos), vistos
        await app.terminar()
        assert app.errores_envio == [], app.errores_envio

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def test_tarjetas_dashboard_declarativas(errores_log, monkeypatch):
    """Todas las tarjetas del Inicio son componentes y reaccionan a los clics."""
    from flet.components.component import Component
    from modules.servidor.odoo import OdooService

    semana = [{"fecha": f"{i:02d}/11", "total": 1000 * i} for i in range(1, 15)]
    monkeypatch.setattr(OdooService, "get_ventas_dias", staticmethod(lambda dias=14: semana))
    monkeypatch.setattr(OdooService, "listar_ordenes_compra",
                        staticmethod(lambda **kw: [{"name": "P00999", "date_order": "2026-11-01",
                                                    "amount_untaxed": 100, "amount_total": 119}]))

    def recorrer(c):
        yield c
        for nombre in ("_b", "content", "controls", "rows", "cells"):
            hijo = getattr(c, nombre, None)
            for h in (hijo if isinstance(hijo, list) else [hijo]):
                if h is not None and hasattr(h, "_i"):
                    yield from recorrer(h)

    def textos(c):
        return [x.value for x in recorrer(c) if isinstance(getattr(x, "value", None), str)]

    def boton(c, tooltip):
        return next(x for x in recorrer(c) if getattr(x, "tooltip", None) == tooltip)

    async def clic_y_esperar(app, control, condicion):
        await app.sesion.dispatch_event(control._i, "click", None)
        for _ in range(30):
            await app.esperar(0.1)
            if condicion():
                return
        raise AssertionError("la tarjeta no cambió")

    async def prueba():
        app = await abrir_app()
        app.ir("/inicio")
        p = app.page.controls[0].control_page.content
        cont = [p.stock_critico_container, p.compras_proveedor_container, p.ventas_hoy_container,
                p.grafico_semana_container, p.top_productos_container]
        assert all(isinstance(c.content, Component) for c in cont)

        semana_t = p.grafico_semana_container.content
        await clic_y_esperar(app, boton(semana_t, "Cargar ventas semanales desde Odoo"),
                             lambda: any("Total 7 días" in t for t in textos(semana_t)))

        compras_t = p.compras_proveedor_container.content
        await clic_y_esperar(app, boton(compras_t, "Cargar compras desde Odoo"),
                             lambda: "P00999" in textos(compras_t))

        await app.terminar()
        assert app.errores_envio == [], app.errores_envio
        problemas = problemas_en_controles(app.page)
        assert problemas == [], "\n".join(problemas[:20])

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def _tecla(app, key, ctrl=False):
    datos = {"key": key, "shift": False, "ctrl": ctrl, "alt": False, "meta": False}
    return app.sesion.dispatch_event(app.page._i, "keyboard_event", datos)


def test_atajos_de_teclado(errores_log, monkeypatch):
    """F1 abre la ayuda; F5 en el Inicio carga las tarjetas de Odoo sin hacer clic."""
    from modules.servidor.odoo import OdooService

    llamadas = []
    monkeypatch.setattr(OdooService, "get_ventas_dias",
                        staticmethod(lambda dias=14: llamadas.append("semana") or []))
    monkeypatch.setattr(OdooService, "get_ventas_hoy",
                        staticmethod(lambda: llamadas.append("hoy") or {"ordenes": [], "label": "Hoy"}))
    monkeypatch.setattr(OdooService, "listar_ordenes_compra",
                        staticmethod(lambda **kw: llamadas.append("compras") or []))

    async def prueba():
        app = await abrir_app()
        app.ir("/inicio")
        await _tecla(app, "F1")
        await app.esperar(0.2)
        assert any(d.open for d in app.page._dialogs.controls), "F1 no abrió la ayuda"

        await _tecla(app, "F5")
        for _ in range(30):
            await app.esperar(0.1)
            if {"semana", "hoy", "compras"} <= set(llamadas):
                break
        assert {"semana", "hoy", "compras"} <= set(llamadas), llamadas
        await app.terminar()
        assert app.errores_envio == [], app.errores_envio

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def test_menu_contextual_en_tablas(errores_log):
    """Las filas de las pantallas genéricas traen sus acciones en el clic derecho."""
    import flet as ft
    from modules.servidor.models import ProductoML

    if ProductoML.objects.first() is None:
        pytest.skip("La base no tiene productos ML")

    async def prueba():
        app = await abrir_app()
        app.ir("/mercado_libre/productos")
        await app.esperar(0.5)
        pagina = app.page.controls[0].control_page.content
        filas = pagina.table.component_body.controls
        assert filas, "la tabla no tiene filas"
        menu = filas[0].content
        assert isinstance(menu, ft.ContextMenu), type(menu)
        textos = [i.content for i in menu.secondary_items]
        assert "Copiar SKU" in textos, textos
        await app.terminar()

    asyncio.run(prueba())


def test_titulo_en_la_barra_superior(errores_log):
    """La barra superior muestra el título de la pantalla actual."""
    async def prueba():
        app = await abrir_app()
        vistos = {}
        for ruta in ("/inicio", "/reportes/movimientos", "/sincronizacion/barcode", "/reportes/stock"):
            app.ir(ruta)
            vistos[ruta] = app.page._titulo_barra.value
        await app.terminar()
        assert vistos["/inicio"] == "Inicio", vistos
        assert vistos["/reportes/movimientos"] == "Reporte de Movimientos", vistos
        assert all(vistos.values()), vistos

    asyncio.run(prueba())


def test_ventas_dias_agrupa_por_dia_local(monkeypatch):
    """get_ventas_dias suma por día de Chile (no UTC) y devuelve 14 días con ceros."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo
    from modules.servidor import odoo

    tz = ZoneInfo("America/Santiago")
    hoy = datetime.now(tz).replace(hour=12, minute=0, second=0, microsecond=0)
    ayer_tarde = (hoy - timedelta(days=1)).replace(hour=22).astimezone(ZoneInfo("UTC"))  # sigue siendo "ayer" en Chile

    class Falso:
        def execute_kw(self, *a, **k):
            return [
                {"date_order": hoy.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S"), "amount_total": 100},
                {"date_order": hoy.astimezone(ZoneInfo("UTC")).strftime("%Y-%m-%d %H:%M:%S"), "amount_total": 50},
                {"date_order": ayer_tarde.strftime("%Y-%m-%d %H:%M:%S"), "amount_total": 7},
            ]

    monkeypatch.setattr(odoo, "models", Falso())
    dias = odoo.OdooService.get_ventas_dias(14)
    assert len(dias) == 14
    assert dias[-1] == {"fecha": hoy.strftime("%d/%m"), "total": 150}
    assert dias[-2]["total"] == 7
    assert sum(d["total"] for d in dias[:-2]) == 0


def test_revision_detecta_expand_dentro_de_wrap():
    """Una fila con wrap=True y un hijo con expand deja un bloque gris en la app real."""
    import flet as ft
    malo = ft.Row(controls=[ft.Text("a"), ft.Container(expand=True)], wrap=True)
    bueno = ft.Row(controls=[ft.Text("a"), ft.Container()], wrap=True)
    assert any("wrap=True" in p for p in problemas_en_controles(malo))
    assert problemas_en_controles(bueno) == []


def test_contadores_en_el_menu(errores_log, monkeypatch):
    """El menú lateral muestra los pendientes junto a cada opción y suma los del grupo."""
    from utilities import pendientes

    monkeypatch.setattr(pendientes, "contar", lambda: {
        "sincronizacion/precio": 12, "sincronizacion/barcode": 3, "compras/orden_compra": 120,
    })

    def contadores(menu):
        return {i.destination.name: (i.contador.visible, i.contador_texto.value)
                for i in menu.rail.controls if hasattr(i, "contador")}

    async def prueba():
        app = await abrir_app()
        app.ir("/inicio")
        await app.esperar(0.5)
        menu = app.page.controls[0].left_nav
        c = contadores(menu)
        assert c["sincronizacion"] == (True, "15"), c      # suma de sus opciones
        assert c["compras"] == (True, "99+"), c            # tope visual
        assert c["inicio"][0] is False, c                  # sin pendientes: oculto

        # al abrir el grupo, cada opción trae el suyo
        app.ir("/sincronizacion/precio")
        await app.esperar(0.5)
        hijos = contadores(menu)
        assert hijos["sincronizacion/precio"] == (True, "12"), hijos
        assert hijos["sincronizacion/barcode"] == (True, "3"), hijos
        assert hijos["sincronizacion/descripcion"][0] is False, hijos

        await app.terminar()
        assert app.errores_envio == [], app.errores_envio
        problemas = problemas_en_controles(app.page)
        assert problemas == [], "\n".join(problemas[:20])

    asyncio.run(prueba())
    assert _sin_errores_de_servicio(errores_log) == []


def test_pendientes_cuenta_sobre_la_base_local():
    """contar() devuelve un número por cada opción del menú, sin fallar."""
    from utilities import pendientes

    r = pendientes.contar()
    assert set(r) == set(pendientes.POR_RUTA)
    assert all(isinstance(v, int) and v >= 0 for v in r.values()), r
