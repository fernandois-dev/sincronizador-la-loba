import asyncio
import datetime
import flet as ft

from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo, tarea_async
from logger_config import get_logger
from modules.servidor import registro_stock
from modules.servidor.models import Comparativa

logger = get_logger(__name__)

class DlgConfirmacionSincronizacion(PaginaFija, ft.AlertDialog):
    def __init__(self, page: ft.Page, 
                 filas_a_actualizar: list,  
                 fields: list[str],

                 fn_sincronizar: callable, fn_continuar: callable,
                 fn_finalizar: callable = None, aviso: str = None, detalle: str = "") -> None:
        """
        fn_finalizar: opcional, se llama una vez terminado el lote (p. ej. para
        escribir en la planilla); si devuelve {"state", "msg"} se agrega al registro.
        aviso: opcional, texto de advertencia que se muestra sobre la tabla.
        detalle: opcional, cómo se armó la selección; queda en el registro de
        movimientos de stock junto a cada producto del lote.
        """
        super().__init__()
        self.modal=True
        self.title=ft.Text("Confirmar Sincronización")
        self.page = page
        self.fn_sincronizar = fn_sincronizar
        self.fn_continuar = fn_continuar
        self.fn_finalizar = fn_finalizar
        self.detalle = detalle

        self.fields = fields
        self.filas_a_actualizar = filas_a_actualizar

        self.btn_cancelar = ft.TextButton("Cancelar", on_click=lambda e: self.close())
        self.btn_sincronizar = ft.TextButton("Sincronizar", on_click=lambda e: self.sincronizar_precios(filas_a_actualizar))
        self.btn_continuar = ft.TextButton("Continuar", on_click=lambda e: self.continuar_sincronizacion(), visible=False)

        self.rows = self.build_rows_sincronizacion()
        
        self.dlg_table = self.build_dlg_table()
        
        self.log_column = self.build_log_column()
        self.log_content = self.build_log_content()

        botones = ft.Row(
            controls=[
                self.btn_cancelar,
                self.btn_sincronizar,
                self.btn_continuar
            ],
            alignment=ft.MainAxisAlignment.END,
        )
        
        self.content=ft.Container(
            ft.Column(
                controls=[
                    ft.Text(f"Se sincronizarán {len(filas_a_actualizar)} productos con diferencias."),
                    *([ft.Container(
                        content=ft.Text(aviso, size=12, selectable=True),
                        bgcolor=ft.Colors.with_opacity(0.15, ft.Colors.AMBER),
                        border_radius=6,
                        padding=8,
                    )] if aviso else []),
                    self.dlg_table,
                    self.log_content,
                    botones
                ],
                expand=True,
                alignment=ft.MainAxisAlignment.START,
            ),
            width=600,
            height=400,
            expand=True,
        )
        # abrir_dialogo(self.page, self)
        
    def close(self):
        """
        Cierra el diálogo y actualiza la página.
        """
        cerrar_dialogo(self.page, self)
        self.page.update()

    def continuar_sincronizacion(self):
        """
        Función para continuar después de la sincronización.
        """
        cerrar_dialogo(self.page, self)
        self.page.update()
        abrir_dialogo(self.page, ft.SnackBar(ft.Text("Sincronización completada.")))
        self.fn_continuar()

    def build_rows_sincronizacion(self):
        """Genera las filas para la tabla de sincronización de forma dinámica basada en self.fields"""
        return [
            ft.DataRow(cells=[
            ft.DataCell(
                # Verificar si el valor es booleano
                ft.Checkbox(
                    value=getattr(obj, field, False),
                    disabled=True,  # Solo lectura
                    scale=0.8  # Hacer el checkbox más pequeño
                ) if isinstance(getattr(obj, field, None), bool) else ft.Text(str(getattr(obj, field, '')))
                
                ) for field in self.fields
        ]) for obj in self.filas_a_actualizar
        ]
        
    def build_columns_sincronizacion(self):
        """Genera las columnas de la tabla de forma dinámica basada en self.fields"""
        # Mapeo de nombres de campos a títulos más legibles
        field_titles = {
            'producto': 'Producto',
            'tb_precio': 'Precio Tabla Base',
            'odoo_precio': 'Precio Odoo',
            'tb_min': 'Mín TB',
            'odoo_min': 'Mín O',
            'tb_max': 'Máx TB',
            'odoo_max': 'Máx O',
            'tb_barcode': 'Código TB',
            'odoo_barcode': 'Código Odoo',
            'ref_interna': 'Ref. Interna',
            'existe': 'Existe',
            'desc_ok': 'Desc. OK',
            'producto': 'Descripción T.B.',
            'odoo_producto': 'Descripción Odoo',
        }
        
        return [
            ft.DataColumn(ft.Text(field_titles.get(field, field.replace('_', ' ').title())))
            for field in self.fields
        ]
        
    def build_log_column(self):
        """
        Construye la columna de log para mostrar los mensajes de sincronización.
        """
        return ft.Column(
            expand=True,
            spacing=4,
            alignment=ft.MainAxisAlignment.START,
            horizontal_alignment=ft.MainAxisAlignment.START,
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=True,
        )

    def build_log_content(self):
        """
        Construye el contenido del log.
        """
        return ft.Container(
            content=ft.Row(
                controls=[
                    ft.SelectionArea(self.log_column)
                ],
                expand=True,
                scroll=ft.ScrollMode.ALWAYS,  # Permite scroll horizontal para líneas largas (ej. tracebacks)
            ),
            bgcolor=ft.Colors.OUTLINE_VARIANT,
            expand=True,
            border_radius=ft.BorderRadius.all(10),
            alignment=ft.Alignment.TOP_LEFT,
            padding=ft.Padding.all(10),
            visible=False,  # Inicialmente oculto
        )
        
    def build_dlg_table(self):
        """
        Construye la tabla de diálogo con los productos a sincronizar de forma dinámica.
        """
        return ft.Column(controls=[
            ft.DataTable(
                columns=self.build_columns_sincronizacion(),
                rows=self.rows,
            )],
            scroll=ft.ScrollMode.ALWAYS,
            auto_scroll=True,
            visible=True,
            alignment= ft.MainAxisAlignment.START,
            horizontal_alignment = ft.MainAxisAlignment.START,
            expand=True,
        )
        
    @tarea_async
    async def sincronizar_precios(self, filas_a_actualizar: list[Comparativa]):
        """
        Función para sincronizar los precios entre la tabla base y Odoo.
        """
        self.btn_cancelar.visible = False
        self.btn_sincronizar.visible = False

        self.btn_continuar.visible = True
        self.btn_continuar.disabled = True

        self.dlg_table.visible = False
        self.log_content.visible = True
        self.page.update()

        proceso_ok = True
        ok_count = 0
        err_count = 0

        logger.info("Sincronización confirmada por el usuario. Total a procesar: %d", len(filas_a_actualizar))

        with registro_stock.lote(self.detalle):
            for fila in filas_a_actualizar:
                resultado = await asyncio.to_thread(self.fn_sincronizar, fila)
                self.build_single_log_msg(fila.producto, resultado)
                if resultado.get("state") == "S":
                    ok_count += 1
                else:
                    proceso_ok = False
                    err_count += 1

        if self.fn_finalizar:
            try:
                resultado = await asyncio.to_thread(self.fn_finalizar)
            except Exception as e:
                logger.error("Error en el cierre de la sincronización.", exc_info=True)
                resultado = {"state": "E", "msg": f"Error al finalizar: {e}"}
            if resultado:
                self.build_single_log_msg("Otras hojas del producto", resultado)
                if resultado.get("state") == "E":
                    proceso_ok = False

        logger.info("Sincronización finalizada. OK: %d | Errores: %d", ok_count, err_count)

        if not proceso_ok:
            logger.warning("Se registraron %d errores durante la sincronización.", err_count)
            abrir_dialogo(self.page, ft.SnackBar(ft.Text(f"Se registraron errores al sincronizar en Odoo.", bgcolor=ft.Colors.ERROR)))

        self.btn_continuar.disabled = False
        self.btn_continuar.update()
        self.page.update()
            
    def build_single_log_msg(self, producto, msg):
        fecha = datetime.datetime.now().strftime("%d-%m-%Y %H:%M:%S")
        texto = f'{fecha} - {producto} \n {msg["msg"]}'
        # no_wrap para que las líneas largas (ej. tracebacks) no se corten: el
        # Row contenedor tiene scroll horizontal, así se pueden ver completas.
        if msg["state"] == "S":
            control = ft.Text(texto, style=ft.TextStyle(size=11), selectable=True, no_wrap=True)
        elif msg["state"] == "W":
            control = ft.Text(texto, style=ft.TextStyle(size=11), selectable=True, no_wrap=True, bgcolor=ft.Colors.with_opacity(color=ft.Colors.YELLOW, opacity=0.2))
        else: # E => Error
            control = ft.Text(texto, style=ft.TextStyle(size=11), selectable=True, no_wrap=True, bgcolor=ft.Colors.RED_900)
        self.log_column.controls.append(control)
        self.log_column.update()