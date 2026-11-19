from utilities.flet_compat import PaginaFija, abrir_dialogo
from flet import *
from modules.servidor.odoo import OdooService
import datetime
from components.custom_buttons import CustomButtonCupertino, CustomIconButton

class OrdenesCompraPage(PaginaFija, Column):
    def __init__(self, page: Page, params={}):
        super().__init__()
        self.page = page
        self.proveedor_id = None
        self.fecha_inicio = None
        self.fecha_fin = None
        self.ordenes = []
        self.build_ui()

    def build_ui(self):
        self.fecha_inicio_picker = DatePicker(
            on_change=self.on_filtro_cambio
        )
        self.txt_fecha_inicio = TextField(
            label="Fecha inicio",
            on_change=self.on_filtro_cambio,
            read_only=True,
            width=150,
        )
        self.btn_fecha_inicio_picker = CustomIconButton(
            icon=Icons.CALENDAR_MONTH,
            on_click=lambda e: abrir_dialogo(self.page, 
                self.fecha_inicio_picker
            ),
        )
        self.fecha_fin_picker = DatePicker(
            on_change=self.on_filtro_cambio
        )
        self.txt_fecha_fin = TextField(
            label="Fecha fin",
            on_change=self.on_filtro_cambio,
            read_only=True,
            width=150,
        )
        self.btn_fecha_fin_picker = CustomIconButton(
            icon=Icons.CALENDAR_MONTH,
            on_click=lambda e: abrir_dialogo(self.page, 
                self.fecha_fin_picker
            ),
        )
        self.tabla = DataTable(
            columns=[
                DataColumn(label=Text("ID")),
                DataColumn(label=Text("Proveedor")),
                DataColumn(label=Text("Fecha")),
                DataColumn(label=Text("Estado")),
                DataColumn(label=Text("Total")),
            ],
            rows=[]
        )
        self.controls = [
            Row([
                self.txt_fecha_inicio,
                self.btn_fecha_inicio_picker,
                self.txt_fecha_fin,
                self.btn_fecha_fin_picker
            ]),
            self.tabla
        ]
        self.update_tabla()

    def on_filtro_cambio(self, e=None):
        self.proveedor_id = None
        self.fecha_inicio = self.fecha_inicio_picker.value
        self.txt_fecha_inicio.value = str(self.fecha_inicio)
        self.fecha_fin = self.fecha_fin_picker.value
        self.txt_fecha_fin.value = str(self.fecha_fin)
        self.update_tabla()
        self.page.update()
        
    def update_tabla(self):
        self.ordenes = OdooService.listar_ordenes_compra(
            proveedor_id=None,
            fecha_inicio=self.fecha_inicio,
            fecha_fin=self.fecha_fin
        )
        self.tabla.rows = [
            DataRow(cells=[
                DataCell(Text(str(o['id']))),
                DataCell(Text(o['partner_id'][1] if o['partner_id'] else "")),
                DataCell(Text(o['date_order'][:10] if o['date_order'] else "")),
                DataCell(Text(o['state'])),
                DataCell(Text(str(o['amount_total']))),
            ]) for o in self.ordenes
        ]