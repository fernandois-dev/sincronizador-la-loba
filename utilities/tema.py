"""Tema visual de La Loba.

Un solo lugar para los colores y el estilo de los controles. El color base
(azul petróleo) genera toda la paleta de Material 3 en claro y en oscuro; el
selector de color del menú solo cambia la semilla, el resto del estilo se
mantiene.
"""
import flet as ft

COLOR_LA_LOBA = "#0F5C6E"  # azul petróleo

# (valor, nombre) para el selector de color del menú. El primero es el predeterminado.
COLORES = [
    (COLOR_LA_LOBA, "La Loba (azul petróleo)"),
    ("indigo", "Índigo"),
    ("blue", "Azul"),
    ("teal", "Verde azulado"),
    ("green", "Verde"),
    ("deeppurple", "Morado"),
    ("orange", "Naranjo"),
    ("pink", "Rosado"),
]


def crear_tema(semilla: str = COLOR_LA_LOBA) -> ft.Theme:
    redondeado = ft.RoundedRectangleBorder(radius=12)
    return ft.Theme(
        color_scheme_seed=semilla,
        use_material3=True,
        appbar_theme=ft.AppBarTheme(
            title_text_style=ft.TextStyle(size=22, weight=ft.FontWeight.W_600),
        ),
        card_theme=ft.CardTheme(shape=redondeado),
        dialog_theme=ft.DialogTheme(shape=ft.RoundedRectangleBorder(radius=16)),
        data_table_theme=ft.DataTableTheme(
            heading_text_style=ft.TextStyle(size=12, weight=ft.FontWeight.BOLD, color=ft.Colors.ON_SURFACE_VARIANT),
            divider_thickness=0.5,
        ),
        navigation_rail_theme=ft.NavigationRailTheme(indicator_shape=redondeado),
        scrollbar_theme=ft.ScrollbarTheme(thickness=8, radius=4),
        tooltip_theme=ft.TooltipTheme(wait_duration=400),
    )


def aplicar(page: ft.Page, semilla: str | None = None) -> None:
    """Pone el tema La Loba (claro y oscuro) con la semilla indicada. No llama a update()."""
    page.theme = crear_tema(semilla or COLOR_LA_LOBA)
    page.dark_theme = crear_tema(semilla or COLOR_LA_LOBA)
