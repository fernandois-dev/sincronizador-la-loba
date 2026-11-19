import flet as ft
from utilities.flet_compat import abrir_dialogo, cerrar_dialogo
from django.db import transaction


from modules.servidor.google_sheet import GoogleService
from modules.servidor.models import HojasTablaBase
from modules.servidor.reports import generar_reporte_a4
from pages.generic_page import GenericPage
from utilities.conditions import Conditions


def impresion_a4_view(page: ft.Page, params: dict):
    
    def show_loading_report(message="Generando reporte..."):
        """Muestra un diálogo de loading para reportes"""
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

    def hide_loading_report(loading_dialog):
        """Oculta el diálogo de loading"""
        cerrar_dialogo(page, loading_dialog)
    
    def genera_reporte_codigo_barras_a4(selected_objects):
        # 1 Obtiene los datos desde la tabla base iterando sobre las hojas seleccionadas
        # 2 filtra los datos para obtener solos los que tienen un codigo de barras que empiecen con "LL"
        # 3 genera el reporte en formato PDF
        # 4 descarga el reporte en el navegador
        
        # Mostrar loading
        loading_dialog = show_loading_report("Generando reporte PDF...")
        
        try:
            data = []
            
            for hoja in selected_objects:
                
                data = GoogleService.get_data(hoja.nombre)
                if not data:
                    break
                # 2
                data = [row for row in data if str(row.get("CODIGO BARRAS", "")).startswith("LL")]
                if not data:
                    hide_loading_report(loading_dialog)
                    abrir_dialogo(page, ft.SnackBar(ft.Text(f"No se encontraron datos para la hoja: {hoja.nombre}")))
                    break
                # 3 genera el reporte en formato PDF
                report = generar_reporte_a4(page, nombre_hoja=hoja.nombre, products=data)

                # 4 descarga el reporte en el navegador
                hide_loading_report(loading_dialog)
                abrir_dialogo(page, ft.SnackBar(ft.Text(f"Reporte generado: {report}")))
                
        except Exception as e:
            hide_loading_report(loading_dialog)
            abrir_dialogo(page, ft.SnackBar(ft.Text(f"Error al generar reporte: {str(e)}", bgcolor=ft.Colors.ERROR)))
    
    # Definir acciones personalizadas
    custom_actions = [
        {
            'text': 'Generar Reporte A4',
            'icon': ft.Icons.PRINT,
            'function': genera_reporte_codigo_barras_a4
        },
    ]
    
    
    conditions = Conditions(
        fields_excluded=["id","activo"],
    )

    # limpia la base de datos
    HojasTablaBase.objects.all().delete()

    list_hojas = GoogleService.get_hojas()
    
    with transaction.atomic():
        if list_hojas:
            HojasTablaBase.objects.bulk_create([
                HojasTablaBase(nombre=nombre) 
                for nombre in list_hojas
            ])


    view = GenericPage(page=page, _model=HojasTablaBase, params=params, conditions=conditions,
                       display_btn_edit=False, display_btn_delete=False, display_btn_new=False, 
                       display_btn_desactivar=False,
                       custom_actions=custom_actions)
    view.build_page()
    return view