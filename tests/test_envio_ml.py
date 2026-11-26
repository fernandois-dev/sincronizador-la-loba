"""
Costo de envío de Mercado Libre en el precio: ML lo cobra en TODAS las ventas (bajo
$19.990 es una tarifa menor, pero no cero). Valores reales de la cuenta de La Loba
(reputación naranja/roja con 30 % de descuento) consultados el 26-11-2026.
"""
import math

from modules.mercadolibre import catalogo, publicador

# (medidas, peso_g) → tarifa sin descuento, según precio (tabla naranja/roja de ML Chile)
TARIFAS = {
    ("28x28x28", 1000): (1900, 2342, 10400),   # 5,49 kg volumétrico
    ("18x28x68", 2407): (2271, 2842, 12400),   # 8,57 kg volumétrico
}


def _tramo(precio, tarifas):
    if precio < 9990:
        return tarifas[0], 0.3
    if precio < 19990:
        return tarifas[1], 0.3
    return tarifas[2], 0.5


class MLFalso:
    def __init__(self):
        self.consultas = []

    def usuario_actual(self):
        return {"id": 1, "tags": []}

    def get(self, ruta, params=None, auth=True):
        self.consultas.append((ruta, params))
        if ruta.endswith("/shipping_options/free"):
            medidas, peso = params["dimensions"].rsplit(",", 1)
            tarifa, rate = _tramo(params["item_price"], TARIFAS[(medidas, int(peso))])
            return {"coverage": {"all_country": {
                "list_cost": tarifa * (1 - rate), "currency_id": "CLP", "billable_weight": 5488,
                "discount": {"rate": rate, "type": "mandatory", "promoted_amount": tarifa}}}}
        if ruta.endswith("/listing_prices"):
            fee = round(params["price"] * 0.16)
            return {"sale_fee_amount": 0, "sale_fee_details": {"gross_amount": fee}}
        raise AssertionError(ruta)


def test_bajo_el_umbral_tambien_se_cobra_envio():
    cache = catalogo._CacheML(MLFalso(), "gold_special")
    precio, comision, envio = catalogo.calcular_precio_ml(cache, 3900, "MLC1642", "28x28x28", 1000)
    assert precio < 9990
    assert envio == 1330                      # 1.900 con 30 % de descuento
    assert precio - comision - envio >= 3900  # La Loba recibe al menos lo del local
    assert precio % 100 == 90


def test_paquete_inflado_cuesta_mas():
    cache = catalogo._CacheML(MLFalso(), "gold_special")
    _, _, envio = catalogo.calcular_precio_ml(cache, 3900, "MLC1642", "18x28x68", 2407)
    assert envio == math.ceil(2271 * 0.7 - 1e-6) == 1590


def test_sin_medidas_el_envio_queda_pendiente():
    cache = catalogo._CacheML(MLFalso(), "gold_special")
    precio, comision, envio = catalogo.calcular_precio_ml(cache, 3900, "MLC1642", "", 1000)
    assert envio is None
    assert precio - comision >= 3900


def test_peso_facturable():
    kg, volumetrico = catalogo.peso_facturable("28x28x28", 1000)
    assert volumetrico and round(kg, 2) == 5.49
    assert catalogo.peso_facturable("10x10x10", 2000) == (2.0, False)
    assert catalogo.peso_facturable("", 1000) is None


def test_paquete_de_y_comparacion():
    attrs = [{"id": "SELLER_PACKAGE_HEIGHT", "value_name": "68 cm"},
             {"id": "SELLER_PACKAGE_LENGTH", "value_name": "18 cm"},
             {"id": "SELLER_PACKAGE_WIDTH", "value_name": "28 cm"},
             {"id": "SELLER_PACKAGE_WEIGHT", "value_name": "2407 g"}]
    medidas, peso = publicador.paquete_de(attrs)
    assert peso == 2407
    assert publicador._mismo_paquete(medidas, "68x18x28")
    assert not publicador._mismo_paquete(medidas, "28x28x28")
    assert publicador.paquete_de([{"id": "SELLER_PACKAGE_WEIGHT", "value_name": "1,5 kg"}]) == ("", 1500)


def test_info_envio_para_la_simulacion(monkeypatch):
    monkeypatch.setattr(publicador, "config_ml", lambda: {"tipo_publicacion": "gold_special"})

    class P:
        ref_interna, peso_gr, medidas_paquete = "ESP0064", 1000, "28x28x28"
        precio_ml, comision, envio, precio_local = 4590, 643, 0, 3900

    res = {"avisos": []}
    publicador._revisar_envio(MLFalso(), P(), res)
    texto = " ".join(res["envio"]["lineas"])
    assert res["envio"]["costo"] == 1330
    assert "5,5 kg" in texto and "volumétrico" in texto and "$1.330" in texto
    # el precio guardado no incluía el envío: avisa que La Loba recibiría menos que en el local
    assert any("Actualiza la lista" in a for a in res["avisos"])
