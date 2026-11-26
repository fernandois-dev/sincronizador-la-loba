"""
Fichas ML: datos de la categoría de Mercado Libre en la pestaña FICHAS ML
(modules/mercadolibre/fichas.py) y su formulario en la vista previa.
"""
import asyncio
import gc
import json

import pytest

from modules.mercadolibre import catalogo, fichas

# Datos de una categoría tipo Cojines, como los devuelve /categories/{id}/attributes
ATRIBUTOS_COJINES = [
    {"id": "BRAND", "name": "Marca", "tags": {"required": True}, "value_type": "string"},
    {"id": "GTIN", "name": "Código universal de producto", "tags": {}, "value_type": "string"},
    {"id": "FILLING_MATERIAL", "name": "Material del relleno", "tags": {"required": True},
     "value_type": "list", "values": [{"id": "1", "name": "Poliéster"}, {"id": "2", "name": "Algodón"}]},
    {"id": "SALE_FORMAT", "name": "Formato de venta", "tags": {"required": True},
     "value_type": "list", "values": [{"id": "3", "name": "Unidad"}, {"id": "4", "name": "Pack"}]},
    {"id": "UNITS_PER_PACKAGE", "name": "Cantidad de envases", "tags": {"conditional_required": True},
     "value_type": "number"},
    {"id": "COLOR", "name": "Color", "tags": {}, "value_type": "string",
     "values": [{"id": "5", "name": "Blanco"}]},
    {"id": "INTERNO", "name": "Dato interno", "tags": {"hidden": True}, "value_type": "string"},
]


class HojaFalsa:
    """Lo mínimo de un gspread.Worksheet que usa fichas.py."""

    def __init__(self, filas=None):
        self.celdas = [list(fichas.ENCABEZADOS)] + [list(f) for f in (filas or [])]
        self.row_count = 500

    def get_all_values(self):
        return [list(f) for f in self.celdas]

    def update(self, range_name, values, value_input_option=None):
        assert range_name == "A1"
        self.celdas = [list(f) for f in values] + self.celdas[len(values):]

    def batch_clear(self, rangos):
        (rango,) = rangos
        desde = int(rango.split(":")[0][1:])
        self.celdas = self.celdas[:desde - 1]

    def add_rows(self, n):
        self.row_count += n


@pytest.fixture
def hoja(monkeypatch):
    ws = HojaFalsa([["OTRO1", "Color", "Rojo", "manual", "2026-11-01 10:00"]])
    monkeypatch.setattr(fichas, "_hoja", lambda crear=False: ws)
    return ws


def test_combinar_prioridad_y_nombres_equivalentes():
    valores, origen = fichas.combinar(
        {"MATERIAL DEL RELLENO": "Algodón"},                           # columna de la planilla
        {"Material del relleno": "Poliéster", "Color": "Blanco"},       # ficha
        [("Cantidad de envases", "1"), ("Color", "Negro")])              # por defecto
    assert valores == {"MATERIAL DEL RELLENO": "Algodón", "Color": "Blanco", "Cantidad de envases": "1"}
    assert origen == {"MATERIAL DEL RELLENO": "planilla", "Color": "ficha",
                      "Cantidad de envases": fichas.ORIGEN_DEFECTO}


def test_guardar_y_leer_no_toca_otros_productos(hoja):
    fichas.guardar("alg0001", {"Material del relleno": "Poliéster", "Color": "  "})
    fichas.guardar("ALG0001", {"Formato de venta": "Unidad", "Material del relleno": "Poliéster"})
    todas = fichas.leer_todas()
    assert todas == {"OTRO1": {"Color": "Rojo"},
                     "ALG0001": {"Formato de venta": "Unidad", "Material del relleno": "Poliéster"}}
    assert hoja.celdas[0] == fichas.ENCABEZADOS
    assert all(f[3] == fichas.ORIGEN_MANUAL for f in hoja.celdas[1:] if f[0] == "ALG0001")


def test_guardar_sin_ref_falla(hoja):
    with pytest.raises(ValueError):
        fichas.guardar("", {"Color": "Blanco"})


def _producto(**cambios):
    from modules.servidor.models import ProductoML

    datos = dict(estado=catalogo.ESTADO_FALTAN, pendientes="faltan datos ML: Material del relleno, Formato de venta",
                 hoja="ALGODON", fila=5, ref_interna="ALG0001", producto="ALGODON SILICONADO 1 KG",
                 precio_local=3900, precio_ml=4690, comision=750, stock=16, peso_gr=1000,
                 medidas_paquete="30x30x20", categoria_id="MLC1642", categoria_nombre="Cojines",
                 marca="GENERICA", titulo="Algodón Siliconado 1 Kg", atributos_ml="{}", atributos_origen="{}")
    datos.update(cambios)
    return ProductoML(**datos)


def test_aplicar_ficha_recalcula_pendientes_y_estado():
    p = _producto(pendientes="sin fotos, faltan datos ML: Material del relleno, Formato de venta")
    faltan = catalogo.aplicar_ficha(p, {"Material del relleno": "Poliéster"}, ATRIBUTOS_COJINES)
    assert faltan == ["Formato de venta"]
    assert p.pendientes == "sin fotos, faltan datos ML: Formato de venta"
    assert p.estado == catalogo.ESTADO_FALTAN

    p.pendientes = "faltan datos ML: Formato de venta"
    faltan = catalogo.aplicar_ficha(p, {"Material del relleno": "Poliéster", "Formato de venta": "Unidad"},
                                    ATRIBUTOS_COJINES)
    assert faltan == [] and p.pendientes == "" and p.estado == catalogo.ESTADO_LISTO
    assert p.datos_ml == {"Material del relleno": "Poliéster", "Formato de venta": "Unidad"}
    assert set(p.origen_datos_ml.values()) == {"ficha"}


def test_aplicar_ficha_respeta_columna_de_la_planilla():
    p = _producto(atributos_ml=json.dumps({"MATERIAL DEL RELLENO": "Algodón"}),
                  atributos_origen=json.dumps({"MATERIAL DEL RELLENO": "planilla"}))
    catalogo.aplicar_ficha(p, {"Material del relleno": "Poliéster", "Formato de venta": "Unidad"},
                           ATRIBUTOS_COJINES)
    assert p.datos_ml["MATERIAL DEL RELLENO"] == "Algodón"   # la planilla manda
    assert "Material del relleno" not in p.datos_ml


def test_datos_a_mostrar():
    from modules.servidor.components.datos_ml import datos_a_mostrar

    principales, opcionales = datos_a_mostrar(ATRIBUTOS_COJINES, {}, [])
    assert [a["id"] for a in principales] == ["FILLING_MATERIAL", "SALE_FORMAT", "UNITS_PER_PACKAGE"]
    assert [a["id"] for a in opcionales] == ["COLOR"]      # sin marca, GTIN ni ocultos


def test_formulario_en_la_vista_previa_guarda_en_fichas(monkeypatch, hoja, errores_log):
    import flet as ft
    from modules.mercadolibre import publicador
    from modules.servidor.components.datos_ml import FormularioDatosML
    from tests.apoyo import abrir_app, problemas_en_controles

    monkeypatch.setattr(publicador, "miniaturas", lambda ref: [])
    monkeypatch.setattr(publicador, "atributos_categoria", lambda cat, ml=None: ATRIBUTOS_COJINES)

    async def prueba():
        app = await abrir_app()
        p = _producto()
        await asyncio.to_thread(p.save)
        app.ir("/mercado_libre/productos")
        await app.esperar()
        pagina = app.page.controls[0].control_page.content
        await pagina.vista_previa.ahora(pagina, [p])
        await app.esperar()
        assert [d for d in app.page._dialogs.controls if d.open], "no se abrió la vista previa"
        assert problemas_en_controles(app.page) == []

        dlg = next(d for d in app.page._dialogs.controls if d.open)

        def boton_publicar():
            return next(b for b in dlg.actions if getattr(b, "content", None) == "Publicar")

        assert boton_publicar().disabled  # faltan datos
        form = next(o for o in gc.get_objects() if isinstance(o, FormularioDatosML) and o.p is p)
        assert isinstance(form.campos["Material del relleno"], ft.Dropdown)
        assert isinstance(form.campos["Cantidad de envases"], ft.TextField)
        form.campos["Material del relleno"].value = "Poliéster"
        form.campos["Formato de venta"].value = "Unidad"
        form.campos["Cantidad de envases"].value = "1"
        await form.guardar()
        await app.esperar()

        assert app.errores_envio == [], app.errores_envio
        assert problemas_en_controles(app.page) == []
        assert not boton_publicar().disabled, boton_publicar().tooltip  # listo: se puede publicar
        await app.terminar()
        return p

    p = asyncio.run(prueba())
    assert fichas.leer_todas()["ALG0001"] == {
        "Material del relleno": "Poliéster", "Formato de venta": "Unidad", "Cantidad de envases": "1"}
    from modules.servidor.models import ProductoML
    guardado = ProductoML.objects.get(pk=p.pk)
    assert guardado.estado == catalogo.ESTADO_LISTO and guardado.pendientes == ""
    assert guardado.datos_ml["Formato de venta"] == "Unidad"


@pytest.mark.parametrize("ok", [True, False])
def test_simular_muestra_el_resultado_en_una_ventana(monkeypatch, ok, errores_log):
    """Al simular, el veredicto aparece de inmediato en su propia ventana; si se puede,
    con el botón Publicar, y 'Volver' regresa a la vista previa."""
    from modules.mercadolibre import publicador
    from tests.apoyo import abrir_app, problemas_en_controles

    monkeypatch.setattr(publicador, "miniaturas", lambda ref: [])
    monkeypatch.setattr(publicador, "atributos_categoria", lambda cat, ml=None: ATRIBUTOS_COJINES)
    resultado = {"ok": ok, "errores": [] if ok else ["Falta Cantidad de envases"],
                 "avisos": ["La columna 'MATERIAL ML' no es un dato de esta categoría: se ignora."]}
    monkeypatch.setattr(publicador, "simular", lambda p, ml=None: resultado)

    async def prueba():
        app = await abrir_app()
        p = _producto(estado=catalogo.ESTADO_LISTO, pendientes="", ref_interna=f"SIM{int(ok)}")
        await asyncio.to_thread(p.save)
        app.ir("/mercado_libre/productos")
        await app.esperar()
        pagina = app.page.controls[0].control_page.content
        await pagina.vista_previa.ahora(pagina, [p])
        vista = next(d for d in app.page._dialogs.controls if d.open)
        boton_simular = next(b for b in vista.actions if getattr(b, "content", None) == "Simular publicación")
        await boton_simular.on_click(None)
        await app.esperar()

        abiertos = [d for d in app.page._dialogs.controls if d.open]
        assert len(abiertos) == 1 and abiertos[0] is not vista
        ventana = abiertos[0]
        titulo = ventana.content.controls[0].content.controls[1].controls[0].value
        assert titulo == ("Se puede publicar" if ok else "No se puede publicar todavía")
        textos = [b.content for b in ventana.actions]
        assert ("Publicar" in textos) == ok
        assert problemas_en_controles(app.page) == []

        volver = next(b for b in ventana.actions if b.content == "Volver a la vista previa")
        volver.on_click(None)
        await app.esperar()
        assert [d for d in app.page._dialogs.controls if d.open] == [vista]
        assert app.errores_envio == []
        await app.terminar()

    asyncio.run(prueba())
