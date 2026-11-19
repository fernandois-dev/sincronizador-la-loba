import configparser
import datetime
import os
from components.custom_buttons import CustomButtonCupertino
from components.loading import Loading
from modules.servidor.business_logic import TablaBaseManager
from modules.servidor.components.dlg_confirmacion_sincronizacion import DlgConfirmacionSincronizacion
from modules.servidor.components.dlg_selecciona_hoja_google import DlgSeleccionaHojaGoogle
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from modules.servidor.printer import PrinterZebra
from pages.generic_page import GenericPage
import flet as ft
from utilities.flet_compat import abrir_dialogo, abrir_unico, cerrar_dialogo
from components.custom_buttons import boton_cargar_tb, boton_recargar_tb

from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions
from utilities import carpeta_datos



class ImpresionBarcodePage(GenericPage):
    def __init__(self, page: ft.Page, params={}, _model=TablaBase):
        super().__init__(page=page, params=params, _model=_model)
        self.titulo = "Impresión de Códigos de Barras"
        # self.custom_queryset = self.get_filtered_queryset()
        self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = False
        self.conditions = Conditions(
            fields_order=["ref_interna", "descripcion", "precio", "barcode"],
        )
        self.custom_actions = self.build_custom_actions()
        
        self.input_cantidad_codigos = self.build_input_cantidad_codigos()
        self.dlg_impresion_set_cantidad = self.build_dlg_impresion_set_cantidad()
        
        self.table_previa_productos = self.build_table_previa_productos()
        self.dlg_impresion_preview = self.build_dlg_impresion_preview()
        
        self.dlg_impresion = self.build_dlg_impresion()
        self.printer = PrinterZebra(printer_name=self.get_printer_name())

        self.page.update()
        self.build_page()
        
        self.component_chips.chip_delete_all_callback = lambda: self.limpiar_tablas()
        for hoja in TablaBaseManager.obtener_hojas_seleccionadas():
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))

    def build_page(self):
        super().build_page()
        self.page.update()
        

    def build_input_cantidad_codigos(self):
        return ft.TextField(
            label="Cantidad de codigos a imprimir",
            autofocus=True,
            on_submit=lambda e: self.siguiente_paso_dlg_impresion(e),
        )

    def build_dlg_impresion_set_cantidad(self):
        return ft.Container(
            ft.Column(
                [
                    ft.Text("Los impresion de codigos de barra se basa en la tabla y contempla solo los productos seleccionados y que cuyos codigos de barra empiecen con LL.", size=11),
                    ft.Container(
                        content=self.input_cantidad_codigos,
                            expand=True
                        ),
                        ft.Row(
                            [
                                CustomButtonCupertino(
                                    "Cancelar",
                                    icon=ft.Icons.CANCEL,
                                    on_click=lambda e: cerrar_dialogo(self.page, self.dlg_impresion),
                                    bgcolor=ft.Colors.SECONDARY,
                                    color=ft.Colors.ON_SECONDARY,
                                    height=40,
                                ),
                                CustomButtonCupertino(
                                    "Siguiente",
                                    icon=ft.Icons.ARROW_FORWARD,
                                    on_click=lambda e: self.siguiente_paso_dlg_impresion(e),
                                    bgcolor=ft.Colors.PRIMARY,
                                    color=ft.Colors.ON_PRIMARY,
                                    height=40,
                                ),
                            ],
                            spacing=10,
                            alignment=ft.MainAxisAlignment.END,
                        ),
                        
                    ],
                    spacing=10,
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=20,
                alignment=ft.Alignment.TOP_CENTER,
                width=600,
                height=500,
                visible=True,  # Inicialmente visible
            )

    def build_dlg_impresion_preview(self):
        return ft.Container(
            ft.Column(
                [
                    ft.Text("Vista Previa de Productos", size=14, weight=ft.FontWeight.BOLD ),
                    ft.Container(
                        content=ft.Column(
                                controls=[self.table_previa_productos],
                                height=300,
                                scroll=ft.ScrollMode.AUTO
                            ),
                            expand=True
                        ),
                        ft.Row(
                            [
                                
                                CustomButtonCupertino(
                                    "Cancelar",
                                    icon=ft.Icons.CANCEL,
                                    on_click=lambda e: cerrar_dialogo(self.page, self.dlg_impresion),
                                    bgcolor=ft.Colors.SECONDARY,
                                    color=ft.Colors.ON_SECONDARY,
                                    height=40,
                                ),
                                CustomButtonCupertino(
                                    "Imprimir",
                                    icon=ft.Icons.ARROW_FORWARD,
                                    on_click=lambda e: self.imprime_codigo_barras(),
                                    bgcolor=ft.Colors.PRIMARY,
                                    color=ft.Colors.ON_PRIMARY,
                                    height=40,
                                    autofocus=True,  # Enfoca este botón al abrir el diálogo
                                
                                ),
                            ],
                            spacing=10,
                            alignment=ft.MainAxisAlignment.END,
                        ),
                        
                    ],
                    spacing=10,
                    alignment=ft.MainAxisAlignment.START,
                ),
                padding=20,
                alignment=ft.Alignment.TOP_CENTER,
                width=600,
                height=500,
                visible=False,  # Inicialmente oculto
            )
        
    def build_dlg_impresion(self):
        
        return ft.AlertDialog(
            title=ft.Text("Impresión de códigos de barras"),
            content=ft.Row(
            controls=[
                self.dlg_impresion_set_cantidad,
                self.dlg_impresion_preview,
            ],
        ),
        )

    def build_table_previa_productos(self):
        return ft.DataTable(
            expand=True,
            columns=[
                ft.DataColumn(ft.Text("Producto")),
                ft.DataColumn(ft.Text("Codigo Barras")),
                ft.DataColumn(ft.Text("Cantidad"), numeric=True),
            ],
    )
    
    def get_filtered_queryset(self):
        """Retorna el queryset filtrado para mostrar solo productos con precios distintos"""
        return TablaBase.objects.all()

    def build_custom_actions(self):
        return [
            {
                'text': 'Imprimir Códigos de Barras',
                'icon': ft.Icons.SYNC,
                'function': lambda e: self.imprimir_codigos_barras(e)
            },
        ]
    
    def siguiente_paso_dlg_impresion(self, e):

        if not self.input_cantidad_codigos.value.isdigit() or int(self.input_cantidad_codigos.value) <= 0:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text("Por favor, ingrese una cantidad válida de códigos a imprimir.")))
            self.input_cantidad_codigos.focus()
            return

        if self.table.get_header_chk_column().value:
            productos_seleccionados = [obj for obj in self.table.get_all_objects() if obj.barcode and str(obj.barcode).strip()]
        else:
            productos_seleccionados = [row for row in self.table.get_selectd_objects() if row.barcode and str(row.barcode).strip()]

        self.table_previa_productos.rows = []
        for producto in productos_seleccionados:
            self.table_previa_productos.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(producto.descripcion[0:28])),
                        ft.DataCell(ft.Text(producto.barcode)),
                        ft.DataCell(ft.Text(self.input_cantidad_codigos.value)),
                    ]
                )
            )

        self.dlg_impresion_preview.visible = True
        self.dlg_impresion_set_cantidad.visible = False

        self.table_previa_productos.update()
        self.dlg_impresion.update()

        self.page.update()

    def imprimir_codigos_barras(self, lista_de_productos):
        try:
            if self.table.get_header_chk_column().value:
                filas_a_actualizar = [obj for obj in self.table.get_all_objects() if obj.barcode and str(obj.barcode).strip()]
            else:
                filas_a_actualizar = [obj for obj in lista_de_productos if obj.barcode and str(obj.barcode).strip()]
            
            
        # Abre el diálogo de impresión si no ha sido abierto
            self.dlg_impresion_set_cantidad.visible = True
            self.dlg_impresion_preview.visible = False
            self.input_cantidad_codigos.value = ""
            if not self.dlg_impresion.open:
                abrir_dialogo(self.page, self.dlg_impresion)
            else:
                abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos con codigos para imprimir.")))
                return
        except Exception as e:
            # Ocultar loading en caso de error
            self.loading.hide()
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error al imprimir códigos de barras: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def get_printer_name(self):
        """Obtiene el nombre de la impresora configurada en server_settings.cfg"""
        config_path = str(carpeta_datos.ruta("server_settings.cfg"))
        config = configparser.ConfigParser()
        carpeta_datos.leer_ini(config, config_path)
        return config.get("IMPRESORA", "nombre", fallback="zebra")

    def enviar_a_impresora(self, fila):
        self.printer.create_data([
            {"producto":fila.producto, 
             "codigo": fila.barcode, 
             "cantidad": int(fila.cantidad)}])

    def build_custom_buttons(self):
        """Construye los botones personalizados para la página"""
        return [
            boton_cargar_tb(lambda e: DlgSeleccionaHojaGoogle(self.page, fn_yes=self.carga_tabla_base)),
            boton_recargar_tb(lambda e: self.recargar_tabla_base()),
        ]
        
    def carga_tabla_base(self, hojas_seleccionadas):
        self.component_chips.remove_all_chips()
        """Carga la tabla base usando el manager de lógica de negocio"""
        for hoja in hojas_seleccionadas:
            self.component_chips.add_chip(hoja, on_delete=lambda e, h=hoja: self.eliminar_chip(h))
        
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def recargar_tabla_base(self):
        """Recarga la tabla base usando el manager de lógica de negocio"""
        return TablaBaseManager.cargar_tabla_base(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def gestiona_hojas_seleccionadas(self, hojas_seleccionadas):
        """ Guarda las hojas seleccionadas en la base de datos
        """
        HojasSeleccionadas.objects.all().delete()
        listo_obj = [
            HojasSeleccionadas(hoja=hoja)
            for hoja in hojas_seleccionadas
        ]
        # Guardamos todas las reglas de una vez
        HojasSeleccionadas.objects.bulk_create(listo_obj)

    def update_filtered_view(self):
        """Actualiza la vista con el queryset filtrado después de cambios en los datos"""
        self.table.clear_cache()
        # Aplicar el queryset según el estado actual del filtro
        if self.is_filtered:
            # Mantener el filtro activo
            self.set_custom_queryset(self.get_filtered_queryset())
        else:
            # Mantener mostrando todos
            self.set_custom_queryset(TablaBase.objects.all())

    def eliminar_chip(self, hoja):
        """Elimina una hoja de la lista de chips y actualiza la base de datos"""
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Hoja {hoja} eliminada.")))
        
        # Obtener hojas actuales excepto la que se va a eliminar
        # hojas_restantes = [h.data for h in self.chips if h.data != hoja]
        self.component_chips.remove_chip(hoja)
        TablaBaseManager.elimina_hoja_seleccionada(
            hoja,
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        return TablaBaseManager.limpiar_tablas(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )

    def imprime_codigo_barras(self):
        # obtine la cantidad de codigos a imprimir desde la tabla
        # productos_seleccionados = []
        # for row in table.get_selectd_objects():
        #     productos_seleccionados.append({"producto":row.producto, "codigo": row.tb_barcode, "cantidad": int(input_cantidad_codigos.value)})
            
        # # filtra a los productos cullos codigos de barras empiezan con "LL"
        # productos_seleccionados = [row for row in productos_seleccionados if str(row["codigo"]).startswith("LL")]

        if self.table.get_header_chk_column().value:
            productos_seleccionados = [obj for obj in self.table.get_all_objects() if obj.barcode and str(obj.barcode).strip()]
        else:
            productos_seleccionados = [row for row in self.table.get_selectd_objects() if row.barcode and str(row.barcode).strip()]

        productos_seleccionados = [{"producto":row.descripcion, "codigo": row.barcode, "cantidad": int(self.input_cantidad_codigos.value)}
                                   for row in productos_seleccionados]


        # llama a la funcion que envia los datos a la impresora
        printer = PrinterZebra(printer_name=self.get_printer_name())
        printer.create_data(productos_seleccionados)
        abrir_dialogo(self.page, ft.SnackBar(ft.Text("Impresión de códigos de barras iniciada.")))
        cerrar_dialogo(self.page, self.dlg_impresion)
        self.page.update()

