from typing import List, Dict, Optional, Any
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo, cerrar_dialogo, en_pagina
from components.chips import ChipComponent
from components.custom_buttons import CustomButtonCupertino
from components.not_data_table import NotDataTable
from data.serach import buscar_modelo
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from components.custom_dialogs import DlgConfirm
from utilities.conditions import Conditions
from django.db.models import ProtectedError, RestrictedError
from components.selection import Selection

class GenericPage(PaginaFija, ft.Column):
    """
    Clase genérica para manejar páginas con tablas, paginación y acciones CRUD.
    """

    def __init__(self, page: ft.Page, params = {}, _model = None, conditions = Conditions(), 
                 display_btn_edit: bool = True, display_btn_delete: bool = True, display_btn_new: bool = True, 
                 display_btn_desactivar: bool = True, custom_actions:Optional[List] = [], custom_buttons:Optional[List] = [],
                 custom_queryset: Optional[Any] = None, titulo: Optional[str] = None, display_search: bool = True):
        """
        Inicializa la página genérica.

        Args:
            page (ft.Page): Página principal de Flet.
            _model (Any): Modelo de Django asociado a la tabla.
            params (Optional[Dict]): Parámetros iniciales para la página.
            conditions (Conditions): Condiciones para el despliegue de datos para la tabla y los filtros.
            custom_queryset (Optional[Any]): Queryset personalizado para filtrar datos específicos.
        """
        super().__init__()
        self.expand: bool = True
        self.spacing: int = 0
        self.params: Dict = params or {}
        self._model: Any = _model
        self.custom_queryset: Optional[Any] = custom_queryset  # Nuevo atributo
        self.conditions: Conditions = conditions
        self.display_btn_edit: bool = display_btn_edit
        self.display_btn_delete: bool = display_btn_delete
        self.display_btn_new: bool = display_btn_new
        self.display_btn_desactivar: bool = display_btn_desactivar
        self.table_handle_on_long_press: Optional[Any] = None
        self.display_search: bool = display_search
        self.custom_actions: Optional[List] = custom_actions if custom_actions is not None else []
        self.custom_buttons: Optional[List] = custom_buttons if custom_buttons is not None else []
        self.titulo: str = titulo or self._model._meta.verbose_name or ""
        self.page: ft.Page = page
        self.dict_order: Dict[str, str] = {}
        self.text_search: str = ""
        self.text_order: str = ""
        self.is_chk_column_enabled = True  # Nuevo atributo para habilitar/deshabilitar la columna de selección
        self.table = None   
        self.all_records_selected = False
        self._data = []

    def build_page(self):
        # Crear la tabla principal
        self.table: NotDataTable = self.table if self.table else self._create_table()

        # Paginación
        self.pagination_lbl_page_info = self.build_pagination_lbl_page_info()
        self.pagination_btn_previous = self.build_pagination_btn_previous()
        self.pagination_btn_next = self.build_pagination_btn_next()
        self.component_pagination: ft.Row = self.build_component_pagination()
        self.current_page: int = 1
        self.items_per_page: int = 20
        self.paginator: Optional[Paginator] = None
        
        # Componentes de búsqueda
        self.component_search_input: Optional[ft.TextField] = self.build_search_input()
        self.component_search_cancel: Optional[ft.TextButton] = self.build_search_cancel()
        self.component_search: Optional[ft.Row] = self.build_search()
        
        # Chips
        self.component_chips: Optional[ft.Row] = ChipComponent(page=self.page)

        # Botones y acciones
        self.component_left_buttons: Optional[ft.Row] = self.build_left_buttons()
        self.btn_editar = self.build_btn_editar()
        self.component_actions_submenu: Optional[ft.SubmenuButton] = self.build_actions_submenu()
        self.component_actions: Optional[ft.Row] = self.build_actions()
        self.text_row_selected = ft.Text("")

        self.set_base_queryset()
        self.build_default_paginator()
        self.component_seleccionados = Selection(
            fn_cancel_selection=self.cancel_selection,
            fn_seleccion_todos=self.fn_seleccion_todos,
            total_records=self.paginator.count if self.paginator else 0,
            pagination_limit=self.items_per_page
        )
        
        # Menú de la tabla
        self.menu_table: ft.Row = self.build_menu_table()
        self.controls = self.build_controls()

        self.load_page_data()
        self.table.set_model(self._model)
        self.table.create_table()
        self.display_main()

    def fn_seleccion_todos(self):
        self.all_records_selected = True
    
    def build_controls(self):

        return [
            ft.Container(
                content=ft.Row(
                    height=40,
                    controls=[
                        self.menu_table,
                        self.component_pagination,
                    ],
                ), 
                margin=ft.Margin.only(left=10, top=5, right=10, bottom=15)),
            ft.Container(content=self.component_chips, margin=ft.Margin.only(left=10, right=10, bottom=5)),
            ft.Container(
                content=ft.Row(
                    controls=[
                        ft.Column(
                            controls=[self.table],
                            scroll=ft.ScrollMode.AUTO,  # Scroll horizontal
                            expand=False,
                            alignment=ft.MainAxisAlignment.START,
                            
                        )
                    ],
                    scroll=ft.ScrollMode.ALWAYS,  # Scroll vertical
                    expand=True,
                    alignment=ft.MainAxisAlignment.START,
                    vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                expand=True,
                margin=ft.Margin.symmetric(horizontal=10),
                padding=ft.Padding.all(0),
            )
        ]
        

    def build_menu_table(self) -> ft.Row:
        """
        Construye el menú de la tabla con los botones y controles necesarios.

        Returns:
            ft.Row: Fila que contiene los controles del menú de la tabla.
        """
        return ft.Row(
            controls=[
                self.component_left_buttons, 
                self.component_search if self.display_search else ft.Container(),
                self.btn_editar,
                self.component_seleccionados,
                self.component_actions,
            ],
            alignment=ft.MainAxisAlignment.START,
            spacing=10
        )
        
    def build_btn_editar(self):
        return CustomButtonCupertino(
            text="Editar",
            icon=ft.Icons.EDIT,
            on_click=lambda e: self.display_form() if self.display_btn_edit else None
        )
        
    def _create_table(self) -> NotDataTable:
        """
        Crea y configura la tabla principal.

        Returns:
            NotDataTable: Tabla configurada.
        """
        return NotDataTable(
            handle_on_long_press=self.display_form if self.display_btn_edit else self.table_handle_on_long_press if self.table_handle_on_long_press else None,
            on_row_selected=self.handle_on_row_selected,
            on_click_column=self.set_dict_order,
            conditions=self.conditions,
            is_chk_column_enabled=self.is_chk_column_enabled,
            menu_contextual=self.menu_contextual,
            # is_editable=self.display_btn_edit
        )
        
    def set_is_chk_column_enabled(self, is_enabled: bool):
        """
        Habilita o deshabilita la columna de selección de filas.

        Args:
            is_enabled (bool): Indica si la columna de selección debe estar habilitada.
        """
        self.table.is_chk_column_enabled = is_enabled
        # self.table.update()

    def build_default_paginator(self):
        if "text_order" in self.params:
            self.text_order = self.params["text_order"]
        if "search_filter" in self.params:
            self.text_search = self.params["search_filter"]
            self.component_search_input.value = self.text_search
            if self.text_order == "":
                productos_filtrados = buscar_modelo(self.base_queryset, self.text_search)      
            else:
                productos_filtrados = buscar_modelo(self.base_queryset.order_by(self.text_order), self.text_search)
            self.paginator = Paginator(productos_filtrados, self.items_per_page)  
            
        else:
            # self._data = self._model.objects.all()  #Database call
            if self.text_order == "":
                self.paginator = Paginator(self.base_queryset, self.items_per_page)
            else:
                self.paginator = Paginator(self.base_queryset.order_by(self.text_order), self.items_per_page)
                
    def set_base_queryset(self):
        # Determinar el queryset base a usar
        if self.custom_queryset is not None:
            self.base_queryset = self.custom_queryset
        else:
            self.base_queryset = self._model.objects.all()
    
    def load_page_data(self):
        try:
            page_obj = self.paginator.page(self.current_page)
            data_page = page_obj.object_list
        except PageNotAnInteger:
            # If page is not an integer, deliver first page.
            data_page = self.paginator.page(1).object_list
            self.current_page = 1
        except EmptyPage:
            # If page is out of range (e.g. 9999), deliver last page of results.
            data_page = self.paginator.page(self.paginator.num_pages).object_list
            self.current_page = self.paginator.num_pages

        self.table.set_data(data_page)
        self.component_seleccionados.set_total_records(self.paginator.count)
        self.component_seleccionados.set_pagination_limit(
            self.items_per_page if self.paginator.count > self.items_per_page else self.paginator.count
        )
        self.update_pagination_controls()
    
    def display_main(self):
        self.component_left_buttons.visible = True
        self.component_search.visible = True
        self.component_seleccionados.manage_selection_display(0)
        self.component_actions.visible = False
        self.btn_editar.visible = False
        self.component_pagination.visible = True
        # self.table.build_body()
   
    def build_actions(self):
        
        return ft.Row(
            alignment=ft.MainAxisAlignment.CENTER, 
            controls=[
                ft.Row(expand=3, alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.MenuBar(
                            expand=True,
                            style=ft.MenuStyle(
                                alignment=ft.Alignment.TOP_LEFT,
                                bgcolor=ft.Colors.ON_SECONDARY,
                                shadow_color=ft.Colors.ON_SECONDARY,
                                elevation= False,
                                mouse_cursor={
                                    ft.ControlState.HOVERED: ft.MouseCursor.WAIT,
                                    ft.ControlState.DEFAULT: ft.MouseCursor.ZOOM_OUT,
                                },
                            ),
                            controls=[
                                self.component_actions_submenu,
                            ]
                        )
                    ]
                ),
            ]
        )
        
    def build_actions_submenu(self):
        return ft.SubmenuButton(
            content=ft.Text("Acciones", color=ft.Colors.ON_SURFACE, size=15, font_family="Roboto Mono"),
            leading=ft.Icon(ft.Icons.MENU, color=ft.Colors.ON_SURFACE),
            controls=[],
        )
    
    def handle_custom_action(self, action_function, selected_objects):
        """
        Maneja la ejecución de acciones personalizadas.
        
        Args:
            action_function: Función a ejecutar o evento original
            selected_objects: Lista de objetos seleccionados en la tabla
        """
        try:
            if callable(action_function):
                # Si es una función, la llamamos con los objetos seleccionados
                action_function(selected_objects)
            elif hasattr(action_function, '__call__'):
                # Si es un método o callable
                action_function(selected_objects)
            else:
                # Si es el evento original de un MenuItemButton
                if action_function:
                    action_function(selected_objects)
        except Exception as e:
            # Mostrar error en caso de que falle la función personalizada
            abrir_dialogo(self.page, ft.SnackBar(
                content=ft.Text(f"Error en acción personalizada: {str(e)}"),
                bgcolor=ft.Colors.ERROR
            ))
    
    def build_left_buttons(self):
        component_left_buttons = ft.Row(controls=[], spacing=3, wrap=True)
        if self.display_btn_new:
            component_left_buttons.controls.append(ft.CupertinoFilledButton(
                    content=ft.Text("Nuevo"),
                    height=40,
                    padding=ft.Padding.symmetric(horizontal=10),
                    on_click=lambda e: self.display_form()
                ))
        # El título de la pantalla se muestra en la barra superior (main.actualizar_titulo).

        for button in self.custom_buttons:
            if isinstance(button, dict):
                btn_cupertino = CustomButtonCupertino(
                    text=button.get('text', 'Acción'),
                    icon=button.get('icon', None),
                    on_click=lambda e, btn=button: btn.get('function')() if callable(btn.get('function')) else None,
                    bgcolor=button.get('bgcolor', ft.Colors.ON_SECONDARY),
                    color=button.get('color', ft.Colors.ON_SURFACE),
                    tooltip=button.get('tooltip'),
                )
                component_left_buttons.controls.append(btn_cupertino)
            elif isinstance(button, CustomButtonCupertino):
                component_left_buttons.controls.append(button)
            elif isinstance(button, ft.Switch):
                component_left_buttons.controls.append(button)
            else:
                component_left_buttons.controls.append(button)
        return component_left_buttons
    
    def build_pagination_lbl_page_info(self):
        """
        Construye la etiqueta que muestra información de la página actual.
        """
        return ft.Container(
            content=ft.Text("", color=ft.Colors.ON_SURFACE, size=13, font_family="Roboto Mono"),
            padding=ft.Padding.symmetric(horizontal=6),
        )
        
    def build_pagination_btn_previous(self):
        """
        Construye el botón de página anterior.
        """
        return ft.TextButton(
            content=ft.Row([ft.Icon(icon=ft.Icons.CHEVRON_LEFT, size=28)]),
            width=40,
            height=40,
            style=ft.ButtonStyle(
                padding=ft.Padding.all(5),
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                shape=ft.RoundedRectangleBorder(radius=3),
            ),
            on_click=lambda e: self.previous_page(),
        )
        
    def build_pagination_btn_next(self):
        """
        Construye el botón de página siguiente.
        """
        return ft.TextButton(
            content=ft.Row([ft.Icon(icon=ft.Icons.CHEVRON_RIGHT, size=28)]),
            width=40,
            height=40,
            style=ft.ButtonStyle(
                padding=ft.Padding.all(5),
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                shape=ft.RoundedRectangleBorder(radius=3),
            ),
            on_click=lambda e: self.next_page(),
        )

    def build_component_pagination(self) -> None:
        """
        Construye los controles de paginación.
        """
        
        return ft.Row(
            expand=2,
            spacing=1,
            alignment=ft.MainAxisAlignment.END,
            controls=[
                self.pagination_lbl_page_info,
                self.pagination_btn_previous,
                self.pagination_btn_next,
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_size=20,
                    tooltip="Recargar Datos",
                    on_click=lambda e: self.search(),
                ),
            ],
        )
    
    def update_pagination_controls(self):
        if self.paginator is not None:
          total_items = self.paginator.count
          total_pages = self.paginator.num_pages

          start_index = (self.current_page - 1) * self.items_per_page + 1
          end_index = min(self.current_page * self.items_per_page, total_items)

          self.pagination_lbl_page_info.content.value = f"{start_index}-{end_index}/{total_items}"
          self.pagination_btn_previous.disabled = self.current_page == 1
          self.pagination_btn_next.disabled = self.current_page == total_pages

    def next_page(self):
        if self.current_page < self.paginator.num_pages:
            self.current_page += 1
            self.load_page_data()
            self.table.build_body()
            self.table.navigation_map_activate()
            self.update()

    def previous_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.load_page_data()
            self.table.build_body()
            self.table.navigation_map_activate()
            self.update()

    def build_search_input(self):
        return ft.TextField(
            label="Busqueda",
            height=34,
            width=250,
            icon=ft.Icons.SEARCH,
            text_style=ft.TextStyle(size=14),
            border_color="#ababab",
            on_submit= lambda e: self.set_text_search(e.control.value)
        )
    
    def build_search_cancel(self, show_close=False):
        return ft.TextButton(
            content=ft.Row([
                ft.Icon(icon=ft.Icons.CANCEL, size=20, color=ft.Colors.TERTIARY),
            ]),
            width=32,
            height=32,
            style=ft.ButtonStyle(padding=ft.Padding.all(5)),
            on_click= lambda e: self.cancel_search(),
            visible=show_close
        )
        
    def build_search(self):
        return ft.Row(controls=[
            self.component_search_input,
            self.component_search_cancel,
        ])
        
    def cancel_search(self):
        self.text_search = ""
        self.search()
        self.component_search_input.value = ""
        self.component_search_input.update()
    
    def menu_contextual(self, obj):
        """Acciones del clic derecho sobre una fila: editar y las acciones propias de la pantalla."""
        items = []
        if self.display_btn_edit:
            items.append(("Editar", ft.Icons.EDIT, lambda: self.display_form(obj)))
        for accion in self.custom_actions:
            if isinstance(accion, dict) and callable(accion.get("function")):
                items.append((
                    accion.get("text", "Acción"),
                    accion.get("icon", ft.Icons.SETTINGS),
                    lambda f=accion["function"]: self.handle_custom_action(f, [obj]),
                ))
        return items

    def atajos(self):
        async def ir_al_buscador():
            if self.component_search.visible and en_pagina(self.component_search_input):
                await self.component_search_input.focus()

        def pagina(mover):
            return lambda: mover() if getattr(self, "paginator", None) is not None else None

        return {"ctrl+f": ir_al_buscador, "pagedown": pagina(self.next_page), "pageup": pagina(self.previous_page)}

    def set_dict_order(self, dict_order):
        self.dict_order = dict_order
        self.search()
     
    def set_text_search(self, value):
        self.text_search = value
        self.search()
        
    def search(self):
        # if self.text_search == "":
        #     self.search_active = False
        # else:
        #     self.search_active = True
        
        self.component_search_cancel.visible = True if self.text_search else False
        self.component_search.update()
        
        self.text_order = ""
        for clave in self.dict_order:
            if self.dict_order[clave] == "asc":
                self.text_order = f"{clave}"
            else:
                self.text_order = f"-{clave}"
                
        if(self.text_order == ""):
            productos_filtrados = buscar_modelo(self.base_queryset, self.text_search)
        else:
            productos_filtrados = buscar_modelo(self.base_queryset.order_by(self.text_order), self.text_search)
        self._data = productos_filtrados
        self.paginator = Paginator(productos_filtrados, self.items_per_page)
        self.current_page = 1
        self.load_page_data()
        
        # Limpiar cache de modificaciones al hacer una nueva búsqueda
        if hasattr(self.table, 'clear_cache'):
            self.table.clear_cache()
            
        self.table.build_body()
        self.table.navigation_map_activate()
        self.update()
        self.table.update()
        
    def set_data(self, data):
        self._data = data
        
    def set_custom_queryset(self, queryset):
        """
        Actualiza el queryset personalizado y recarga los datos.
        
        Args:
            queryset: Nuevo queryset a usar como filtro
        """
        self.custom_queryset = queryset
        self.set_base_queryset()
        # Recargar datos con el nuevo queryset
        self.search()
      
    def load_data_table(self):
        self.table.fill_data_table()
    
    def set_actions_menu(self, list_objs):
        count_row_selected = len(list_objs)
        ## despliega boton editar si hay un solo objeto seleccionado
        if len(list_objs) == 1 and self.display_btn_edit:
            obj = list_objs[0]
            self.btn_editar.on_click = lambda e: self.display_form(obj)
            self.btn_editar.visible = True
        else:
            self.btn_editar.on_click = lambda e: None
            self.btn_editar.visible = False
            
        ## despliega el boton de seleccionados si hay objetos seleccionados
        self.component_seleccionados.manage_selection_display(count_row_selected)

        #################################################
        ########### MENU DE ACCIONES ####################
        #################################################
        items_accion = []
        if self.display_btn_delete:
            items_accion.append(ft.MenuItemButton(
                content=ft.Text("Eliminar"),
                leading=ft.Icon(ft.Icons.DELETE),
                on_click= lambda e: self.handle_delete(),
            ))
        if self.display_btn_desactivar:
            items_accion.append(ft.MenuItemButton(
                content=ft.Text("Desactivar"),
                leading=ft.Icon(ft.Icons.CANCEL),
            ))
        # Mejorar el manejo de custom_actions
        for action in self.custom_actions:
            if isinstance(action, dict):
                # Si es un diccionario con 'text', 'icon' y 'function'
                menu_item = ft.MenuItemButton(
                    content=ft.Text(action.get('text', 'Acción')),
                    leading=ft.Icon(action.get('icon', ft.Icons.SETTINGS)),
                    on_click=lambda e, func=action.get('function'): self.handle_custom_action(func, list_objs)
                )
                items_accion.append(menu_item)
            elif isinstance(action, ft.MenuItemButton):
                # Si ya es un MenuItemButton, necesitamos modificar su on_click
                # para pasar los objetos seleccionados
                original_on_click = action.on_click
                action.on_click = lambda e, original=original_on_click: self.handle_custom_action(original, list_objs)
                items_accion.append(action)
                
                
        self.component_actions_submenu.controls = items_accion
        self.component_actions_submenu.update()
        self.component_left_buttons.visible = True
        self.component_search.visible = False
        self.component_actions.visible = True  
        self.component_pagination.visible = True
        self.menu_table.update()
        self.component_seleccionados.manage_selection_display(count_row_selected)
        self.component_seleccionados.update()

    def cancel_selection(self):
        self.all_records_selected = False
        self.table.clean_selection()
        self.set_search_menu()
    
    def set_search_menu(self):
        self.component_left_buttons.visible = True
        self.component_search.visible = True
        self.component_actions.visible = False
        self.component_pagination.visible = True
        self.component_seleccionados.manage_selection_display(0)
        # self.btn_editar.visible = False
        self.menu_table.update()
    
    def handle_on_row_selected(self, list_obj):
        self.all_records_selected = False
        count_selected = len(list_obj)
        if count_selected > 0:
            # get_count_objects
            self.set_actions_menu(list_obj)
        else:
            self.set_search_menu()
              
    def btn_cancelar_dlg_si(self):
        cerrar_dialogo(self.page, self.dlg_alert)
        self.display_main()
        self.update()

    def btn_cancelar_dlg_no(self):
        cerrar_dialogo(self.page, self.dlg_alert)
             
    def handle_delete(self):
        DlgConfirm(page=self.page, title="Desea eliminar los registros?", fn_yes=self.handle_delete_yes)
    
    def handle_delete_yes(self):
        """
        Maneja la confirmación de eliminación de registros seleccionados.
        """
        for obj in self.table.get_selectd_objects():
            try:
                obj.delete()
            except ProtectedError as e:
                relaciones = self.obtener_relaciones(obj)
                self.dlg_msg = ft.AlertDialog(
                    title=ft.Text(f"No se puede eliminar {str(obj)}."),
                    content=ft.Text(f"Registros relacionados: {relaciones}"),
                )
                abrir_dialogo(self.page, self.dlg_msg)
            except RestrictedError as e:
                self.dlg_msg = ft.AlertDialog(
                    title=ft.Text(f"Error al eliminar {str(obj)}."),
                    content=ft.Text(f"Detalles del error: {str(e)}"),
                )
                abrir_dialogo(self.page, self.dlg_msg)    
        self.set_search_menu()
        self.search()
            
    def obtener_relaciones(self, obj):
        """
        Devuelve un diccionario con los nombres de los modelos relacionados y la cantidad de registros asociados.
        """
        relaciones = {}
        for relation in obj._meta.related_objects:
            related_name = relation.get_accessor_name()
            related_manager = getattr(obj, related_name)
            
            count = related_manager.count()  # Contar registros relacionados
            if count > 0:
                relaciones[relation.related_model.__name__] = count
        
        return relaciones   
    
    def display_form(self, _obj = None):
        params = {}
        params["returns_params"] = {}
        if self.text_search:
            params["returns_params"]["search_filter"] = self.text_search
        if self.text_order:
            params["returns_params"]["text_order"] = self.text_order
            
        if _obj:
            params["_obj"] = _obj
            self.page.custom_go(f"{self.page.route}/form?origin={self.page.route}?id={_obj.id}", params=params)
        else:
            self.page.custom_go(f"{self.page.route}/form?origin={self.page.route}", params=params)
    