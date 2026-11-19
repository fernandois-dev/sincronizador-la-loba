# from .views import hoja_a4_view, sincroniza_stock_view

from modules.servidor.pages.lista_ordenes_compra_page import ListaOrdenesCompraPage
from modules.servidor.views.impresion_a4_view import impresion_a4_view
# from modules.servidor.views.sincroniza_stock_view import sincroniza_stock_view
from modules.servidor.views.correlativo_codigo_view import correlativo_codigo_view
# from modules.servidor.views.sincroniza_precio_view import sincroniza_precio_view
# from modules.servidor.views.sincroniza_barcode_view import sincroniza_barcode_view
# from modules.servidor.views.sincroniza_abastecimiento_view import sincroniza_abastecimiento_view
from modules.servidor.pages.sincroniza_precio_page import SincronizaPrecioPage
from modules.servidor.pages.sincroniza_barcode_page import SincronizaBarcodePage
from modules.servidor.pages.ajuste_stock_page import AjusteStockPage
from modules.servidor.pages.nuevo_stock_page import NuevoStockPage
from modules.servidor.pages.sincroniza_abastecimiento_page import SincronizaAbastecimientoPage
from modules.servidor.pages.impresion_barcode_page import ImpresionBarcodePage
from modules.servidor.pages.sincroniza_nuevos_productos_page import SincronizaNuevosProductosPage
from modules.servidor.pages.sincroniza_descripcion_page import SincronizaDescripcionPage
from modules.servidor.pages.sincroniza_activo_page import SincronizaActivoPage
from modules.servidor.pages.sincroniza_proveedores_page import SincronizaProveedoresPage
from modules.servidor.pages.compras_page import ComprasPage
from modules.servidor.pages.ordenes_compra_page import OrdenesCompraPage
from modules.servidor.pages.reportes.venta_ultimos_meses_page import VentaUltimosMesesPage
from modules.servidor.pages.reportes.compras_page import ComprasPage
from modules.servidor.pages.reportes.reporte_movimientos_page import ReporteMovimientosPage
from modules.servidor.pages.reportes.ventas_semanales_page import VentasSemanalesPage
from modules.servidor.pages.pedidos_compra_page import PedidosCompraPage
from modules.servidor.pages.reportes.reporte_stock_page import ReporteStockPage
from modules.servidor.pages.reportes.bajo_stock_page import BajoStockPage
from modules.servidor.pages.sincroniza_favoritos_page import SincronizaFavoritosPage
from modules.servidor.pages.ajuste_stock_favoritos_page import AjusteStockFavoritosPage
from modules.servidor.pages.registro_stock_page import RegistroStockPage
from modules.servidor.pages.desactivados_page import DesactivadosPage

from modules.servidor.pages.nueva_compra import NuevaCompra
from modules.servidor.pages.inicio_page import InicioPage
from modules.servidor.pages.log_page import LogPage
from modules.servidor.pages.server_config_page import ServerConfigPage
from modules.servidor.pages.mercado_libre_page import MercadoLibrePage


routes = {
    "/codigos_de_barra/hoja_a4": impresion_a4_view,
    "/codigos_de_barra/correlativo": correlativo_codigo_view,
    "/sincronizacion/precio": SincronizaPrecioPage,
    "/sincronizacion/barcode": SincronizaBarcodePage,
    "/sincronizacion/descripcion": SincronizaDescripcionPage,
    "/sincronizacion/nuevos_productos": SincronizaNuevosProductosPage,
    "/sincronizacion/abastecimiento": SincronizaAbastecimientoPage,
    "/sincronizacion/proveedores": SincronizaProveedoresPage,
    "/sincronizacion/favorito": SincronizaFavoritosPage,
    "/sincronizacion/desactivados": DesactivadosPage,
    "/codigos_de_barra/zebra": ImpresionBarcodePage,
    "/sincronizacion/activo": SincronizaActivoPage,
    "/stock/ajustes": AjusteStockPage,
    "/stock/nuevo_stock": NuevoStockPage,
    "/stock/ajuste_favoritos": AjusteStockFavoritosPage,
    "/stock/registro": RegistroStockPage,
    "/compras/orden_compra": NuevaCompra,
    "/compras/listado_ordenes_compra": ListaOrdenesCompraPage,
    "/compras/pedidos": PedidosCompraPage,
    "/reportes/venta_ultimos_meses": VentaUltimosMesesPage,
    "/reportes/ventas_semanales": VentasSemanalesPage,
    "/reportes/compras": ComprasPage,
    "/reportes/movimientos": ReporteMovimientosPage,
    "/inicio": InicioPage,
    "/reportes/stock": ReporteStockPage,
    "/reportes/bajo_stock": BajoStockPage,
    "/sistema/log": LogPage,
    "/sistema/configuracion": ServerConfigPage,
    "/mercado_libre/productos": MercadoLibrePage,
}
