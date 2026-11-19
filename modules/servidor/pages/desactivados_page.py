import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, tarea_async
from components.generic_inputs import GenericSearchField
from components.loading import Loading
from modules.servidor.business_logic import OdooSyncManager
from modules.servidor.data_manage import DataManage
from components.estilos import BOTON_EXITO, BOTON_PELIGRO
from components.custom_buttons import CustomButtonCupertino, CustomIconButton, boton_cargar_datos, boton_cargar_odoo, boton_exportar
from modules.servidor.google_sheet import GoogleService
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import HojasSeleccionadas, OdooProveedor
from modules.servidor.odoo import OdooService

class DesactivadosPage(PaginaFija, ft.Column):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.row_height = 35
        self.loading = Loading(self.page, open=False)
        self.data_original = []
        self.data_filtrada = []
        self.proveedor_id = None
        self.data_proveedores: list[OdooProveedor] = []
        self.estado_seleccionado = None
        self.selected_ids = set()
        self.get_proveedores()
        self.build_ui()
        
        # Colores para los estados
        self.colores_estados = {
            "PARA VENTA": ft.Colors.GREEN_400,
            "DESACTIVADOS": ft.Colors.RED_400,
            "DESHABILITADO": ft.Colors.GREY_400
        }
        
        # Control de ordenamiento
        self.orden_actual = {"campo": "activo", "direccion": "asc"}
        # Cargar datos iniciales de forma segura (sin llamar update() antes de montar)
        # Cargamos los desactivados por defecto
        self.cargar_datos(activo=False)

    def _safe_update(self, control):
        try:
            if getattr(control, "page", None):
                control.update()
        except Exception:
            # Ignorar actualizaciones tempranas antes del montaje
            pass
    
    def get_proveedores(self):
        """Obtiene la lista de proveedores desde Odoo"""
        try:
            self.data_proveedores = DataManage.get_proveedores_con_productos()
        except Exception as e:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error al obtener proveedores: {e}")))
            self.data_proveedores = []
    
    def did_mount(self):
        # verificamos si hay alguna hoja seleccionada en la tabla HojasSeleccionadas
        proveedor = None
        try:
            hojas = HojasSeleccionadas.objects.all()
            if hojas.exists() and hojas.count() == 1:
                hoja = hojas.first()
                # obtengo el id desde la hoja
                sheet_proveedor = GoogleService.get_proveedor(hoja.hoja)
                proveedor = OdooProveedor.objects.filter(id=sheet_proveedor["id"]).first()
            # self.page.update()
        except Exception as e:
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Error al cargar configuración de hoja: {e}"))) 
        finally:
            pass
        if proveedor:
            # se deja none en favoritos
            self.filtro_proveedor.set_initial_value(value=proveedor.name, data={"id": proveedor.id, "name": proveedor.name})
            self.filtro_proveedor.update()
    
    def build_ui(self):
        # Filtros
        self.filtro_proveedor = GenericSearchField(
            name="proveedor",
            page=self.page,
            label="Proveedor",
            width=400,
            on_change=self.handle_on_change,
            handle_search=lambda val: self.buscar_proveedor(val)
        )
        
        self.filtro_estado = ft.Dropdown(
            label="Filtrar por",
            width=150,
            text_size=12,
            text_style=ft.TextStyle(size=10),
            options=[
                ft.DropdownOption("TODOS", "TODOS"),
                ft.DropdownOption("PARA VENTA", "PARA VENTA"),
                ft.DropdownOption("DESACTIVADOS", "DESACTIVADOS"),
            ],
            value="TODOS"
        )
        
        self.filtro_producto = ft.TextField(
            label="Buscar Producto",
            width=250,
            height=35,
            text_size=12,
            on_submit=lambda e: self.cargar_datos()
        )
        
        self.btn_cargar_odoo = boton_cargar_odoo(self._ejecutar_carga_odoo_products, height=35)
        
        self.btn_cargar = boton_cargar_datos(self.cargar_datos, height=35)
        
        self.btn_activar_venta = CustomButtonCupertino(
            text="Activar Venta",
            icon=ft.Icons.CHECK_CIRCLE,
            width=140,
            height=35,
            on_click=lambda e: self.toggle_activo_selected(True),
            bgcolor=BOTON_EXITO[0],
            color=BOTON_EXITO[1],
            visible=False
        )
        
        self.btn_desactivar_venta = CustomButtonCupertino(
            text="Desactivar Venta",
            icon=ft.Icons.CANCEL,
            width=140,
            height=35,
            on_click=lambda e: self.toggle_activo_selected(False),
            bgcolor=BOTON_PELIGRO[0],
            color=BOTON_PELIGRO[1],
            visible=False
        )
        
        self.btn_exportar = boton_exportar(self.exportar_excel, height=35)
        
        # Contenedor de filtros
        self.filtros_container = ft.Row(
            [
                self.filtro_proveedor,
                self.filtro_producto,
                self.btn_cargar,
            ],
            spacing=10,
            wrap=True
        )
        
        # Tabla
        self.tabla = self.build_table()
        
        # Estadísticas
        self.resumen_desactivados = ft.Text(
            "Desactivados para productos seleccionados: 0",
            size=13,
            weight=ft.FontWeight.W_600,
            color=ft.Colors.BLUE_800
        )

        self.stats_container = ft.Row(
            [],
            spacing=15,
            wrap=True
        )
        
        # Layout principal
        self.spacing = 0
        self.controls = [
            ft.Container(
                content=ft.Column([
                    ft.Row(
                        controls=[
                            ft.Text("Gestión de Productos Desactivados (Sale Ok)", size=24, weight=ft.FontWeight.BOLD),
                            self.btn_cargar_odoo,
                            self.btn_activar_venta,
                            self.btn_desactivar_venta,
                            ], 
                        alignment=ft.MainAxisAlignment.START),
                    
                    ft.Divider(height=2, color=ft.Colors.BLUE_700)
                ]),
                padding=10
            ),
            ft.Container(
                content=self.filtros_container,
                padding=10
            ),
            ft.Divider(),
            ft.Container(
                content=ft.Column(
                    controls=[
                        self.resumen_desactivados,
                        self.stats_container
                    ],
                    spacing=8
                ),
                padding=10
            ),
            ft.Column(
                controls=[self.tabla],
                expand=True,
                scroll=ft.ScrollMode.AUTO
            )
        ]
        
    def buscar_proveedor(self, text_busqueda):
        ret = []
        for proveedor in self.data_proveedores:
            if text_busqueda.lower() in proveedor.name.lower():
                ret.append({"id": proveedor.id, "name": proveedor.name})
        return ret
        
    def handle_on_change(self, e=None, value=None):
        if value:
            self.proveedor_id = value
            self.cargar_datos()
            return
        if e:
            self.proveedor_id = e.control.data
            self.cargar_datos()
            return
        self.proveedor_id = None
        
    def _ejecutar_carga_odoo_products(self, e=None):
        return OdooSyncManager.cargar_productos_odoo(
            loading_widget=self.loading,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def update_filtered_view(self):
        self.filtro_proveedor.value = ""
        self.filtro_producto.value = ""
        self.filtro_estado.value = "TODOS"
        self.proveedor_id = None
        self.data_original = []
        self.data_filtrada = []
        self.actualizar_tabla()
        self.actualizar_estadisticas()
        
    def build_table(self):
        return ft.DataTable(
            columns=[
                ft.DataColumn(
                    label=ft.GestureDetector(
                        content=ft.Row([
                            ft.Text("Producto", size=12, weight=ft.FontWeight.BOLD),
                            ft.Icon(ft.Icons.ARROW_DOWNWARD, size=12, visible=False)
                        ], spacing=5),
                        on_tap=lambda e: self.ordenar_por("producto")
                    )
                ),
                ft.DataColumn(
                    ft.Text("Proveedor", size=12, weight=ft.FontWeight.BOLD)
                ),
                ft.DataColumn(
                    ft.Text("Precio", size=12, weight=ft.FontWeight.BOLD),
                    numeric=True
                ),
                ft.DataColumn(
                    label=ft.GestureDetector(
                        content=ft.Row([
                            ft.Text("Estado Venta", size=12, weight=ft.FontWeight.BOLD),
                            ft.Icon(ft.Icons.ARROW_DOWNWARD, size=12, visible=True)
                        ], spacing=5),
                        on_tap=lambda e: self.ordenar_por("activo")
                    )
                ),
            ],
            rows=[],
            border=ft.Border.all(1, ft.Colors.GREY_400),
            border_radius=10,
            vertical_lines=ft.BorderSide(1, ft.Colors.GREY_300),
            horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_300),
            heading_row_color=ft.Colors.BLUE_GREY_100,
            heading_row_height=45,
            data_row_min_height=self.row_height,
            data_row_max_height=self.row_height,
            column_spacing=10,
            show_checkbox_column=True,
        )
        
    @tarea_async
    async def cargar_datos(self, e=None, activo: bool = None):
        try:
            self.loading.show("Generando Reporte...")
            await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
            self.estado_seleccionado = None
            self.filtro_estado.value = "TODOS"
            self.selected_ids.clear()
            self.actualizar_botones_accion()
            
            proveedor_id = self.proveedor_id["id"] if self.proveedor_id else None
            producto = self.filtro_producto.value.strip() if self.filtro_producto.value.strip() else None
            
            # Obtener datos del reporte (activo=False por defecto si es la carga inicial)
            self.data_original = await asyncio.to_thread(DataManage.productos_proveedor, proveedor_id, producto, activo=activo)

            MAX_RECORDS = 1000
            if isinstance(self.data_original, list) and len(self.data_original) > MAX_RECORDS:
                abrir_dialogo(self.page, 
                    ft.SnackBar(
                        content=ft.Text(f"Se limitaron los resultados a {MAX_RECORDS} registros para mejorar el rendimiento."),
                        bgcolor=ft.Colors.ORANGE_700
                    )
                )
                self.data_original = self.data_original[:MAX_RECORDS]
            
            if not self.data_original:
                abrir_dialogo(self.page, 
                    ft.SnackBar(
                        content=ft.Text("No se encontraron datos"),
                        bgcolor=ft.Colors.ORANGE_700
                    )
                )
                return
            
            proveevores_nombres = set()
            for item in self.data_original:
                if item.get("partner"):
                    proveevores_nombres.add(item["partner"])
            
            self.data_filtrada = self.data_original.copy()
            self.orden_actual = {"campo": "activo", "direccion": "asc"}
            self.ordenar_datos()
            self.actualizar_tabla()
            self.actualizar_estadisticas()
            
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Se cargaron {len(self.data_original)} registros"),
                    bgcolor=ft.Colors.GREEN_700
                )
            )
            
        except Exception as ex:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Error al cargar datos: {str(ex)}"),
                    bgcolor=ft.Colors.RED_700
                )
            )
        finally:
            self.loading.hide()
            
    def aplicar_filtros(self, e=None):
        if not self.data_original:
            return
            
        self.data_filtrada = []
        estado_filtro = self.filtro_estado.value
        
        for item in self.data_original:
            es_activo = item.get("activo", False)
            if estado_filtro == "TODOS":
                pass
            elif estado_filtro == "PARA VENTA" and not es_activo:
                continue
            elif estado_filtro == "DESACTIVADOS" and es_activo:
                continue
                
            self.data_filtrada.append(item)
        
        self.actualizar_tabla()
        self.actualizar_estadisticas()
        
    def ordenar_por(self, campo):
        if not self.data_filtrada:
            return
            
        if self.orden_actual["campo"] == campo:
            self.orden_actual["direccion"] = "desc" if self.orden_actual["direccion"] == "asc" else "asc"
        else:
            self.orden_actual["campo"] = campo
            self.orden_actual["direccion"] = "asc"
            
        self.ordenar_datos()
        self.actualizar_tabla()
        
    def ordenar_datos(self):
        if not self.data_filtrada:
            return
            
        campo = self.orden_actual["campo"]
        direccion = self.orden_actual["direccion"]
        reverso = (direccion == "desc")
        
        if campo == "activo":
            self.data_filtrada.sort(
                key=lambda x: x.get("activo", False),
                reverse=reverso
            )
        else:
            self.data_filtrada.sort(
                key=lambda x: (x.get(campo, "") or "").upper(),
                reverse=reverso
            )
        
    def actualizar_tabla(self):
        self.tabla.rows.clear()
        
        columnas_ordenables = {
            0: "producto",
            3: "activo"
        }
        
        for idx, campo in columnas_ordenables.items():
            col = self.tabla.columns[idx]
            if hasattr(col.label, 'content') and isinstance(col.label.content, ft.Row):
                row = col.label.content
                if len(row.controls) > 1:
                    icon_widget = row.controls[1]
                    if campo == self.orden_actual["campo"]:
                        icon_widget.visible = True
                        icon_widget.icon = ft.Icons.ARROW_UPWARD if self.orden_actual["direccion"] == "desc" else ft.Icons.ARROW_DOWNWARD
                    else:
                        icon_widget.visible = False
        
        for item in self.data_filtrada:
            item_id = item.get("id")
            es_activo = item.get("activo", False)
            icono = ft.Icons.CHECK_CIRCLE if es_activo else ft.Icons.CANCEL
            color_icono = ft.Colors.GREEN if es_activo else ft.Colors.RED
            
            # Nombre del producto con estrella si es favorito
            nombre_producto = item.get("producto", "")
            if item.get("favorito"):
                content_producto = ft.Row([
                    ft.Icon(ft.Icons.STAR, color=ft.Colors.YELLOW_700, size=16),
                    ft.Text(nombre_producto, size=11, max_lines=2, expand=True)
                ], spacing=5, alignment=ft.MainAxisAlignment.START)
            else:
                content_producto = ft.Text(nombre_producto, size=11, max_lines=2)

            row = ft.DataRow(
                cells=[
                    ft.DataCell(content_producto),
                    ft.DataCell(ft.Text(item.get("proveedor", ""), size=11)),
                    ft.DataCell(ft.Text(f"${item.get('precio', 0):,.0f}", size=11)),
                    ft.DataCell(
                        ft.Icon(
                            icono,
                            size=20,
                            color=color_icono
                        )
                    ),
                ],
                selected=item_id in self.selected_ids,
                on_select_change=lambda e, i_id=item_id: self.handle_selection_change(e, i_id),
            )
            self.tabla.rows.append(row)
            
        self._safe_update(self.tabla)

    def handle_selection_change(self, e, item_id):
        is_selected = str(e.data).lower() == "true"
        if is_selected:
            self.selected_ids.add(item_id)
        else:
            self.selected_ids.discard(item_id)
        
        e.control.selected = is_selected
        self._safe_update(e.control)
        self.actualizar_botones_accion()

    def actualizar_botones_accion(self):
        if not self.selected_ids:
            self.btn_activar_venta.visible = False
            self.btn_desactivar_venta.visible = False
        else:
            seleccionados = [item for item in self.data_original if item.get("id") in self.selected_ids]
            todos_activos = all(item.get("activo", False) for item in seleccionados)
            todos_desactivados = all(not item.get("activo", False) for item in seleccionados)
            
            self.btn_activar_venta.visible = todos_desactivados
            self.btn_desactivar_venta.visible = todos_activos
            
        self._safe_update(self.btn_activar_venta)
        self._safe_update(self.btn_desactivar_venta)

    def toggle_activo_selected(self, activar: bool):
        try:
            from modules.servidor.models import OdooProducto
            ids_guardados_correctamente = []

            for item_id in self.selected_ids:
                ret = OdooService.set_sale_ok_productos(
                    producto_id=item_id,
                    sale_ok=activar
                )
                if ret["state"] == "S":
                    OdooProducto.objects.filter(id=item_id).update(activo=activar)
                    for item in self.data_original:
                        if item.get("id") == item_id:
                            item["activo"] = activar
                    ids_guardados_correctamente.append(item_id)

            if len(ids_guardados_correctamente) < len(self.selected_ids):
                abrir_dialogo(self.page, 
                    ft.SnackBar(
                        content=ft.Text(f"Algunos productos no se pudieron actualizar en Odoo."),
                        bgcolor=ft.Colors.ORANGE_700
                    )
                )

            for item in self.data_original:
                if item.get("id") in ids_guardados_correctamente:
                    item["activo"] = activar
            
            for item in self.data_filtrada:
                if item.get("id") in ids_guardados_correctamente:
                    item["activo"] = activar
            
            self.selected_ids.clear()
            self.actualizar_tabla()
            self.actualizar_botones_accion()
            self.actualizar_estadisticas()
            
            mensaje = "Productos activados para venta" if activar else "Productos desactivados para venta"
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"{mensaje} ({len(ids_guardados_correctamente)} productos)"),
                    bgcolor=ft.Colors.GREEN_700
                )
            )
        except Exception as ex:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Error al actualizar estado: {str(ex)}"),
                    bgcolor=ft.Colors.RED_700
                )
            )
        
    def actualizar_estadisticas(self):
        if not self.data_original:
            self.stats_container.controls.clear()
            self.resumen_desactivados.value = "Desactivados para productos seleccionados: 0"
            self._safe_update(self.resumen_desactivados)
            self._safe_update(self.stats_container)
            return
            
        conteo = {"PARA VENTA": 0, "DESACTIVADOS": 0}
        for item in self.data_original:
            if item.get("activo", False):
                conteo["PARA VENTA"] += 1
            else:
                conteo["DESACTIVADOS"] += 1

        self.resumen_desactivados.value = (
            f"Desactivados para productos seleccionados: {conteo['DESACTIVADOS']} "
            f"de {len(self.data_original)} productos"
        )
        self._safe_update(self.resumen_desactivados)
                
        self.stats_container.controls.clear()
        
        for estado, cantidad in conteo.items():
            color = self.colores_estados.get(estado, ft.Colors.BLUE_400)
            border_style = ft.Border.all(2, ft.Colors.BLACK) if self.estado_seleccionado == estado else None
            card = ft.Container(
                content=ft.Column([
                    ft.Text(estado, size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                    ft.Text(str(cantidad), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
                ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
                bgcolor=color,
                padding=15,
                border_radius=10,
                width=150,
                height=80,
                border=border_style,
                on_click=lambda e, est=estado: self._filtrar_por_estado(est)
            )
            self.stats_container.controls.append(card)
            
        total_card = ft.Container(
            content=ft.Column([
                ft.Text("TOTAL", size=14, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE),
                ft.Text(str(len(self.data_original)), size=24, weight=ft.FontWeight.BOLD, color=ft.Colors.WHITE)
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=5),
            bgcolor=ft.Colors.BLUE_700,
            padding=15,
            border_radius=10,
            width=120,
            height=80,
            on_click=lambda e: self._filtrar_por_estado(None)
        )
        self.stats_container.controls.append(total_card)
        self._safe_update(self.stats_container)

    def _filtrar_por_estado(self, estado):
        if estado is None:
            self.estado_seleccionado = None
            self.filtro_estado.value = "TODOS"
        else:
            if self.estado_seleccionado == estado:
                self.estado_seleccionado = None
                self.filtro_estado.value = "TODOS"
            else:
                self.estado_seleccionado = estado
                self.filtro_estado.value = estado

        self.aplicar_filtros()
        
    def exportar_excel(self, e=None):
        if not self.data_filtrada:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text("No hay datos para exportar"),
                    bgcolor=ft.Colors.ORANGE_700
                )
            )
            return
            
        try:
            import pandas as pd
            from datetime import datetime
            
            # Crear DataFrame
            df = pd.DataFrame(self.data_filtrada)
            
            # Seleccionar y renombrar columnas
            columnas = {
                'producto': 'Producto',
                'proveedor': 'Proveedor',
                'precio': 'Precio',
                'activo': 'Es Vendible (Sale Ok)'
            }
            
            df = df[list(columnas.keys())]
            df.rename(columns=columnas, inplace=True)
            
            # Generar nombre de archivo con timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"reporte_desactivados_{timestamp}.xlsx"
            
            # Guardar a Excel
            df.to_excel(filename, index=False, engine='openpyxl')
            
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Archivo exportado: {filename}"),
                    bgcolor=ft.Colors.GREEN_700
                )
            )
            
        except ImportError:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text("Instalar pandas y openpyxl para exportar: pip install pandas openpyxl"),
                    bgcolor=ft.Colors.ORANGE_700
                )
            )
        except Exception as ex:
            abrir_dialogo(self.page, 
                ft.SnackBar(
                    content=ft.Text(f"Error al exportar: {str(ex)}"),
                    bgcolor=ft.Colors.RED_700
                )
            )
