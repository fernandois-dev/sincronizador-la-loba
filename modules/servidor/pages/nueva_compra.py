import asyncio
import datetime
from components.custom_buttons import CustomButtonCupertino
from components.custom_input import DisplayMode, LayoutMode, SearchField
from components.field_builder import FieldBuilder
from components.loading import Loading
from components.steps_modal import StepsModal, StepStatus
from components.not_data_table import NotDataTable
from modules.servidor.business_logic import OdooSyncManager, TablaBaseManager
from modules.servidor.models import Comparativa, Compra, DetalleCompra, HojasSeleccionadas, HojasTablaBase, TablaBase
from modules.servidor.odoo import OdooService
from modules.servidor.google_sheet import GoogleService
from pages.generic_header_detail_form import GenericHeaderDetailForm
from pages.generic_page import GenericPage
from modules.servidor.models import Comparativa
import flet as ft

from utilities import pendientes
from utilities.flet_compat import PaginaFija, abrir_unico, tarea_async
from django.db.models import F
from django.db import transaction

from utilities.conditions import Conditions
from utilities.utilities import num_or_zero

def format_number(number):
    """Formatea un número con puntos como separadores de miles y comas como separadores decimales."""
    return "{:,.0f}".format(number).replace(",", "X").replace(".", ",").replace("X", ".")

class NuevaCompra(PaginaFija, ft.Column):
    def __init__(self, page: ft.Page, params={}):
        super().__init__()
        self.page = page
        self.params = params
        self.titulo = "Nueva Compra"
        self.custom_queryset = None
        # self.custom_buttons = self.build_custom_buttons()
        self.display_btn_edit = False
        self.display_btn_delete = False
        self.display_btn_new = False
        self.display_btn_desactivar = False
        self.loading = Loading(self.page, open=False)
        self.is_filtered = False
        self.cod_proveedor = None

        self.txt_subtotal = ft.Text(f"${format_number(0)}", theme_style=ft.TextThemeStyle.TITLE_MEDIUM)
        self.txt_iva = ft.Text(f"${format_number(0)}", theme_style=ft.TextThemeStyle.TITLE_MEDIUM)
        self.txt_total = ft.Text(f"${format_number(0)}", theme_style=ft.TextThemeStyle.HEADLINE_SMALL, weight=ft.FontWeight.BOLD)
        self.txt_cantidad_productos = ft.Text("0", theme_style=ft.TextThemeStyle.TITLE_MEDIUM)

        self.update_hojas_tabla_base()

        self.obj_compra = Compra()
        self.form = FieldBuilder(
            self.obj_compra, 
            layout_mode=LayoutMode.HORIZONTAL, 
            display_mode=DisplayMode.EDIT,
            conditions=Conditions(
                fields_order=["fecha", "proveedor"],
                overrides_input_type={"proveedor": SearchField },
            )
        )
        self.alignment = ft.MainAxisAlignment.START

        self.table = NotDataTable(
            handle_on_long_press=None,
            on_row_selected=None,
            on_click_column=None,
            conditions=Conditions(
                fields_readonly=["total", "uds_agrupamiento"],
                fields_order=["producto", "cantidad", "uds_agrupamiento", "precio_unitario", "total"],
                overrides_input_type={"producto": SearchField },
                fields_calculations={
                    "precio_unitario": {
                        "depends": ["producto"],
                        "calculation": lambda obj: (
                            obj.producto.precio_mayor
                            if obj.producto_id and num_or_zero(obj.producto.uds_agrupamiento) > 0
                            else (obj.producto.tb_precio_compra if obj.producto_id else 0)
                        )
                    },
                    "uds_agrupamiento": {
                        "depends": ["producto"],
                        "calculation": lambda obj: obj.producto.uds_agrupamiento if obj.producto_id else 0
                    },
                    "total": {
                        "depends": ["precio_unitario", "cantidad"],
                        "calculation": lambda obj: num_or_zero(obj.cantidad) * num_or_zero(obj.precio_unitario),
                        "callback_pos_calculation": self.update_summary
                    },
                }
            ),
            is_chk_column_enabled=False,
            is_editable=True,
            content_modified_callback=self.update_summary,
        )
        self.table.set_model(DetalleCompra)
        self.table.set_data(DetalleCompra.objects.all())
        self.table.create_table()
        self.table.visible = False
        # self.page.update()
        # self.build_page()
        self.controls = [
            ft.Row(
                controls=[
                    ft.Row(
                        controls=[
                            CustomButtonCupertino(
                                "Volver",
                                on_click=lambda e: self.ir_a_listado_compras(),
                                bgcolor=ft.Colors.BLUE_GREY_700,
                                color=ft.Colors.ON_PRIMARY,
                                icon=ft.Icons.ARROW_BACK),
                            CustomButtonCupertino(
                                "Limpiar",
                                on_click=lambda e: self.limpiar_formulario(),
                                bgcolor=ft.Colors.TERTIARY,
                                color=ft.Colors.ON_TERTIARY,
                                icon=ft.Icons.CLEAR),
                            CustomButtonCupertino(
                                "Limpiar Google",
                                on_click=lambda e: self.limpiar_cantidades_google(),
                                bgcolor=ft.Colors.GREEN_700,
                                color=ft.Colors.ON_PRIMARY,
                                icon=ft.Icons.RESTORE_FROM_TRASH),
                            CustomButtonCupertino(
                                "Guardar", 
                                on_click=lambda e: self.guardar_formulario(), 
                                bgcolor=ft.Colors.PRIMARY, 
                                color=ft.Colors.ON_PRIMARY, 
                                icon=ft.Icons.SAVE),
                        ]
                    ),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            ),
            ft.Divider(),
            ft.Row(
                controls=[
                    ft.Container(self.form, height=70),
                    CustomButtonCupertino("Obtener Productos", on_click=lambda e: self.cargar_productos(), bgcolor=ft.Colors.OUTLINE_VARIANT, color=ft.Colors.ON_SURFACE_VARIANT, icon=ft.Icons.UPLOAD_FILE),
                ]
            ),
            ft.Column(controls=[self.table], expand=True, scroll=ft.ScrollMode.AUTO),
            ft.Divider(),
            ft.Container(
                content=ft.Row(
                    alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                    controls=[
                        ft.Row(
                            alignment=ft.MainAxisAlignment.START,
                            controls=[
                                ft.Text("Productos a agregar: ", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                                self.txt_cantidad_productos,
                            ],
                        ),
                        ft.Column(
                            controls=[
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.END,
                                    controls=[
                                        ft.Text("Subtotal (Neto): ", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                                        self.txt_subtotal
                                    ]
                                ),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.END,
                                    controls=[
                                        ft.Text("IVA (19%): ", theme_style=ft.TextThemeStyle.TITLE_MEDIUM),
                                        self.txt_iva
                                    ]
                                ),
                                ft.Row(
                                    alignment=ft.MainAxisAlignment.END,
                                    controls=[
                                        ft.Text("TOTAL: ", theme_style=ft.TextThemeStyle.HEADLINE_SMALL),
                                        self.txt_total
                                    ]
                                ),
                            ],
                            spacing=5,
                        ),
                    ],
                ),
                padding=ft.Padding.only(right=20, top=10, bottom=30),
            ),
        ]
        self.revisar_condiciones_iniciales()

    def ir_a_listado_compras(self):
        """Navega al listado de órdenes de compra."""
        self.page.custom_go(self._build_listado_compras_route(reload=False))

    def _build_listado_compras_route(self, reload: bool = False) -> str:
        """Construye la ruta al listado de compras con opción de recargar."""
        route = "/compras/listado_ordenes_compra"
        if reload:
            return f"{route}?reload=1"
        return route

    def revisar_condiciones_iniciales(self):
        # si solo hay una empresa seleccionada la tabla pasa a visible y se setea la empresa en el formulario
        empresas = HojasSeleccionadas.objects.all()
        if len(empresas) == 1:
            self.empresa = empresas[0].hoja
            self.cod_proveedor = empresas[0].proveedor_id
            # La hoja puede no estar en HojasTablaBase (por ejemplo si se cargó una pestaña
            # que no está en la lista de proveedores): en ese caso no se preselecciona.
            hoja_tabla_base = HojasTablaBase.objects.filter(nombre=empresas[0].hoja).first()
            if hoja_tabla_base:
                self.form.get_field_by_name("proveedor").set_initial_value(empresas[0].hoja, data=hoja_tabla_base)
            # self.table.set_data(self.crea_detalle_inicial())
            # self.table.build_body()
            # self.table.visible = True
            # neto_inicial = self.calcula_total_inicial()
            # iva_inicial = neto_inicial * 0.19
            # total_inicial = neto_inicial + iva_inicial
            
            # self.txt_subtotal.value = f"${format_number(neto_inicial)}"
            # self.txt_iva.value = f"${format_number(iva_inicial)}"
            # self.txt_total.value = f"${format_number(total_inicial)}"
        else:
            self.table.visible = False
        self.page.update()
        
    def calcula_total_linea(self, obj):
        return num_or_zero(obj.cantidad) * num_or_zero(obj.precio_unitario)

    def calcula_total(self, items):
        """Calcula el total de la compra."""
        return sum(self.calcula_total_linea(item) for item in items)

    def update_summary(self, e=None):
        """Actualiza el subtotal, IVA y total en el cuadro resumen"""
        items = self.table.get_all_objects()
        neto = self.calcula_total(items)
        iva = neto * 0.19
        total = neto + iva
        cantidad_productos = sum(1 for item in items if num_or_zero(item.cantidad) > 0)
        
        self.txt_subtotal.value = f"${format_number(neto)}"
        self.txt_iva.value = f"${format_number(iva)}"
        self.txt_total.value = f"${format_number(total)}"
        self.txt_cantidad_productos.value = str(cantidad_productos)
        
        self.txt_subtotal.update()
        self.txt_iva.update()
        self.txt_total.update()
        self.txt_cantidad_productos.update()

    @tarea_async
    async def cargar_productos(self):
        chk = self.form.full_clean()
        if not chk:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Por favor, complete los campos obligatorios.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        hojas_seleccionadas = [self.form.get_field_by_name("proveedor").value]
        self.loading.show("Cargando productos...")
        await TablaBaseManager.limpiar_tablas.ahora(page=self.page, update_view_callback=self.update_filtered_view)
        # Carga la tabla base y espera el resultado
        tb_cargada = await TablaBaseManager.cargar_tabla_base.ahora(
            hojas_seleccionadas=hojas_seleccionadas, page=self.page, update_view_callback=self.update_filtered_view)
        if not tb_cargada:
            self.loading.hide()
            return
        
        empresas = HojasSeleccionadas.objects.all()
        if len(empresas) == 1:
            self.empresa = empresas[0].hoja
            self.cod_proveedor = empresas[0].proveedor_id
        
        cantidad = Comparativa.objects.count()
        if cantidad == 0:
            abrir_unico(self.page, ft.SnackBar(ft.Text("No se encontraron productos en la tabla base para el proveedor seleccionado.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            self.table.visible = False
            self.loading.hide()
            self.page.update()
            return
        self.table.visible = True
        # limpia tabla
        self.table.set_data(self.crea_detalle_inicial())
        self.table.build_body()
        self.table.visible = True
        
        neto_inicial = self.calcula_total_inicial()
        iva_inicial = neto_inicial * 0.19
        total_inicial = neto_inicial + iva_inicial
        
        self.txt_subtotal.value = f"${format_number(neto_inicial)}"
        self.txt_iva.value = f"${format_number(iva_inicial)}"
        self.txt_total.value = f"${format_number(total_inicial)}"
        self.txt_cantidad_productos.value = str(sum(1 for item in self.table.get_all_objects() if num_or_zero(item.cantidad) > 0))
        
        self.loading.hide()
        abrir_unico(self.page, ft.SnackBar(ft.Text(f"Se cargaron {cantidad} productos desde la tabla base.")))
        self.page.update()
        
    def limpiar_tablas(self):
        """Limpia las tablas usando el manager de lógica de negocio"""
        return TablaBaseManager.limpiar_tablas(
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
        
    def update_filtered_view(self):
        pass
    
    @tarea_async
    async def limpiar_cantidades_google(self, e=None):
        """Limpia las celdas de cantidad de compra en Google Sheets para los productos cargados"""
        if not hasattr(self, 'empresa') or not self.empresa:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Debe seleccionar un proveedor primero.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        detalles = self.table.get_all_objects()
        if not detalles:
            abrir_unico(self.page, ft.SnackBar(ft.Text("No hay productos cargados para limpiar.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        self.loading.show("Limpiando cantidades en Google Sheets...")
        try:
            lista_productos = [line.producto.producto for line in detalles]
            ret = await asyncio.to_thread(GoogleService.limpia_celdas_cant_compra, self.empresa, lista_productos)
            
            if ret and ret[0]['state'] == 'S':
                await self._marcar_compradas([line.producto for line in detalles])
                abrir_unico(self.page, ft.SnackBar(ft.Text(ret[0]['msg'], color=ft.Colors.ON_PRIMARY), bgcolor=ft.Colors.PRIMARY))
            else:
                msg = ret[0].get('msg', 'Error desconocido') if ret else "Error al procesar"
                abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error: {msg}", color=ft.Colors.ERROR), bgcolor=ft.Colors.ERROR))
        except Exception as ex:
            abrir_unico(self.page, ft.SnackBar(ft.Text(f"Error inesperado: {str(ex)}", color=ft.Colors.ERROR), bgcolor=ft.Colors.ERROR))
        finally:
            self.loading.hide()
            self.page.update()

    def guardar_formulario(self):
        # Validaciones previas en el hilo principal (sin abrir modal todavía)
        if not self.form.full_clean():
            abrir_unico(self.page, ft.SnackBar(ft.Text("Por favor, complete los campos obligatorios.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        proveedor_id = self.cod_proveedor
        fecha = self.form.get_field_by_name("fecha").value
        detalles = self.table.get_all_objects()

        if not proveedor_id or not detalles:
            abrir_unico(self.page, ft.SnackBar(ft.Text("Debe seleccionar un proveedor y agregar productos.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        if not self.table.full_clean():
            abrir_unico(self.page, ft.SnackBar(ft.Text("Por favor, corrija los errores en los detalles de la compra.", color=ft.Colors.ON_ERROR), bgcolor=ft.Colors.ERROR))
            return

        # Abrir modal de progreso
        modal = StepsModal(self.page, title="Guardando compra")
        modal.add_step("Registrar compra en Odoo")
        modal.add_step("Limpiar cantidades en Google Sheets")
        modal.show()

        async def _proceso():
            # --- PASO 1: Odoo ---
            modal.set_step_status(0, StepStatus.IN_PROGRESS)
            try:
                proveedor_odoo = await asyncio.to_thread(OdooService.buscar_proveedor_odoo, proveedor_id)
                if not proveedor_odoo:
                    modal.set_step_status(0, StepStatus.ERROR, "Proveedor no encontrado en Odoo.")
                    modal.show_close_button()
                    return

                order_lines = []
                for detalle in detalles:
                    producto_odoo = await asyncio.to_thread(OdooService.buscar_producto_odoo, detalle.producto.producto_id)
                    if not producto_odoo:
                        modal.set_step_status(0, StepStatus.ERROR, f"Producto '{detalle.producto.producto}' no encontrado en Odoo.")
                        modal.show_close_button()
                        return
                    uds = num_or_zero(detalle.uds_agrupamiento)
                    if uds > 0:
                        # Compra mayorista: convertir a unidades minoristas
                        qty_odoo = num_or_zero(detalle.cantidad) * uds
                        price_odoo = num_or_zero(detalle.precio_unitario) / uds
                    else:
                        qty_odoo = detalle.cantidad
                        price_odoo = detalle.precio_unitario
                    order_lines.append({
                        'product_id': detalle.producto.producto_id,
                        'name': detalle.producto.producto,
                        'product_qty': qty_odoo,
                        'product_uom': producto_odoo['uom_id'][0],
                        'price_unit': price_odoo,
                        'date_planned': fecha if fecha else datetime.datetime.now().strftime('%Y-%m-%d'),
                    })
                lista_productos = [line['name'] for line in order_lines]

                purchase_id = await asyncio.to_thread(OdooService.crear_orden_compra_odoo, proveedor_odoo['id'])
                purchase_name = await asyncio.to_thread(OdooService.obtiene_name_compra_odoo, purchase_id)
                if not purchase_id:
                    modal.set_step_status(0, StepStatus.ERROR, "Error al crear la orden de compra en Odoo.")
                    modal.show_close_button()
                    return

                detalles_ok = await asyncio.to_thread(OdooService.crear_detalle_orden_compra_odoo, purchase_id, order_lines)
                if not detalles_ok:
                    await asyncio.to_thread(OdooService.cancelar_y_eliminar_orden_compra_odoo, purchase_id)
                    modal.set_step_status(0, StepStatus.ERROR, "Error al agregar los detalles a la orden de compra.")
                    modal.show_close_button()
                    return

                await asyncio.to_thread(OdooService.confirmar_orden_compra_odoo, purchase_id)
                await asyncio.to_thread(OdooService.validar_recepcion_odoo, purchase_name)
                modal.set_step_status(0, StepStatus.SUCCESS)

            except Exception as e:
                modal.set_step_status(0, StepStatus.ERROR, str(e))
                modal.show_close_button()
                return

            # --- PASO 2: Google Sheets ---
            # La compra ya está creada en Odoo. Un error aquí NO deshace la compra.
            max_retries = 3
            google_error = None
            for attempt in range(1, max_retries + 1):
                step_name = (
                    "Limpiar cantidades en Google Sheets"
                    if attempt == 1
                    else f"Limpiar cantidades en Google Sheets (intento {attempt}/{max_retries})"
                )
                modal.set_step_name(1, step_name)
                modal.set_step_status(1, StepStatus.IN_PROGRESS)
                google_error = None
                try:
                    ret = await asyncio.to_thread(GoogleService.limpia_celdas_cant_compra, self.empresa, lista_productos)
                    if ret and ret[0]['state'] != 'S':
                        google_error = ret[0].get('msg', 'Error desconocido')
                    else:
                        google_error = None
                except Exception as ex_google:
                    google_error = str(ex_google)

                if google_error is None:
                    break  # éxito, salir del loop

            if google_error:
                modal.set_step_status(1, StepStatus.ERROR, f"{google_error} — Use 'Limpiar Google' para reintentar.")
                # No navegar: el cliente necesita poder usar el botón "Limpiar Google"
                modal.show_close_button()
            else:
                await self._marcar_compradas([d.producto for d in detalles])
                modal.set_step_status(1, StepStatus.SUCCESS)
                # Al cerrar el modal se navega al listado
                modal.show_close_button(on_close=lambda: (self.limpiar_formulario(), self.page.custom_go(self._build_listado_compras_route(reload=True))))

        self.page.run_task(_proceso)

    async def _marcar_compradas(self, productos: list[Comparativa]):
        """Deja en 0 la cantidad a comprar en la base local, igual que se hizo en Google Sheets.

        Sin esto, el contador de "Compras" del Inicio y del menú (pendientes.compras) seguía
        mostrando la compra como pendiente hasta volver a cargar la Tabla Base.
        Se limpian Comparativa (lo que se cuenta) y TablaBase (de donde se regenera Comparativa).
        """
        ids = [p.id for p in productos if p and p.id]
        nombres = [p.producto for p in productos if p and p.producto]

        def _guardar():
            with transaction.atomic():
                Comparativa.objects.filter(id__in=ids).update(cantidad_compra=0)
                TablaBase.objects.filter(descripcion__in=nombres).update(cantidad_compra=0)

        await asyncio.to_thread(_guardar)
        pendientes.refrescar(self.page)

    def update_hojas_tabla_base(self):
        # limpia la base de datos
        HojasTablaBase.objects.all().delete()
        
        with transaction.atomic():
            if self.page.hojas:
                HojasTablaBase.objects.bulk_create([
                    HojasTablaBase(nombre=nombre)
                    for nombre in self.page.hojas
                ])
                
    def carga_tabla_base(self, hojas_seleccionadas):
        """Carga la tabla base usando el manager de lógica de negocio"""
        return TablaBaseManager.cargar_tabla_base(
            hojas_seleccionadas=hojas_seleccionadas,
            page=self.page,
            update_view_callback=self.update_filtered_view
        )
    
    def limpiar_formulario(self):
        # Limpiar los campos del formulario principal
        # self.form.clean()
        # Limpiar la tabla de detalles
        self.table.set_data([])
        self.table.build_body()
        # Restablecer los totales
        self.txt_subtotal.value = f"${format_number(0)}"
        self.txt_iva.value = f"${format_number(0)}"
        self.txt_total.value = f"${format_number(0)}"
        self.txt_cantidad_productos.value = "0"
        
        self.txt_subtotal.update()
        self.txt_iva.update()
        self.txt_total.update()
        self.txt_cantidad_productos.update()
        # Ocultar la tabla si lo deseas
        self.table.visible = False
        # Actualizar la página
        self.page.update()
        
    def get_productos_compra(self):
        """Retorna el queryset filtrado para mostrar solo productos con códigos de barras distintos (case-insensitive y sin espacios)"""
        return Comparativa.objects.filter(existe=True).filter(cantidad_compra__gt=0)
    
    def crea_detalle_inicial(self) -> list[DetalleCompra]:
        """Crea registros iniciales si es necesario"""
        detalle = []
        for item in self.get_productos_compra():
            es_mayorista = num_or_zero(item.uds_agrupamiento) > 0
            precio = item.precio_mayor if es_mayorista else item.tb_precio_compra
            detalle.append(DetalleCompra(
                producto=item,
                cantidad=item.cantidad_compra,
                uds_agrupamiento=item.uds_agrupamiento if es_mayorista else 0,
                precio_unitario=precio,
                total=num_or_zero(item.cantidad_compra) * num_or_zero(precio)
            ))
        return detalle

    def calcula_total_inicial(self):
        return sum(
            num_or_zero(item.cantidad_compra) * (
                num_or_zero(item.precio_mayor) if num_or_zero(item.uds_agrupamiento) > 0
                else num_or_zero(item.tb_precio_compra)
            )
            for item in self.get_productos_compra()
        )