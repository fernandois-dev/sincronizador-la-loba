"""Los chequeos de problemas_en_controles detectan lo que el cliente rechaza."""
import decimal

import flet as ft

from tests.apoyo import problemas_en_controles


def test_detecta_valores_que_el_cliente_rechaza():
    texto_numero = ft.Text("x")
    # Saltarse la conversión a str que hace main.py para simular código sin ella.
    texto_numero._values["value"] = decimal.Decimal("1.5")
    arbol = ft.Column([
        texto_numero,
        ft.Icon("arrow_drop_down"),
        ft.Text("titulo", style=ft.TextThemeStyle.TITLE_LARGE),
        ft.Text("bien", theme_style=ft.TextThemeStyle.TITLE_LARGE),
        ft.Icon(ft.Icons.ADD),
    ])
    problemas = problemas_en_controles(arbol)
    assert any("Text.value es Decimal" in p for p in problemas)
    assert any("Icon.icon es texto" in p for p in problemas)
    assert any("TextThemeStyle" in p for p in problemas)
    assert len(problemas) == 3
