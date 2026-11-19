import flet as ft
from django.db import transaction

from modules.servidor.google_sheet import GoogleService
from modules.servidor.odoo import OdooService

def correlativo_codigo_view(page: ft.Page, params: dict):
    # Componentes de la interfaz
    texto_ultimo = ft.Text("", size=16)
    texto_siguiente = ft.Text("", size=14, weight=ft.FontWeight.BOLD)
    btn_buscar = ft.Button(
        content="Buscar Último Correlativo",
        icon=ft.Icons.SEARCH,
        on_click=lambda e: buscar_correlativo(),
        style=ft.ButtonStyle(
            bgcolor=ft.Colors.PRIMARY,
            color=ft.Colors.ON_PRIMARY,
        )
    )
    loading_ring = ft.ProgressRing(visible=False)
    
    def buscar_correlativo():
        """Función que ejecuta la búsqueda del correlativo"""
        try:
            # Mostrar loading
            loading_ring.visible = True
            btn_buscar.disabled = True
            texto_ultimo.value = "Buscando..."
            texto_siguiente.value = ""
            page.update()
            
            # Obtener códigos de barras desde Odoo
            ultimo_correlativo = OdooService.obtener_ultimo_correlativo_odoo()
            siguiente_correlativo = generar_siguiente_correlativo(ultimo_correlativo)
            
            # Actualizar la interfaz con los resultados
            texto_ultimo.value = f"Último correlativo encontrado: {ultimo_correlativo}"
            texto_siguiente.value = f"Próximo correlativo sugerido: {siguiente_correlativo}"
            texto_ultimo.color = ft.Colors.ON_SURFACE
            
        except Exception as e:
            texto_ultimo.value = f"Error al obtener correlativo: {str(e)}"
            texto_ultimo.color = ft.Colors.ERROR
            texto_siguiente.value = ""
            
        finally:
            # Ocultar loading
            loading_ring.visible = False
            btn_buscar.disabled = False
            page.update()
    
    view = ft.Container(
        content=ft.Column(
            controls=[
                ft.Text("Consulta de Correlativos", size=20, weight=ft.FontWeight.BOLD),
                ft.Divider(),
                btn_buscar,
                loading_ring,
                ft.SelectionArea(texto_ultimo),
                ft.SelectionArea(texto_siguiente),
                ft.Container(height=20),  # Espaciado
                ft.Row(
                    controls=[
                        ft.Icon(ft.Icons.INFO, color=ft.Colors.BLUE),
                        ft.Text("Consulta directa a Odoo para evitar límites de API", size=12, color=ft.Colors.BLUE_GREY)
                    ],
                    alignment=ft.MainAxisAlignment.CENTER
                )
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=15
        ),
        width=500,
        height=300,
        alignment=ft.Alignment.CENTER,
        padding=20
    )
    
    return view

def generar_siguiente_correlativo(ultimo_correlativo):
    """
    Genera el siguiente correlativo basado en el último encontrado.
    
    Args:
        ultimo_correlativo (str): El último código de barras encontrado
        
    Returns:
        str: El siguiente correlativo sugerido
    """
    try:
        if not ultimo_correlativo or ultimo_correlativo == 'LL0000':
            return 'LL0001'
        
        # Extraer la parte numérica del código
        if ultimo_correlativo.startswith('LL'):
            numero_parte = ultimo_correlativo[2:]  # Quitar el prefijo 'LL'
            try:
                numero = int(numero_parte)
                siguiente_numero = numero + 1
                # Formatear con ceros a la izquierda para mantener la longitud
                return f"LL{siguiente_numero:0{len(numero_parte)}d}"
            except ValueError:
                return 'LL0001'
        else:
            return 'LL0001'
            
    except Exception as e:
        print(f"Error al generar siguiente correlativo: {e}")
        return 'LL0001'