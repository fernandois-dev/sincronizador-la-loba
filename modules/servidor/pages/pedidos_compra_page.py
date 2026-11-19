import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_unico, tarea_async
from components.loading import Loading
from modules.servidor.odoo import OdooService
from components.estilos import BOTON_EXITO
from components.custom_buttons import CustomButtonCupertino
import datetime


class PedidosCompraPage(PaginaFija, ft.Column):
    titulo = "Pedidos de Compra"
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.loading = Loading(self.page, open=False)
        self.pedidos = []
        self.build_ui()
        # Cargar pedidos automáticamente al iniciar
        self.cargar_pedidos()
        
    def build_ui(self):
        """Construye la interfaz de usuario"""
        
        # Botón para cargar pedidos
        self.btn_cargar = CustomButtonCupertino(
            text="Cargar Pedidos",
            icon=ft.Icons.REFRESH,
            bgcolor=ft.Colors.PRIMARY,
            color=ft.Colors.ON_PRIMARY,
            on_click=self.cargar_pedidos
        )
        
        # Contenedor para la lista de pedidos
        self.lista_pedidos = ft.Column(
            scroll=ft.ScrollMode.AUTO,
            spacing=10,
        )
        
        self.controls = [
            ft.Row([
                self.btn_cargar,
                CustomButtonCupertino(
                    text="Nueva Compra",
                    icon=ft.Icons.ADD_SHOPPING_CART,
                    bgcolor=BOTON_EXITO[0],
                    color=BOTON_EXITO[1],
                    on_click=self.ir_a_nueva_compra
                ),
            ]),
            ft.Divider(),
            ft.Container(
                content=self.lista_pedidos,
                expand=True,
            )
        ]
        
    @tarea_async
    async def cargar_pedidos(self, e=None):
        """Carga los pedidos de compra en estado 'draft' desde Odoo"""
        self.loading.show("Cargando pedidos de compra...")
        await asyncio.sleep(0.05)  # mostrar "Procesando" antes de trabajar
        
        try:
            # Obtener todas las órdenes de compra
            ordenes = await asyncio.to_thread(OdooService.listar_ordenes_compra)
            
            # Filtrar solo las que están en estado 'draft' (Pedido de Compra)
            self.pedidos = [orden for orden in ordenes if orden.get('state') == 'draft']
            
            # Construir la UI con los pedidos
            self.construir_lista_pedidos()
            
        except Exception as ex:
            abrir_unico(self.page, 
                ft.SnackBar(
                    ft.Text(f"Error al cargar pedidos: {str(ex)}"),
                    bgcolor=ft.Colors.ERROR
                )
            )
        finally:
            self.loading.hide()
    
    def construir_lista_pedidos(self):
        """Construye la lista expansible de pedidos"""
        self.lista_pedidos.controls.clear()
        
        if not self.pedidos:
            self.lista_pedidos.controls.append(
                ft.Container(
                    content=ft.Text(
                        "No hay pedidos de compra en estado 'Pedido de Compra'",
                        theme_style=ft.TextThemeStyle.BODY_LARGE,
                        color=ft.Colors.GREY_600
                    ),
                    alignment=ft.Alignment.CENTER,
                    padding=20,
                )
            )
        else:
            for pedido in self.pedidos:
                self.lista_pedidos.controls.append(
                    self.crear_item_pedido(pedido)
                )
        
        self.lista_pedidos.update()
    
    def crear_item_pedido(self, pedido):
        """Crea un item expansible para un pedido"""
        
        # Información del pedido
        pedido_id = pedido.get('id')
        nombre = pedido.get('name', 'Sin nombre')
        proveedor = pedido.get('partner_id', ['', 'Sin proveedor'])[1] if pedido.get('partner_id') else 'Sin proveedor'
        fecha = pedido.get('date_order', '')
        total = pedido.get('amount_total', 0)
        neto = pedido.get('amount_untaxed', 0)
        iva = pedido.get('amount_tax', 0)
        
        # Formatear fecha
        if fecha:
            try:
                fecha_obj = datetime.datetime.fromisoformat(fecha.replace('Z', '+00:00'))
                fecha_formato = fecha_obj.strftime('%d/%m/%Y')
            except:
                fecha_formato = fecha
        else:
            fecha_formato = 'Sin fecha'
        
        # Contenedor para los detalles (inicialmente vacío)
        detalle_container = ft.Container(
            visible=False,
            padding=ft.Padding.only(left=40, top=10, bottom=10),
        )
        
        # Función para expandir/contraer
        def toggle_expansion(e):
            if not detalle_container.visible:
                # Cargar detalles si no están cargados
                if not detalle_container.content:
                    self.cargar_detalle_pedido(pedido_id, detalle_container)
                detalle_container.visible = True
                icono_expansion.icon = ft.Icons.EXPAND_LESS
            else:
                detalle_container.visible = False
                icono_expansion.icon = ft.Icons.EXPAND_MORE
            
            e.control.update()
            detalle_container.update()
            icono_expansion.update()
        
        # Ícono de expansión
        icono_expansion = ft.Icon(
            icon=ft.Icons.EXPAND_MORE,
            size=20,
        )
        
        # Cabecera del pedido (clickeable)
        cabecera = ft.Container(
            content=ft.Row([
                icono_expansion,
                ft.Column([
                    ft.Text(f"{nombre} - {proveedor}", weight=ft.FontWeight.BOLD, size=14),
                    ft.Row([
                        ft.Text(f"Fecha: {fecha_formato}", size=12, color=ft.Colors.ON_SURFACE_VARIANT),
                        ft.VerticalDivider(width=20),
                        ft.Text(f"Neto: ${self.formato_chileno(neto)}", size=12),
                        ft.Text(f"IVA: ${self.formato_chileno(iva)}", size=12),
                        ft.Text(f"Total: ${self.formato_chileno(total)}", size=12, weight=ft.FontWeight.BOLD),
                    ], spacing=10),
                ], spacing=5),
            ], spacing=10),
            padding=15,
            bgcolor=ft.Colors.BLUE_50,
            border_radius=8,
            on_click=toggle_expansion,
            ink=True,
        )
        
        # Contenedor completo del item
        return ft.Column([
            cabecera,
            detalle_container,
        ], spacing=0)
    
    def cargar_detalle_pedido(self, pedido_id, container):
        """Carga el detalle de productos de un pedido"""
        try:
            resultado = OdooService.obtiene_detalle_compra_odoo(pedido_id)
            
            if resultado.get('state') == 'S':
                detalles = resultado.get('detalle', [])
                
                if not detalles:
                    container.content = ft.Text(
                        "No hay productos en este pedido",
                        color=ft.Colors.GREY_600,
                        italic=True
                    )
                else:
                    # Crear tabla con los productos
                    rows = []
                    for detalle in detalles:
                        producto_nombre = detalle.get('product_id', ['', 'Sin nombre'])[1] if detalle.get('product_id') else 'Sin nombre'
                        cantidad = detalle.get('product_qty', 0)
                        precio_unit = detalle.get('price_unit', 0)
                        subtotal = cantidad * precio_unit
                        
                        rows.append(
                            ft.DataRow(cells=[
                                ft.DataCell(ft.Text(producto_nombre, size=12)),
                                ft.DataCell(ft.Text(self.formato_chileno(cantidad), size=12)),
                                ft.DataCell(ft.Text(f"${self.formato_chileno(precio_unit)}", size=12)),
                                ft.DataCell(ft.Text(f"${self.formato_chileno(subtotal)}", size=12, weight=ft.FontWeight.BOLD)),
                            ])
                        )
                    
                    tabla = ft.DataTable(
                        columns=[
                            ft.DataColumn(ft.Text("Producto", weight=ft.FontWeight.BOLD)),
                            ft.DataColumn(ft.Text("Cantidad", weight=ft.FontWeight.BOLD)),
                            ft.DataColumn(ft.Text("Precio Unit.", weight=ft.FontWeight.BOLD)),
                            ft.DataColumn(ft.Text("Subtotal", weight=ft.FontWeight.BOLD)),
                        ],
                        rows=rows,
                        border=ft.Border.all(1, ft.Colors.GREY_300),
                        border_radius=5,
                        vertical_lines=ft.BorderSide(1, ft.Colors.GREY_200),
                        horizontal_lines=ft.BorderSide(1, ft.Colors.GREY_200),
                    )
                    
                    container.content = ft.Column([
                        ft.Text("Productos:", weight=ft.FontWeight.BOLD, size=13),
                        tabla,
                    ], spacing=10)
            else:
                container.content = ft.Text(
                    f"Error: {resultado.get('msg', 'Error desconocido')}",
                    color=ft.Colors.ERROR
                )
                
        except Exception as ex:
            container.content = ft.Text(
                f"Error al cargar detalles: {str(ex)}",
                color=ft.Colors.ERROR
            )
    
    def ir_a_nueva_compra(self, e=None):
        """Navega a la página de nueva compra"""
        self.page.custom_go("/servidor/nueva_compra?return_to=/servidor/pedidos_compra")
    
    def formato_chileno(self, valor):
        """Formatea un número al formato chileno"""
        try:
            valor_float = float(valor) if valor is not None else 0.0
        except (ValueError, TypeError):
            valor_float = 0.0
        
        return "{:,.0f}".format(valor_float).replace(",", "X").replace(".", ",").replace("X", ".")
