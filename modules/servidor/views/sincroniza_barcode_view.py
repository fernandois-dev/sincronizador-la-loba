import flet as ft
from utilities.flet_compat import abrir_dialogo, cerrar_dialogo
from components.custom_buttons import boton_cargar_odoo, boton_cargar_tb, boton_filtro, boton_limpiar_tb
from django.db import transaction
from django.db.models import F


from components.custom_input import DisplayMode
from modules.servidor.data_manage import DataManage
from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import Comparativa, HojasSeleccionadas, TablaBase
from modules.servidor.odoo import OdooService
from pages.generic_page import GenericPage
from utilities.conditions import Conditions


def sincroniza_barcode_view(page: ft.Page, params: dict):

    # Variable de estado para controlar el filtro
    is_filtered = True  # Inicia filtrado por defecto

    def get_filtered_queryset():
        """Retorna el queryset filtrado para mostrar solo productos con códigos de barra distintos"""
        return Comparativa.objects.exclude(tb_barcode=F('odoo_barcode'))

    def update_filtered_view(view_ref):
        """Actualiza la vista con el queryset filtrado después de cambios en los datos"""
        if view_ref:
            # Limpiar cache de modificaciones antes de recargar
            if hasattr(view_ref.table, 'clear_cache'):
                view_ref.table.clear_cache()
            
            # Aplicar el queryset según el estado actual del filtro
            if is_filtered:
                # Mantener el filtro activo
                filtered_queryset = get_filtered_queryset()
                view_ref.set_custom_queryset(filtered_queryset)
            else:
                # Mantener mostrando todos
                view_ref.set_custom_queryset(Comparativa.objects.all())

    def toggle_price_filter(view_ref=None):
        """
        Alterna entre mostrar todos los productos o solo los que tienen precios distintos
        """
        nonlocal is_filtered
        
        if view_ref:
            if is_filtered:
                # Actualmente filtrado, mostrar todos
                view_ref.set_custom_queryset(Comparativa.objects.all())
                is_filtered = False
                abrir_dialogo(page, ft.SnackBar(ft.Text("Mostrando todos los productos")))
            else:
                # Actualmente mostrando todos, aplicar filtro
                filtered_queryset = get_filtered_queryset()
                view_ref.set_custom_queryset(filtered_queryset)
                is_filtered = True
                abrir_dialogo(page, ft.SnackBar(ft.Text("Mostrando solo productos con precios distintos")))

    def show_loading(message="Cargando..."):
        """Muestra un diálogo de loading"""
        loading_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Procesando"),
            content=ft.Column(
                controls=[
                    ft.ProgressRing(),
                    ft.Text(message, text_align=ft.TextAlign.CENTER)
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                height=100,
                width=200
            )
        )
        abrir_dialogo(page, loading_dialog)
        return loading_dialog

    def hide_loading(loading_dialog):
        """Oculta el diálogo de loading"""
        cerrar_dialogo(page, loading_dialog)

    def get_hojas():
        """
        Función para cargar la tabla base desde Google Sheets.
        """
        list_hojas = GoogleService.get_hojas()
        if not list_hojas:
            abrir_dialogo(page, ft.SnackBar(ft.Text("No se encontraron hojas en Google Sheets.")))
            return

        return list_hojas
    
    def selecciona_hoja(e):
        """
        Función para manejar la selección de una hoja en la lista.
        """
        e.control.selected = not e.control.selected
        e.control.update()

    def actualizar_lista():
        lista_hojas.rows.clear()
        hojas = HojasSeleccionadas.objects.all()
        
        for hoja in get_hojas():
            lista_hojas.rows.append(
                ft.DataRow(
                    cells=[
                        ft.DataCell(ft.Text(hoja)),
                    ],
                    data=hoja,
                    selected=hoja in hojas.values_list('hoja', flat=True),
                    on_select_change=lambda e, hoja=hoja: selecciona_hoja(e)
                )
            )
        page.update()
                
    def fn_carga_tb(view_ref=None):
        actualizar_lista()
        abrir_dialogo(page, dlg_modal)

    def agregar_hoja():
        """Función para agregar una nueva hoja a la tabla base."""
        al_menos_una_hoja_seleccionada = False
        for hoja in lista_hojas.rows:
            if hoja.selected:
                al_menos_una_hoja_seleccionada = True
                break
            
        if not al_menos_una_hoja_seleccionada:
            abrir_dialogo(page, ft.SnackBar(ft.Text("Debe seleccionar al menos una hoja.")))
            return
        
        # Cerrar el diálogo modal primero
        cerrar_dialogo(page, dlg_modal)
        
        # Mostrar loading
        loading_dialog = show_loading("Cargando datos de Google Sheets...")
        
        try:
            # Limpia las hojas seleccionadas antes de agregar nuevas
            # Esto asegura que no se dupliquen las hojas seleccionadas
            with transaction.atomic():
                HojasSeleccionadas.objects.all().delete()

                hojas_seleccionadas_from_tabla = [hoja.data for hoja in lista_hojas.rows if hoja.selected]

                listo_obj = [
                    HojasSeleccionadas(hoja=hoja)
                    for hoja in hojas_seleccionadas_from_tabla
                ]
                # Guardamos todas las reglas de una vez
                HojasSeleccionadas.objects.bulk_create(listo_obj)
                
                cargar_data_tabla_base(hojas_seleccionadas_from_tabla)

            # Actualizar la vista después de cargar los datos
            if hasattr(fn_carga_tb, '_view_ref') and fn_carga_tb._view_ref:
                # Actualizar con el queryset filtrado
                update_filtered_view(fn_carga_tb._view_ref)
            
            # Ocultar loading
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos cargados y tabla actualizada.")))
            
        except Exception as e:
            # Ocultar loading en caso de error
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def cargar_data_tabla_base(lista_hojas):
        data = []

        for hoja in lista_hojas:
            data += GoogleService.get_data(hoja)
                
        if not data:
            return
        
        # Guardar datos en la base de datos local
        DataManage.set_data_tabla_base(data)
        # Realiza la comparacion entre los datos de la tabla base y los datos de Odoo
        DataManage.compare_data_with_odoo()
    
    def build_layout_dlg():
        """
        Construye el layout del diálogo modal.
        """
        return ft.Column(
            controls=[
                ft.Container(
                    content=ft.Column(
                        controls=[lista_hojas],  
                    ),
                    width=500,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            scroll=ft.ScrollMode.ALWAYS,
            height=400,
        )

    def sincronizar_codigos(filas_a_actualizar: list[Comparativa], view_ref=None):
        """
        Función para sincronizar los códigos de barra entre la tabla base y Odoo.
        """
        proceso_ok = True
        msg = ""

        for fila in filas_a_actualizar:
            resultado = OdooService.set_productos({"id": fila.producto_id, "barcode": fila.tb_barcode})
            if resultado.get("state") != "S":
                msg = resultado.get("msg", "")
                proceso_ok = False

        if not proceso_ok:
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Se registraron errores al sincronizar el código de barra en Odoo. {msg}", bgcolor=ft.Colors.ERROR)))
            return
        # vuelve a cargar odoo
        _ejecutar_carga_odoo_products(view_ref)
        abrir_dialogo(page, ft.SnackBar(ft.Text("Stock sincronizado con éxito.")))
     
    def carga_odoo(view_ref=None):
        # Verificar si hay modificaciones sin guardar
        if view_ref and hasattr(view_ref.table, 'get_modified_objects_count'):
            modified_count = len([obj for obj in view_ref.table.get_modified_objects().values() if obj.new_stock != 0])
            if modified_count > 0:
                # Mostrar diálogo de confirmación
                def confirmar_carga():
                    cerrar_dialogo(page, dlg_confirmacion)
                    _ejecutar_carga_odoo(view_ref)
                
                def cancelar_carga():
                    cerrar_dialogo(page, dlg_confirmacion)
                
                dlg_confirmacion = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Modificaciones sin guardar"),
                    content=ft.Text(f"Hay {modified_count} modificaciones sin guardar. Al cargar datos de Odoo se perderán estos cambios. ¿Desea continuar?"),
                    actions=[
                        ft.TextButton("Cancelar", on_click=lambda e: cancelar_carga()),
                        ft.TextButton("Continuar", on_click=lambda e: confirmar_carga()),
                    ],
                    actions_alignment=ft.MainAxisAlignment.END,
                )
                abrir_dialogo(page, dlg_confirmacion)
                return
        
        _ejecutar_carga_odoo(view_ref)
    
    def _ejecutar_carga_odoo(view_ref):
        # Mostrar loading
        loading_dialog = show_loading("Cargando datos de Odoo...")
        
        try:
            # Cargar datos de Odoo
            DataManage.save_all_odoo_data(
                products=OdooService.get_productos(),
                tarifas=OdooService.get_tarifas(),
                rutas=OdooService.get_rutas(),
                proveedores=OdooService.get_proveedores()
            )
            DataManage.compare_data_with_odoo()
            
            # Actualizar la vista después de cargar los datos
            if view_ref:
                # Actualizar con el queryset filtrado
                update_filtered_view(view_ref)
            
            # Ocultar loading
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            
        except Exception as e:
            # Ocultar loading en caso de error
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))
            
    def _ejecutar_carga_odoo_products(view_ref):
        # Mostrar loading
        loading_dialog = show_loading("Cargando datos de Odoo...")
        
        try:
            # Cargar datos de Odoo
            DataManage.save_productos_odoo(
                products=OdooService.get_productos()
            )
            DataManage.compare_data_with_odoo()
            
            # Actualizar la vista después de cargar los datos
            if view_ref:
                # Actualizar con el queryset filtrado
                update_filtered_view(view_ref)
            
            # Ocultar loading
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text("Datos de Odoo cargados y tabla actualizada.")))
            
        except Exception as e:
            # Ocultar loading en caso de error
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al cargar datos de Odoo: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def limpiar_tablas(view_ref=None):
        """
        Limpia las tablas HojasSeleccionadas, TablaBase y Comparativa
        """
        # Mostrar loading
        loading_dialog = show_loading("Limpiando tablas...")
        
        try:
            with transaction.atomic():
                # Limpiar las tres tablas
                HojasSeleccionadas.objects.all().delete()
                TablaBase.objects.all().delete()
                Comparativa.objects.all().delete()
            
            # Actualizar la vista después de limpiar
            if view_ref:
                # Actualizar con el queryset filtrado
                update_filtered_view(view_ref)
            
            # Ocultar loading
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text("Tablas limpiadas correctamente.")))
            
        except Exception as e:
            # Ocultar loading en caso de error
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al limpiar tablas: {str(e)}", bgcolor=ft.Colors.ERROR)))

    def obtener_productos_con_codigo_diferente(view_ref, lista_de_productos):
        """
        Función para sincronizar los códigos de barra entre la tabla base y Odoo.
        """
        # Mostrar loading
        loading_dialog = show_loading("Obteniendo Productos...")
        
        try:
            filas_a_actualizar = []
            
            # Obtener productos con códigos de barra diferentes desde la tabla que esten seleccionados
            for obj in lista_de_productos:
                if obj.tb_barcode != obj.odoo_barcode:
                    filas_a_actualizar.append(obj)

            # Ocultar loading
            hide_loading(loading_dialog)
            
            if filas_a_actualizar:
                # Mostrar información de cuántas filas se van a sincronizar
                abrir_dialogo(page, ft.SnackBar(ft.Text(f"Se sincronizarán {len(filas_a_actualizar)} productos con codigos de barra diferentes.")))
                dlg = ft.AlertDialog(
                    modal=True,
                    title=ft.Text("Confirmar Sincronización"),
                    content=ft.Column(
                        controls=[
                            ft.Text(f"Se sincronizarán {len(filas_a_actualizar)} productos con codigos de barra diferentes."),
                            ft.DataTable(
                                columns=[
                                    ft.DataColumn(ft.Text("Producto")),
                                    ft.DataColumn(ft.Text("Código de Barra Tabla Base")),
                                    ft.DataColumn(ft.Text("Código de Barra Odoo"))
                                ],
                                rows=[
                                    ft.DataRow(cells=[
                                        ft.DataCell(ft.Text(obj.producto)),
                                        ft.DataCell(ft.Text(obj.tb_barcode)),
                                        ft.DataCell(ft.Text(obj.odoo_barcode))
                                    ]) for obj in filas_a_actualizar
                                ]
                            )
                        ]
                    ),
                    actions=[
                        ft.TextButton("Cancelar", on_click=lambda e: cerrar_dialogo(page, dlg)),
                        ft.TextButton("Confirmar", on_click=lambda e: sincronizar_codigos(filas_a_actualizar, view_ref)),
                    ],
                )
                abrir_dialogo(page, dlg)
                
            else:
                abrir_dialogo(page, ft.SnackBar(ft.Text("No hay productos seleccionados con precios por modificar para sincronizar.")))

        except Exception as e:
            # Ocultar loading en caso de error
            hide_loading(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al sincronizar precios: {str(e)}", bgcolor=ft.Colors.ERROR)))

        

    lista_hojas = ft.DataTable(
        columns=[
            ft.DataColumn(label=ft.Text("Nombre"))
        ],
        rows=[],
        show_checkbox_column=True,
    )
                
    dlg_modal = ft.AlertDialog(
        modal=True,
        title=ft.Text("Selecciona las hojas para cargar"),
        content=build_layout_dlg(),
        actions=[
            ft.TextButton("Cancelar", on_click=lambda e: cerrar_dialogo(page, dlg_modal)),
            ft.TextButton("Cargar", on_click=lambda e: agregar_hoja()),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
        on_dismiss=lambda e: print("Modal dialog dismissed!"),
    )
    
    # Definir acciones personalizadas
    custom_actions = [
        {
            'text': 'Sincronizar Codigos de Barras',
            'icon': ft.Icons.SYNC,
            'function': lambda e: obtener_productos_con_codigo_diferente(view, e)
        },
    ]

    conditions = Conditions(
        # fields_order=["tb_stock"],
        fields_order=["ref_interna", "producto", "existe", "desc_ok", "tb_barcode", "odoo_barcode"],
        # overrides_view_type={"tb_stock": CustomIntegerField},
        # overrides_display_mode={"new_stock": DisplayMode.EDIT},
        fields_conditions_display={
            "tb_barcode": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_barcode !=  obj.odoo_barcode else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
            "odoo_barcode": lambda obj: {"bgcolor": ft.Colors.ERROR_CONTAINER} if obj.tb_barcode !=  obj.odoo_barcode else {"bgcolor": ft.Colors.PRIMARY_CONTAINER},
        }
    )
    
    custom_buttons = [
        boton_cargar_tb(lambda e: fn_carga_tb(view)),
        boton_limpiar_tb(lambda e: limpiar_tablas(view)),
        boton_cargar_odoo(lambda e: carga_odoo(view)),
        boton_filtro(lambda e: toggle_price_filter(view), tooltip="Filtrar productos")
    ]

    # Crear queryset filtrado para mostrar solo productos con precios distintos
    filtered_queryset = get_filtered_queryset()
    
    view = GenericPage(page=page, _model=Comparativa, params=params, conditions=conditions,
                       display_btn_edit=False, display_btn_delete=False, display_btn_new=False, 
                       display_btn_desactivar=False,
                       custom_actions=custom_actions, 
                       custom_buttons=custom_buttons,
                       custom_queryset=filtered_queryset,
                       titulo="Sincronización de Códigos de Barras"
                       )  # Usar queryset filtrado
    
    # Ahora que tenemos la referencia del view, creamos los custom_buttons
    
    # Reconstruimos los botones izquierdos con la nueva configuración
    view.component_left_buttons = view.build_left_buttons()
    # view.set_is_chk_column_enabled(False)
    
    view.build_page()
    return view