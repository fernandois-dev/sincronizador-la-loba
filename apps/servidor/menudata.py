import flet as ft


class ControlGroup:
    def __init__(self, name: str, label: str, icon: str, selected_icon: str = None, children: list = None, color: str = None):
        self.name = name
        self.label = label
        self.icon = icon
        self.selected_icon = selected_icon or icon
        self.children = children or []
        self.color = color

    def add_child(self, child):
        self.children.append(child)


class MenuData:
    def __init__(self):
        self.control_groups = self.get_control_groups()

    def titulo_de_ruta(self, ruta: str) -> str:
        """Nombre de la ruta según el menú ("/reportes/stock" → "Reportes · Stock")."""
        nombre = (ruta or "").strip("/")
        for grupo in self.control_groups:
            if grupo.name == nombre:
                return grupo.label
            for hijo in grupo.children:
                if hijo.name == nombre:
                    return f"{grupo.label} · {hijo.label}"
        return ""

    def get_control_groups(self):
        return [
            ControlGroup(
                name="inicio",
                label="Inicio",
                icon=ft.Icons.HOME,
                selected_icon=ft.Icons.HOME_OUTLINED,
            ),
            ControlGroup(
                name="codigos_de_barra",
                label="Codigos de Barra",
                icon=ft.Icons.PRINT,
                selected_icon=ft.Icons.PRINT_OUTLINED,
                children=[
                    ControlGroup(
                        name="codigos_de_barra/hoja_a4",
                        label="Hoja A4",
                        icon=ft.Icons.AUTO_STORIES,
                        selected_icon=ft.Icons.AUTO_STORIES,
                    ),
                    ControlGroup(
                        name="codigos_de_barra/zebra",
                        label="Zebra",
                        icon=ft.Icons.BARCODE_READER,
                        selected_icon=ft.Icons.BARCODE_READER,
                    ),
                    ControlGroup(
                        name="codigos_de_barra/correlativo",
                        label="Correlativo",
                        icon=ft.Icons.FORMAT_LIST_NUMBERED,
                        selected_icon=ft.Icons.FORMAT_LIST_NUMBERED_OUTLINED,
                    ),
                ],
            ),
            ControlGroup(
                name="sincronizacion",
                label="Sincronización",
                icon=ft.Icons.SYNC,
                selected_icon=ft.Icons.SYNC_OUTLINED,
                children=[
                    ControlGroup(
                        name="sincronizacion/precio",
                        label="Precio",
                        icon=ft.Icons.PRICE_CHECK,
                        selected_icon=ft.Icons.PRICE_CHECK,
                    ),
                    ControlGroup(
                        name="sincronizacion/barcode",
                        label="Códigos de Barra",
                        icon=ft.Icons.BARCODE_READER,
                        selected_icon=ft.Icons.BARCODE_READER,
                    ),
                    ControlGroup(
                        name="sincronizacion/descripcion",
                        label="Descripciones",
                        icon=ft.Icons.DESCRIPTION,
                        selected_icon=ft.Icons.DESCRIPTION_OUTLINED,
                    ),
                    ControlGroup(
                        name="sincronizacion/abastecimiento",
                        label="Abastecimiento",
                        icon=ft.Icons.SHOP,
                        selected_icon=ft.Icons.SHOP_OUTLINED,
                    ),
                    ControlGroup(
                        name="sincronizacion/proveedores",
                        label="Proveedores",
                        icon=ft.Icons.LOCAL_SHIPPING,
                        selected_icon=ft.Icons.LOCAL_SHIPPING_OUTLINED,
                    ),
                    ControlGroup(
                        name="sincronizacion/nuevos_productos",
                        label="Nuevos Productos",
                        icon=ft.Icons.MY_LIBRARY_ADD,
                        selected_icon=ft.Icons.MY_LIBRARY_ADD_OUTLINED,
                    ),
                    ControlGroup(
                        name="sincronizacion/favorito",
                        label="Favorito",
                        icon=ft.Icons.STAR,
                        selected_icon=ft.Icons.STAR_OUTLINED,
                        color=ft.Colors.YELLOW_900,
                    ),
                    ControlGroup(
                        name="sincronizacion/desactivados",
                        label="Desactivados",
                        icon=ft.Icons.CANCEL,
                        selected_icon=ft.Icons.CANCEL_OUTLINED,
                        color=ft.Colors.RED_900,
                    ),
                ],
            ),
            ControlGroup(
                name="mercado_libre",
                label="Mercado Libre",
                icon=ft.Icons.STOREFRONT,
                selected_icon=ft.Icons.STOREFRONT_OUTLINED,
                children=[
                    ControlGroup(
                        name="mercado_libre/productos",
                        label="Productos ML",
                        icon=ft.Icons.SELL,
                        selected_icon=ft.Icons.SELL_OUTLINED,
                        color=ft.Colors.AMBER_800,
                    ),
                ],
            ),
            ControlGroup(
                name="stock",
                label="Stock",
                icon=ft.Icons.STORAGE,
                selected_icon=ft.Icons.STORAGE_OUTLINED,
                children=[
                    ControlGroup(
                        name="stock/ajustes",
                        label="Ajustes de Stock",
                        icon=ft.Icons.STORAGE,
                        selected_icon=ft.Icons.STORAGE_OUTLINED,
                    ),
                    ControlGroup(
                        name="stock/nuevo_stock",
                        label="Nuevo Stock",
                        icon=ft.Icons.ADD,
                        selected_icon=ft.Icons.ADD_OUTLINED,
                    ),
                    ControlGroup(
                        name="stock/ajuste_favoritos",
                        label="Ajuste Favoritos",
                        icon=ft.Icons.STAR_HALF,
                        selected_icon=ft.Icons.STAR_HALF,
                        color=ft.Colors.ORANGE_700,
                    ),
                    ControlGroup(
                        name="stock/registro",
                        label="Registro de Movimientos",
                        icon=ft.Icons.HISTORY,
                        selected_icon=ft.Icons.HISTORY,
                    ),
                ],
            ),
            ControlGroup(
                name="compras",
                label="Compras",
                icon=ft.Icons.SHOP,
                selected_icon=ft.Icons.SHOP_OUTLINED,
                children=[
                    # ControlGroup(
                    #     name="compras/pedidos",
                    #     label="Compras Sugeridas",
                    #     icon=ft.Icons.SHOPPING_BAG_SHARP,
                    #     selected_icon=ft.Icons.SHOPPING_BAG_SHARP,
                    # ),
                    ControlGroup(
                        name="compras/listado_ordenes_compra",
                        label="Compras",
                        icon=ft.Icons.LIST,
                        selected_icon=ft.Icons.LIST_OUTLINED,
                    ),
                    ControlGroup(
                        name="compras/orden_compra",
                        label="Nueva Compra",
                        icon=ft.Icons.ADD_SHOPPING_CART,
                        selected_icon=ft.Icons.ADD_SHOPPING_CART_OUTLINED,
                    ),
                    
                ],
            ),
            ControlGroup(
                name="reportes",
                label="Reportes",
                icon=ft.Icons.REPORT,
                selected_icon=ft.Icons.REPORT_OUTLINED,
                children=[
                    ControlGroup(
                        name="reportes/venta_ultimos_meses",
                        label="Reporte de Ventas últimos meses",
                        icon=ft.Icons.STORAGE,
                        selected_icon=ft.Icons.STORAGE_OUTLINED,
                    ),
                    ControlGroup(
                        name="reportes/ventas_semanales",
                        label="Reporte de Ventas por semana",
                        icon=ft.Icons.BAR_CHART,
                        selected_icon=ft.Icons.BAR_CHART,
                    ),
                    ControlGroup(
                        name="reportes/compras",
                        label="Reporte de Compras",
                        icon=ft.Icons.SHOPPING_BAG_SHARP,
                        selected_icon=ft.Icons.SHOPPING_BAG_SHARP,
                    ),
                    ControlGroup(
                        name="reportes/movimientos",
                        label="Reporte de Movimientos",
                        icon=ft.Icons.SWAP_HORIZ,
                        selected_icon=ft.Icons.SWAP_HORIZ,
                    ),
                    ControlGroup(
                        name="reportes/stock",
                        label="Reporte de Stock",
                        icon=ft.Icons.STORAGE,
                        selected_icon=ft.Icons.STORAGE_OUTLINED,
                    ),
                    ControlGroup(
                        name="reportes/bajo_stock",
                        label="Bajo Stock Favoritos",
                        icon=ft.Icons.INVENTORY_2,
                        selected_icon=ft.Icons.INVENTORY_2,
                        color=ft.Colors.ORANGE_800,
                    ),
                ],
            ),
            ControlGroup(
                name="sistema",
                label="Sistema",
                icon=ft.Icons.SETTINGS,
                selected_icon=ft.Icons.SETTINGS_OUTLINED,
                children=[
                    ControlGroup(
                        name="sistema/log",
                        label="Log",
                        icon=ft.Icons.ARTICLE_OUTLINED,
                        selected_icon=ft.Icons.ARTICLE,
                    ),
                    ControlGroup(
                        name="sistema/configuracion",
                        label="Configuración",
                        icon=ft.Icons.SETTINGS,
                        selected_icon=ft.Icons.SETTINGS_OUTLINED,
                    ),
                ],
            ),
        ]

