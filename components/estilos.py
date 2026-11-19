"""
Estilos compartidos de la aplicación.

Centraliza colores por significado y radios para que todas las ventanas se vean
iguales y respeten el tema (claro/oscuro y color semilla elegido por el usuario).
"""
import flet as ft


# ─── Radios ────────────────────────────────────────────────────────────────────

RADIO_BOTON = 6
RADIO_TARJETA = 10
RADIO_CHIP = 99


# ─── Variantes de botón (fondo, texto) ─────────────────────────────────────────
# Usar siempre colores del tema para que se adapten al modo oscuro.

BOTON_PRIMARIO = (ft.Colors.PRIMARY, ft.Colors.ON_PRIMARY)            # acción principal de la ventana
BOTON_SECUNDARIO = (ft.Colors.SECONDARY_CONTAINER, ft.Colors.ON_SECONDARY_CONTAINER)  # acciones de apoyo
BOTON_ODOO = (ft.Colors.TERTIARY, ft.Colors.ON_TERTIARY)               # todo lo que trae datos desde Odoo
BOTON_EXITO = (ft.Colors.GREEN_700, ft.Colors.WHITE)                   # exportar, activar, crear
BOTON_PELIGRO = (ft.Colors.ERROR, ft.Colors.ON_ERROR)                  # eliminar, desactivar, limpiar
BOTON_NEUTRO = (ft.Colors.SURFACE_CONTAINER_HIGHEST, ft.Colors.ON_SURFACE)  # filtros, ver detalle
