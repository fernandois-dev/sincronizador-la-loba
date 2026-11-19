import flet as ft

from modules.servidor.models import MovimientoStock
from pages.generic_page import GenericPage
from utilities.conditions import Conditions


class RegistroStockPage(GenericPage):
    """Solo lectura: cada cambio de stock que el Gestor mandó a Odoo (ver registro_stock.py)."""

    def __init__(self, page: ft.Page, params={}, _model=MovimientoStock):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Registro de Movimientos de Stock"
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.is_chk_column_enabled = False
        self.conditions = Conditions(
            fields_order=["fecha", "origen", "lote", "ref_interna", "producto", "stock_anterior",
                          "valor_ingresado", "tipo", "stock_final", "estado", "detalle", "equipo", "mensaje"],
        )
        self.build_page()
