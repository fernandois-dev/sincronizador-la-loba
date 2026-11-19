import asyncio
import flet as ft
from utilities.flet_compat import PaginaFija, abrir_dialogo
import time
from typing import Dict, List, Optional, Callable, Any
from components.custom_dialogs import DlgConfirm
from components.field_builder import FieldBuilder
from utilities.conditions import Conditions
from components.custom_input import DisplayMode, LayoutMode
from utilities.style_manager import StyleManager as SM
from utilities.style_keys import StyleKeys as SK

class NotDataTableHeader(PaginaFija, ft.Container):
    """
    Represents the header of a data table, including column headers and an optional checkbox for selecting all rows.
    """
    def __init__(
        self,
        data: List[Any],
        model: Any,
        is_chk_column_enabled: bool = True,
        is_editable: bool = False,
        handle_all_row_selected: Optional[Callable[[ft.ControlEvent], None]] = None,
        on_click_column: Optional[Callable[[Dict[str, str]], None]] = None,
        conditions: Conditions = Conditions(),
        *args,
        **kwargs,
    ):
        """
        Initializes the NotDataTableHeader component.

        Args:
            data (List[Any]): The data to display in the table.
            model (Any): The model associated with the table.
            is_chk_column_enabled (bool): Whether the checkbox column is enabled.
            is_editable (bool): Whether the table is editable.
            handle_all_row_selected (Optional[Callable[[ft.ControlEvent], None]]): Callback for selecting all rows.
            on_click_column (Optional[Callable[[Dict[str, str]], None]]): Callback for column click events.
            conditions (Conditions): Conditions for filtering and displaying data.
        """
        super().__init__(*args, **kwargs)
        self.is_chk_column_enabled = is_chk_column_enabled
        self.content= None
        
        self._dict = {}
        
        # UI properties
        self.bg_color_primary: str = ft.Colors.with_opacity(1, ft.Colors.SECONDARY_CONTAINER)
        self.bg_color_secondary: str = ft.Colors.with_opacity(0.1, ft.Colors.SECONDARY)
        self.bgcolor=ft.Colors.with_opacity(1, ft.Colors.SECONDARY_CONTAINER)
        self.height=45
        self.bg_color_prin = ft.Colors.with_opacity(1, ft.Colors.SECONDARY_CONTAINER)
        self.bg_color_sec = ft.Colors.with_opacity(0.1, ft.Colors.SECONDARY)
        self.on_click_column = on_click_column
        self.handle_all_row_selected = handle_all_row_selected
        self._data = data
        self._model = model
        self.is_editable = is_editable
        self.conditions = conditions
        
        # self.chk_column = ft.Checkbox(label="", value=False, width=40, tristate=True, on_change=lambda e: self.handle_all_row_selected(e))
    
    def build_header(self):
        list_header_row = []
        self.chk_column = ft.Checkbox(label="", value=False, width=40, tristate=True, on_change=lambda e: self.handle_all_row_selected(e))
        if self.is_chk_column_enabled: list_header_row.append(self.chk_column)
        
        if self.is_editable: list_header_row.append(ft.Container(width=40))
        
        fields_order = self.conditions.fields_order if (self.conditions and self.conditions.fields_order) else [field.name for field in self._model._meta.fields]
    
        for field_name in fields_order:
            col = next((field for field in self._model._meta.fields if field.name == field_name), None)
            if not col:
                continue
            if col.hidden or col.name in self.conditions.fields_excluded if self.conditions else []: 
                continue
            
            
            order_col = ""
            for key in self._dict:
                if key == col.name:
                    order_col = f'{key}-{self._dict[key]}'
                
            # HEADER ALIGMENT    
            if col.aligment == "center":
                header_aligment = ft.MainAxisAlignment.CENTER
            elif col.aligment == "right":
                header_aligment = ft.MainAxisAlignment.END
            else:
                header_aligment = ft.MainAxisAlignment.START
                
            
            icon = ft.Container()
            text_header_expand = None
            sort = getattr(col, "is_sortable", False) if not self.is_editable else False
            if sort:
                icon = ft.Icon(ft.Icons.ARROW_DROP_DOWN) if "desc" in order_col else ft.Icon(ft.Icons.ARROW_DROP_UP)
                text_header_expand = 1
            field_name = col.verbose_name if not self.conditions.fields_descriptions else self.conditions.fields_descriptions.get(col.name, col.verbose_name)
            text_header = ft.Container(
                content=ft.Row(
                    controls=[ft.Text(field_name, weight="bold", expand=text_header_expand),icon],
                    alignment=header_aligment),
                margin=ft.Margin.symmetric(horizontal=0),
                expand=False,
            )

            column_width = getattr(col, "column_width", None)
            container = ft.Container(text_header,
                on_hover=(lambda e: on_hover(e)) if sort else None,
                on_click=(lambda e: on_click(e)) if sort else None,
                # expand=self.conditions.fields_column_width.get(col.name, 1) if self.conditions else 1,
                expand=False,
                width=self.conditions.fields_column_width.get(col.name, column_width) if self.conditions else column_width,
                data=col.name,
                padding=ft.Padding.symmetric(horizontal=5),
                alignment=ft.Alignment.CENTER_LEFT,
                bgcolor=self.bg_color_sec if col.name in order_col else self.bg_color_prin,
                # margin=ft.Margin.symmetric(horizontal=5),
                )
            # container.expand = self.conditions.fields_expand.get(col.name, 1)
            list_header_row.append(container)
        
        self.content = ft.Row(controls=list_header_row, spacing=0, expand=False)
        self.expand = False  # No expandir el header verticalmente
        
        def on_hover(e):
            else_color = None
            if e.control.data in self._dict:
                else_color= ft.Colors.with_opacity(0.1, ft.Colors.SECONDARY)
            else:
                else_color= ft.Colors.with_opacity(1, ft.Colors.SECONDARY_CONTAINER)
            e.control.bgcolor = ft.Colors.with_opacity(0.1, ft.Colors.SECONDARY) if str(e.data).lower() == "true" else else_color
            e.control.update()
                
        def on_click(e):
            if e.control.data in self._dict:
                if self._dict[e.control.data] == "asc":
                    self._dict[e.control.data] = "desc"
                else:
                    self._dict[e.control.data] = "asc"
            else:
                self._dict = {}
                self._dict[e.control.data] = "desc"
            self.build_header()
            self.update()
            if self.on_click_column:
                self.on_click_column(self._dict)
                
    def clean_selection(self):
        self.chk_column.value = False
        if self.is_chk_column_enabled:
            self.chk_column.update()

    def _get_header_alignment(self, col: Any) -> ft.MainAxisAlignment:
        """
        Determines the alignment for a column header.

        Args:
            col (Any): The column to align.

        Returns:
            ft.MainAxisAlignment: The alignment for the column header.
        """
        if col.aligment == "center":
            return ft.MainAxisAlignment.CENTER
        elif col.aligment == "right":
            return ft.MainAxisAlignment.END
        return ft.MainAxisAlignment.START

    def _on_hover(self, e: ft.ControlEvent, col_name: str) -> None:
        """
        Handles hover events on column headers.

        Args:
            e (ft.ControlEvent): The hover event.
            col_name (str): The name of the column being hovered.
        """
        e.control.bgcolor = ft.Colors.with_opacity(0.1, ft.Colors.SECONDARY) if str(e.data).lower() == "true" else self.bg_color_primary
        e.control.update()

    def _on_click(self, e: ft.ControlEvent, col_name: str) -> None:
        """
        Handles click events on column headers to toggle sorting.

        Args:
            e (ft.ControlEvent): The click event.
            col_name (str): The name of the column being clicked.
        """
        if col_name in self._dict:
            self._dict[col_name] = "desc" if self._dict[col_name] == "asc" else "asc"
        else:
            self._dict = {col_name: "desc"}
        self.build_header()
        self.update()
        if self.on_click_column:
            self.on_click_column(self._dict)

    def manage_chk_header(self, len_list_rows_selected: int, len_rows: int) -> None:
        """
        Updates the state of the header checkbox based on the number of selected rows.

        Args:
            len_list_rows_selected (int): The number of selected rows.
            len_rows (int): The total number of rows.
        """
        if not self.is_chk_column_enabled:
            return
        if len_list_rows_selected == len_rows:
            self.chk_column.value = True
        elif len_list_rows_selected == 0:
            self.chk_column.value = False
        else:
            self.chk_column.value = None
        self.content.controls[0].update()

              
class NotDataRowTable(PaginaFija, ft.Container):
    def __init__(self, obj, idx, confirm_delete_row=None, is_editable = False, conditions={}, is_chk_column_enabled=True, handle_on_long_press=None,
                 handle_chk_row_selected=None, handle_row_click=None, get_parent=None, get_children=None, table_ref=None,
                 menu_contextual=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.obj = obj
        self.idx = idx
        self.confirm_delete_row = confirm_delete_row
        self.conditions = conditions
        self.is_editable = is_editable
        self.is_chk_column_enabled = is_chk_column_enabled
        self.handle_on_long_press = handle_on_long_press
        self.handle_chk_row_selected = handle_chk_row_selected
        self.handle_row_click = handle_row_click
        self.is_selected:bool = False
        self.table_ref = table_ref  # Referencia a la tabla
        self.has_focus:bool = False  # Nueva propiedad para tracking de foco

        self.padding = ft.Padding.only(top=0, bottom=0)
        self.border = ft.Border.only(bottom=ft.BorderSide(1, ft.Colors.with_opacity(0.2 , ft.Colors.ON_SURFACE_VARIANT)))
        self.bgcolor= ft.Colors.with_opacity(0.0 if idx%2 == 0 else 0.3  , ft.Colors.SECONDARY_CONTAINER)
        self.original_bgcolor = self.bgcolor  # Guardar color original
        self.focus_bgcolor = ft.Colors.with_opacity(1, ft.Colors.PRIMARY_CONTAINER)  # Color más oscuro cuando tiene foco
        self.selected_bgcolor = ft.Colors.with_opacity(0.5, ft.Colors.PRIMARY_CONTAINER)
        self.alignment=ft.Alignment.CENTER
        self.on_long_press= None if is_editable else lambda e: self.handle_on_long_press(obj)
        if not is_chk_column_enabled and not is_editable:
            self.on_click = lambda e: self._on_row_click()
        # self.on_hover = None if is_editable else lambda e: self.handle_on_hover(e)
        
        self.chk_column = ft.Checkbox(value= False, width=40, height=40, on_change=lambda e: self.handle_on_change_chk_column(e), data=obj)
        self.btn_remove_row = ft.TextButton(content=ft.Row([ft.Icon(icon=ft.Icons.REMOVE, size=28),]),
                                           width=40, height=30,
                                           style=ft.ButtonStyle(padding=ft.Padding.all(5), bgcolor=ft.Colors.TERTIARY_CONTAINER, shape=ft.RoundedRectangleBorder(radius=3)),
                                           on_click=lambda e, idx=idx: self.delete_row())
        
        self.controls = []
        if self.is_chk_column_enabled: 
            self.controls.append(self.chk_column)
        if self.is_editable: 
            self.controls.append(ft.Container(content=self.btn_remove_row, margin=ft.Margin.symmetric(horizontal=0, vertical=0)))
        display_mode = DisplayMode.EDIT if self.is_editable else DisplayMode.VIEW
        self.form = FieldBuilder(obj=obj, layout_mode=LayoutMode.HORIZONTAL, display_mode=display_mode, get_children=get_children,
                                 conditions=self.conditions, page=self.page, get_parent=get_parent, table_ref=self.table_ref, 
                                 row_ref=self)  # Pasar referencia de la fila
        self.controls.append(self.form)
        
        self.expand = False  # No expandir la fila verticalmente
        self.content= ft.Row(controls=self.controls, vertical_alignment=ft.VerticalAlignment.CENTER, spacing=0, expand=False)
        # Clic derecho: menú con las acciones de la fila (si la pantalla las ofrece)
        items = menu_contextual(obj) if menu_contextual else []
        if items:
            self.content = ft.ContextMenu(
                content=self.content,
                secondary_items=[
                    ft.PopupMenuItem(content=texto, icon=icono, on_click=lambda e, fn=fn: fn())
                    for texto, icono, fn in items
                ],
            )
        # Styles of the row
        self.height=SM.get(SK.TABLE_ROW_HEIGHT, None)
        
    def set_row_focus(self, has_focus: bool):
        """
        Cambia el color de la fila según si tiene foco o no.
        
        Args:
            has_focus (bool): True si algún input de la fila tiene foco, False en caso contrario
        """
        self.has_focus = has_focus
        
        if has_focus:
            self.bgcolor = self.focus_bgcolor
        else:
            # Restaurar color original basado en el índice de la fila
            self.bgcolor = ft.Colors.with_opacity(0.0 if self.idx%2 == 0 else 0.3, ft.Colors.SECONDARY_CONTAINER)
            
        self.update()
        
    def notify_focus_gained(self, field_name: str):
        """
        Notifica que un campo de esta fila ha ganado el foco.
        
        Args:
            field_name (str): Nombre del campo que ganó el foco
        """
        # Notificar a la tabla para que quite el foco de otras filas
        if self.table_ref and hasattr(self.table_ref, 'set_focused_row'):
            self.table_ref.set_focused_row(self)
            
        self.set_row_focus(True)
        
    def notify_focus_lost(self, field_name: str):
        """
        Notifica que un campo de esta fila ha perdido el foco.
        
        Args:
            field_name (str): Nombre del campo que perdió el foco
        """
        # Pequeño delay para verificar si otro campo de la misma fila ganó el foco
        async def check_and_remove_focus():
            await asyncio.sleep(0.1)  # Esperar 100ms
            # Si ningún campo de la fila tiene foco, quitar el highlight
            if not self._has_any_field_focused():
                self.set_row_focus(False)
        
        # Esperar sin bloquear la UI
        if self.page:
            self.page.run_task(check_and_remove_focus)
        
    def _has_any_field_focused(self) -> bool:
        """
        Verifica si algún campo de la fila tiene foco actualmente.
        
        Returns:
            bool: True si algún campo tiene foco, False en caso contrario
        """
        try:
            if hasattr(self.form, 'form_fields') and hasattr(self.form.form_fields, 'list_fields'):
                for field in self.form.form_fields.list_fields:
                    if hasattr(field, 'content') and hasattr(field.content, 'focused'):
                        if field.content.focused:
                            return True
                    # También verificar en el control directamente
                    if hasattr(field, 'get_field'):
                        control = field.get_field()
                        if hasattr(control, 'focused') and control.focused:
                            return True
            return False
        except Exception as e:
            print(f"Error checking field focus: {e}")
            return False
     
    def _on_row_click(self):
        new_state = not self.is_selected
        if self.table_ref and new_state:
            for row in self.table_ref.component_body.controls:
                if row is not self and row.is_selected:
                    row.is_selected = False
                    row.bgcolor = row.original_bgcolor
                    row.update()
        self.is_selected = new_state
        self.bgcolor = self.selected_bgcolor if self.is_selected else self.original_bgcolor
        self.update()
        if self.handle_row_click:
            self.handle_row_click(self)

    def handle_on_change_chk_column(self, e):
        if e.control.value == True:
            self.is_selected = True
        else:
            self.is_selected = False
        self.handle_chk_row_selected(e)

    def check_is_selected(self):
        return self.is_selected

    def clean_selection(self):
        self.is_selected = False
        self.bgcolor = self.original_bgcolor
        if self.is_chk_column_enabled:
            self.chk_column.value = False
            self.chk_column.update()
        else:
            self.update()
    
    def handle_on_hover(self, e):
        self.bgcolor =  ft.Colors.with_opacity(0.8, ft.Colors.SECONDARY_CONTAINER) if str(e.data).lower() == "true" else ft.Colors.with_opacity(0.1 if self.idx%2 == 0 else 0.4  , ft.Colors.SECONDARY_CONTAINER)
        self.update()
        
    def save(self, **kwargs):
        return self.form.save(**kwargs)
        
    def full_clean(self, **kwargs):
        return self.form.full_clean(**kwargs)
        
    def delete_obj(self):
        if not self.obj._state.adding:
            self.obj.delete()
            
    def delete_row(self):
        if not self.obj._state.adding or self.form.check_is_dirty():
            DlgConfirm(page=self.page, title="Confirma que desea eliminar los registros?", fn_yes=lambda: self.handle_remove_yes())
        else:
            self.handle_remove_yes()
                 
    def handle_remove_yes(self):
        if self.obj._state.adding:
            self.is_selected = True
            self.confirm_delete_row()
        else:
            try:
                elemento = self.obj
                relaciones = self.obtener_relaciones(elemento)
                
                if relaciones:
                    self.dlg_msg = ft.AlertDialog(title=ft.Text(f"No se puede eliminar {str(elemento)}. Registros relacionados: {relaciones}"))
                    abrir_dialogo(self.page, self.dlg_msg)
                else:
                    elemento.delete()
                self.is_selected = True
                self.confirm_delete_row()
            except Exception as e:
                self.dlg_msg = ft.AlertDialog(title=ft.Text(f"Error al eliminar los registros: {e}"))
                abrir_dialogo(self.page, self.dlg_msg)
            
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

    def set_value_chk_row(self, value):
        self.is_selected = value
        self.chk_column.value = value
        # self.chk_column.update()
   
    def handle_row_selected(self, e):
        list_rows_selected = self.list_rows_selected()
        self.header.manage_chk_header(len(list_rows_selected), len(self.rows))
    
        if self.on_row_selected:
            self.on_row_selected(list_rows_selected)
            
        e.control.update()
      
    def list_rows_selected(self):
        return [row.data["obj_original"] for row in self.controls if row.data["chk"].value]
            
    def _confirm_delete_row(self):
        self.is_selected = True
        if self.confirm_delete_row:
            self.confirm_delete_row()
    
    def set_is_selected(self, value):
        self.is_selected = value
    
    def check_is_dirty(self):
        return self.form.check_is_dirty()
            
    def handle_chk_selected(self, e):
        if e.control.value == None:
            e.control.value = False
            e.control.update()
            
        if e.control.value:
            for row in self.rows:
                row[0].value = True
                row[0].update()
        else:
            for row in self.rows:
                row[0].value = False
                row[0].update()
                
        list_rows_selected = self.list_rows_selected()
        if self.on_row_selected:
            self.on_row_selected(list_rows_selected)


class NotDataTable(PaginaFija, ft.Container):
    """
    A generic data table component for displaying, editing, and managing rows of data.
    """
    def __init__(
        self,
        is_chk_column_enabled: bool = True,
        is_editable: bool = False,
        handle_on_long_press: Optional[Callable[[Any], None]] = None,
        handle_on_chk_row_click: Optional[Callable[[ft.ControlEvent], None]] = None,
        on_row_selected: Optional[Callable[[List[Any]], None]] = None,
        on_click_column: Optional[Callable[[ft.ControlEvent], None]] = None,
        conditions: Conditions = Conditions(),
        content_modified_callback: Optional[Callable[[List[Any]], None]] = None,
        page: Optional[ft.Page] = None,
        get_parent: Optional[Callable[[], Any]] = None,
        enable_cell_navigation: bool = True,  # Nueva opción para habilitar navegación
        menu_contextual: Optional[Callable[[Any], list]] = None,  # obj -> [(texto, icono, fn)]
        *args,
        **kwargs,
    ):
        """
        Initializes the NotDataTable component.

        Args:
            is_chk_column_enabled (bool): Whether the checkbox column is enabled.
            is_editable (bool): Whether the table is editable.
            handle_on_long_press (Optional[Callable[[Any], None]]): Callback for long press events on rows.
            handle_on_chk_row_click (Optional[Callable[[ft.ControlEvent], None]]): Callback for checkbox row clicks.
            on_row_selected (Optional[Callable[[List[Any]], None]]): Callback for row selection events.
            handle_on_chk_header_click (Optional[Callable[[ft.ControlEvent], None]]): Callback for header checkbox clicks.
            conditions (Conditions): Conditions for filtering and displaying data.
            page (Optional[ft.Page]): The parent page.
            get_parent (Optional[Callable[[], Any]]): Function to get the parent object.
        """
        super().__init__(*args, **kwargs)
        self.expand: bool = True
        self.header: Optional[NotDataTableHeader] = None
        self.page: Optional[ft.Page] = page
        self.rows: List[NotDataRowTable] = []
        self.spacing: int = 0
        self._data: Optional[List[Any]] = None
        self._model: Optional[Any] = None
        self.is_chk_column_enabled: bool = is_chk_column_enabled
        self.is_editable: bool = is_editable
        self.is_being_edited: bool = False
        self.on_row_selected: Optional[Callable[[List[Any]], None]] = on_row_selected
        self.handle_on_long_press: Optional[Callable[[Any], None]] = handle_on_long_press
        self.handle_on_chk_row_click: Optional[Callable[[ft.ControlEvent], None]] = handle_on_chk_row_click
        self.on_click_column: Optional[Callable[[Dict[str, str]], None]] = on_click_column
        self.get_parent: Optional[Callable[[], Any]] = get_parent
        self.conditions: Conditions = conditions
        self.content_modified_callback = content_modified_callback
        self.enable_cell_navigation: bool = enable_cell_navigation
        self.menu_contextual = menu_contextual
        
        # Sistema de navegación entre celdas
        self._navigation_map: Dict[str, Dict[str, Any]] = {}  # Mapa de campos editables
        self._current_focus: Optional[str] = None  # Campo actual con foco
        self._focused_row: Optional[NotDataRowTable] = None  # Nueva propiedad para tracking de fila con foco

        # Components
        self.dict_order: Dict[str, str] = {}
        self.chk_column: Optional[ft.Checkbox] = None
        self.component_buttons: ft.Container = ft.Container()
        self.component_header: ft.Container = ft.Container(content=None, expand=False)
        self.component_body: ft.Column = ft.Column(controls=[], spacing=0, expand=False, tight=True)
        self.component_footer: ft.Column = ft.Column(controls=[], spacing=0, expand=False)
        
        # Cache de objetos modificados para mantener cambios al cambiar de página
        self._modified_objects: Dict[Any, Any] = {}  # {id_objeto: objeto_modificado}
        self.component_table:ft.Column = ft.Column(
            controls=[
                self.component_header,
                self.component_body,
                self.component_footer,
            ],
            spacing=0,
            expand=False,  # No expandir verticalmente, mantener altura natural
            alignment=ft.MainAxisAlignment.START,
            tight=True,  # Usar tamaño natural de los hijos
        )
        
        # Contenedor que se adapta al contenido de la tabla
        self.table_container = ft.Container(
            content=self.component_table,
            width=None,  # Ancho determinado por el contenido
            expand=False,  # No expandir el contenedor
        )
        
        self.controls: List[ft.Control] = [
            self.table_container,
            self.component_footer,
        ]
        self.content = self.table_container
        self.expand = True  # La tabla debe expandirse para llenar el espacio disponible
        self.width = None  # Permitir que el ancho sea determinado por el contenido
        # Establecer un ancho mínimo para asegurar que todas las columnas sean visibles
        self.min_width = 800  # Ancho mínimo para la tabla
        # Buttons for adding and removing rows
        self.btn_add_row: ft.TextButton = self._create_add_row_button()
        self.btn_remove_row: ft.TextButton = self._create_remove_row_button()

    def set_focused_row(self, row):
        """
        Establece qué fila tiene el foco actualmente y quita el foco de las demás.
        
        Args:
            row (NotDataRowTable): La fila que tiene el foco
        """
        # Quitar foco de la fila anterior
        if self._focused_row and self._focused_row != row:
            self._focused_row.set_row_focus(False)
            
        # Establecer nueva fila con foco
        self._focused_row = row

    def clear_all_row_focus(self):
        """
        Quita el foco de todas las filas.
        """
        if self._focused_row:
            self._focused_row.set_row_focus(False)
            self._focused_row = None
       
    def _create_add_row_button(self) -> ft.TextButton:
        """
        Creates the button for adding new rows.

        Returns:
            ft.TextButton: The add row button.
        """
        return ft.TextButton(
            content=ft.Row([ft.Icon(icon=ft.Icons.ADD, size=28)]),
            width=40,
            height=40,
            style=ft.ButtonStyle(
                padding=ft.Padding.all(5),
                bgcolor=ft.Colors.PRIMARY_CONTAINER,
                shape=ft.RoundedRectangleBorder(radius=3),
            ),
            on_click=lambda e: self.add_row(),
        )
        
    def clean_selection(self):
        for row in self.component_body.controls:
            row.clean_selection()
            
        self.header.clean_selection()
         
    def _create_remove_row_button(self) -> ft.TextButton:
        """
        Creates the button for removing selected rows.

        Returns:
            ft.TextButton: The remove row button.
        """
        return ft.TextButton(
            content=ft.Row([ft.Icon(icon=ft.Icons.REMOVE, size=28)]),
            width=40,
            height=40,
            style=ft.ButtonStyle(
                padding=ft.Padding.all(5),
                bgcolor=ft.Colors.TERTIARY_CONTAINER,
                shape=ft.RoundedRectangleBorder(radius=3),
            ),
            on_click=lambda e: self.delete_selected_rows(e),
        ) 
        
    def set_data(self, data: List[Any], clear_cache: bool = False) -> None:
        """
        Sets the data for the table.

        Args:
            data (List[Any]): The data to display in the table.
            clear_cache (bool): Si True, limpia el cache de modificaciones. Default False.
        """
        self._data = data
        # Solo limpiar cache si se solicita explícitamente
        if clear_cache:
            self.clear_cache()

    def set_model(self, model: Any) -> None:
        """
        Sets the model for the table.

        Args:
            model (Any): The model to use for the table.
        """
        self._model = model

        
    def build_header(self) -> None:
        """
        Builds the table header.
        """
        self.header = NotDataTableHeader(
            is_chk_column_enabled=self.is_chk_column_enabled,
            data=self._data,
            model=self._model,
            is_editable=self.is_editable,
            conditions=self.conditions,
            handle_all_row_selected=self.handle_on_click_chk_row,
            on_click_column=self.on_click_column,
        )
        self.header.build_header()
        self.component_header.content = self.header

    def build_body(self):
        """
        Builds the table body with rows of data.
        """
        list_data_row = []
        for idx, obj in enumerate(self._data):
            # Usar objeto modificado si existe, sino usar el original
            obj_id = getattr(obj, 'id', id(obj))  # Usar id de Django o id de memoria
            modified_obj = self._modified_objects.get(obj_id, obj)
            
            row = NotDataRowTable(
                obj=modified_obj,
                idx=idx,
                is_editable=self.is_editable,
                conditions=self.conditions,
                handle_on_long_press=self.handle_on_long_press,
                is_chk_column_enabled=self.is_chk_column_enabled,
                handle_chk_row_selected=self.handle_chk_row_selected,
                handle_row_click=self._handle_row_click_selection if not self.is_chk_column_enabled else None,
                confirm_delete_row=self.confirm_delete_row,
                get_children=self.get_children,
                get_parent=self.get_parent,
                table_ref=self,
                menu_contextual=self.menu_contextual,
            )
            list_data_row.append(row)
            
        self.component_body.controls = list_data_row
        
        # Construir mapa de navegación después de crear las filas
        if self.enable_cell_navigation and self.is_editable:
            # Programar construcción con delay para asegurar inicialización completa
            def build_nav_map():
                # print("Building navigation map...")
                self.navigation_map_activate()
            
            # Usar threading para programar el delay
            async def delayed_build():
                await asyncio.sleep(0.3)  # Esperar un poco más para asegurar montaje
                build_nav_map()

            if self.page:
                self.page.run_task(delayed_build)
    
    def build_footer(self):
        """
        Builds the table footer with the button btn_add_row.
        """
        if self.is_editable:
            self.component_footer.controls.append(
                ft.Container(
                    content=self.btn_add_row, 
                    margin=ft.Margin.symmetric(horizontal=0, vertical=5)
                )
            )   
            
    def get_children(self):
        return [row.form for row in self.component_body.controls]
    
    def confirm_delete_row(self):
        self.component_body.controls = [row for row in self.component_body.controls if not row.check_is_selected()]
        if self.content_modified_callback:
            self.content_modified_callback(self.get_all_objects())
        self.update_body()
        
        # Reconstruir mapa de navegación después de eliminar filas
        if self.enable_cell_navigation and self.is_editable:
            self.build_navigation_map()
        
    def update_body(self):
        self.component_body.update()
        
    def cache_modified_object(self, obj):
        """
        Guarda una referencia al objeto modificado para mantener cambios.
        
        Args:
            obj: El objeto que ha sido modificado
        """
        obj_id = getattr(obj, 'id', id(obj))
        self._modified_objects[obj_id] = obj
    
    def get_cached_object(self, obj):
        """
        Obtiene el objeto modificado del cache si existe.
        
        Args:
            obj: El objeto original
            
        Returns:
            El objeto modificado si existe en cache, sino el original
        """
        obj_id = getattr(obj, 'id', id(obj))
        cached_obj = self._modified_objects.get(obj_id, obj)
        return cached_obj
    
    def get_modified_objects(self) -> Dict[Any, Any]:
        """
        Obtiene todos los objetos modificados en cache.
        
        Returns:
            Dict[Any, Any]: Diccionario de objetos modificados {id_objeto: objeto_modificado}
        """
        return self._modified_objects
    
    def clear_cache(self):
        """Limpia el cache de objetos modificados."""
        self._modified_objects.clear()
    
    def save_all_modified_objects(self):
        """
        Guarda todos los objetos modificados en la base de datos.
        
        Returns:
            bool: True si se guardaron todos correctamente, False si hubo errores
        """
        try:
            success = True
            for obj_id, modified_obj in self._modified_objects.items():
                try:
                    if hasattr(modified_obj, '_state') and (modified_obj._state.adding or hasattr(modified_obj, 'save')):
                        modified_obj.save()
                except Exception as e:
                    print(f"Error al guardar objeto {obj_id}: {e}")
                    success = False
            
            if success:
                self.clear_cache()  # Solo limpiar si todo se guardó correctamente
                
            return success
        except Exception as e:
            print(f"Error general al guardar objetos modificados: {e}")
            return False
    
    def get_modified_objects_count(self):
        """Retorna la cantidad de objetos modificados en cache."""
        return len(self._modified_objects)
        
    def create_table(self):
        self.build_header()
        self.build_body()
        self.build_footer()
        
        # Construir mapa de navegación después de crear la tabla completa
        self.navigation_map_activate()

    def navigation_map_activate(self):
        if self.enable_cell_navigation:
            self.build_navigation_map()
        
    def get_selectd_objects(self):
        return [row.obj for row in self.component_body.controls if row.check_is_selected()]
    
    def get_all_objects(self):
        """
        Returns all objects in the table.
        
        Returns:
            List[Any]: A list of all objects in the table.
        """
        return [row.obj for row in self.component_body.controls]
    
    def get_all_rows(self):
        """
        Returns all rows in the table.
        
        Returns:
            List[NotDataRowTable]: A list of all rows in the table.
        """
        return self.component_body.controls
    
    def get_count_objects(self):
        """
        Returns the count of all objects in the table.
        
        Returns:
            int: The count of all objects in the table.
        """
        return len(self._data) if self._data else 0
    
    def set_all_rows_selected(self, value: bool) -> None:
        """
        Sets the selection state of all rows in the table.

        Args:
            value (bool): True to select all rows, False to deselect all.
        """
        for row in self.component_body.controls:
            row.chk_column.value = value
            row.set_is_selected(value)
            
        self.header.chk_column.value = value
    
    def _handle_row_click_selection(self, row):
        list_rows_selected = self.list_rows_selected()
        self.header.manage_chk_header(len(list_rows_selected), len(self.component_body.controls))
        if self.on_row_selected:
            self.on_row_selected(list_rows_selected)

    def handle_chk_row_selected(self, e):
        list_rows_selected = self.list_rows_selected()
        self.header.manage_chk_header(len(list_rows_selected), len(self.component_body.controls))

        if self.on_row_selected:
            self.on_row_selected(list_rows_selected)

        e.control.update()

    def get_header_chk_column(self):
        """
        Returns the checkbox control in the header for selecting all rows.
        
        Returns:
            ft.Checkbox: The checkbox control in the header.
        """
        return self.header.chk_column if self.header else None
        
    def list_rows_selected(self):
        return [row.obj for row in self.component_body.controls if row.check_is_selected()]
        
    def handle_on_click_chk_row(self, e):
        if e.control.value == None:
            e.control.value = False
            e.control.update()
        
        for row in self.component_body.controls:
            row.set_value_chk_row(e.control.value)
            
                
        list_rows_selected = self.list_rows_selected()
        if self.on_row_selected:
            self.on_row_selected(list_rows_selected)
        self.page.update()
        
    def add_row(self):
        """
        Adds a new row to the table.
        """
        idx = len(self.component_body.controls)
        new_row = NotDataRowTable(
            self._model(),
            idx,
            is_editable=self.is_editable,
            conditions=self.conditions,
            handle_on_long_press=self.handle_on_long_press,
            is_chk_column_enabled=self.is_chk_column_enabled,
            handle_chk_row_selected=self.handle_chk_row_selected,
            handle_row_click=self._handle_row_click_selection if not self.is_chk_column_enabled else None,
            confirm_delete_row=self.confirm_delete_row,
            get_children=self.get_children,
            get_parent=self.get_parent,
            table_ref=self,
        )
        self.component_body.controls.append(new_row)
        self.update_body()
        
        # Reconstruir mapa de navegación para incluir la nueva fila
        if self.enable_cell_navigation and self.is_editable:
            self.build_navigation_map()
    
    def save(self, **kwargs):
        """
        Saves all rows in the table.

        Returns:
            bool: True if all rows were saved successfully, False otherwise.
        """
        return all(row.save(**kwargs) for row in self.component_body.controls)
    
    def check_is_dirty(self) -> list:
        """
        Checks if any row in the table has unsaved changes.

        Returns:
            bool: True if there are unsaved changes, False otherwise.
        """
        return [row.check_is_dirty() for row in self.component_body.controls if row.check_is_dirty() != None]
    
    def full_clean(self) -> bool:
        """
        Performs full clean on all rows in the table.

        Returns:
            list: A list of errors if any, otherwise an empty list.
        """
        try:
            return all(row.full_clean() for row in self.get_all_rows())
        except Exception as e:
            return False
    
    def build_navigation_map(self):
        """
        Construye un mapa de navegación de todos los campos editables de la tabla.
        Crea coordenadas (row_idx, field_idx) para cada campo editable.
        """
        # Limpiar mapa actual
        self._navigation_map.clear()
        
        # print(f"DEBUG: Building navigation map for {len(self.component_body.controls)} rows")
        
        for row_idx, row in enumerate(self.component_body.controls):
            if hasattr(row, 'form') and hasattr(row.form, 'form_fields') and hasattr(row.form.form_fields, 'get_original_fields'):
                for field_idx, field in enumerate(row.form.form_fields.get_original_fields()):
                    # En ManagerField, el control está en field.content (devuelto por get_original_fields)
                    control = field
                    
                    # Solo incluir campos que tengan on_submit o que sean SearchField
                    # Ahora que SearchField tiene propiedad on_submit, hasattr(control, 'on_submit') debería ser True
                    if control and hasattr(control, 'on_submit'):
                        field_key = f"row_{row_idx}_field_{field_idx}"
                        self._navigation_map[field_key] = {
                            'row_idx': row_idx,
                            'field_idx': field_idx,
                            'field_name': getattr(field, 'name', ''),
                            'control': control,
                        }
                        
                        # Configurar el evento on_submit para navegación
                        # Guardar el original solo si no lo hemos guardado ya (evita cadenas infinitas)
                        if not hasattr(control, '_original_on_submit'):
                            # Para CustomIntegerField, ya viene definido en __init__
                            # Para otros, lo guardamos ahora
                            if not hasattr(control, '_original_on_submit'):
                                control._original_on_submit = control.on_submit
                        
                        original_on_submit = control._original_on_submit
                        
                        # Crear el navigation handler con el original 
                        navigation_handler = self._create_navigation_handler(field_key, original_on_submit)
                        
                        # Intentar usar set_on_submit si existe (CustomIntegerField)
                        if hasattr(control, 'set_on_submit'):
                            control.set_on_submit(navigation_handler)
                        else:
                            # Para otros controles directos
                            control.on_submit = navigation_handler
                        
        # print(f"Navigation map built with {len(self._navigation_map)} editable fields")
    
    def _create_navigation_handler(self, current_field_key: str, original_handler: Optional[Callable] = None):
        """
        Crea un manejador de navegación que se ejecuta cuando se presiona Enter.
        
        Args:
            current_field_key: Clave del campo actual
            original_handler: Manejador original del campo (si existe)
        
        Returns:
            Función manejadora de navegación
        """
        def navigation_handler(e):
            # print(f"Navigation handler called for {current_field_key}")
            # print(f"Original handler: {original_handler}")
            
            # Ejecutar el manejador original si existe
            if original_handler:
                # print(f"Calling original handler for {current_field_key}")
                original_handler(e)
            
            # Navegar al siguiente campo
            # print(f"Navigating from {current_field_key}")
            self._navigate_to_next_field(current_field_key)
        
        return navigation_handler
    
    def _navigate_to_next_field(self, current_field_key: str):
        """
        Navega al siguiente campo editable disponible.
        Lógica: Derecha → Abajo → Siguiente fila
        
        Args:
            current_field_key: Clave del campo actual
        """
        if current_field_key not in self._navigation_map:
            # Si no está en el mapa, buscar el primer campo disponible
            if self._navigation_map:
                first_key = min(self._navigation_map.keys(), key=lambda k: (
                    self._navigation_map[k]['row_idx'], 
                    self._navigation_map[k]['field_idx']
                ))
                current_field_key = first_key
            else:
                return
        
        current_info = self._navigation_map[current_field_key]
        current_row = current_info['row_idx']
        current_field = current_info['field_idx']
        
        # Buscar el siguiente campo disponible
        next_field_key = self._find_next_editable_field(current_row, current_field)
        
        if next_field_key and next_field_key in self._navigation_map:
            next_control = self._navigation_map[next_field_key]['control']
            
            # Intentar hacer focus y seleccionar texto
            success = False
            try:
                # Método 1: focus() directo
                if hasattr(next_control, 'focus'):
                    next_control.focus()
                    success = True
                    # print(f"Focus successful on {next_field_key}")
                
                # Método 2: focused property
                elif hasattr(next_control, 'focused'):
                    next_control.focused = True
                    if hasattr(next_control, 'update'):
                        next_control.update()
                    success = True
                    # print(f"Focused property set on {next_field_key}")
                
                # Seleccionar todo el texto si el campo lo soporta
                if success:
                    self._current_focus = next_field_key
                    
            except Exception as e:
                print(f"Error al hacer focus en {next_field_key}: {e}")
    
    def _find_next_editable_field(self, current_row: int, current_field: int) -> Optional[str]:
        """
        Encuentra el siguiente campo editable usando la lógica: Derecha → Abajo → Siguiente fila
        
        Args:
            current_row: Índice de la fila actual
            current_field: Índice del campo actual
        
        Returns:
            Clave del siguiente campo o None si no hay más campos
        """
        # 1. Buscar a la derecha en la misma fila
        for field_idx in range(current_field + 1, self._get_max_fields_in_row(current_row)):
            next_key = f"row_{current_row}_field_{field_idx}"
            if next_key in self._navigation_map:
                return next_key
        
        # 2. Buscar en la siguiente fila (desde el primer campo)
        for row_idx in range(current_row + 1, len(self.component_body.controls)):
            for field_idx in range(self._get_max_fields_in_row(row_idx)):
                next_key = f"row_{row_idx}_field_{field_idx}"
                if next_key in self._navigation_map:
                    return next_key
        
        # 3. Si no hay más campos, volver al primero (ciclo)
        for row_idx in range(len(self.component_body.controls)):
            for field_idx in range(self._get_max_fields_in_row(row_idx)):
                next_key = f"row_{row_idx}_field_{field_idx}"
                if next_key in self._navigation_map:
                    return next_key
        
        return None
    
    def _get_max_fields_in_row(self, row_idx: int) -> int:
        """
        Obtiene el número máximo de campos en una fila específica.
        
        Args:
            row_idx: Índice de la fila
        
        Returns:
            Número máximo de campos en la fila
        """
        if row_idx >= len(self.component_body.controls):
            return 0
            
        row = self.component_body.controls[row_idx]
        if hasattr(row, 'form') and hasattr(row.form, 'form_fields') and hasattr(row.form.form_fields, 'get_original_fields'):
            return len(row.form.form_fields.get_original_fields())

        return 0
    
    def focus_first_editable_field(self):
        """
        Hace foco en el primer campo editable de la tabla.
        """
        if self._navigation_map:
            first_key = min(self._navigation_map.keys(), key=lambda k: (
                self._navigation_map[k]['row_idx'], 
                self._navigation_map[k]['field_idx']
            ))
            if first_key:
                self._navigate_to_next_field(f"row_-1_field_-1")  # Truco para ir al primer campo
    
    def get_navigation_info(self) -> Dict[str, Any]:
        """
        Obtiene información sobre el estado actual de navegación.
        
        Returns:
            Diccionario con información de navegación
        """
        fields_info = []
        for key, info in self._navigation_map.items():
            fields_info.append({
                'key': key,
                'row': info['row_idx'],
                'field': info['field_idx'],
                'name': info['field_name'],
                'control_type': type(info['control']).__name__,
                'has_focus_method': hasattr(info['control'], 'focus'),
                'has_focused_property': hasattr(info['control'], 'focused'),
                'has_on_submit': hasattr(info['control'], 'on_submit'),
            })
        
        return {
            'total_editable_fields': len(self._navigation_map),
            'current_focus': self._current_focus,
            'navigation_enabled': self.enable_cell_navigation and self.is_editable,
            'fields_detail': fields_info,
        }
    
    def debug_navigation(self):
        """
        Método de debug para imprimir información de navegación.
        """
        info = self.get_navigation_info()
        print("=== DEBUG NAVIGATION ===")
        print(f"Navigation enabled: {info['navigation_enabled']}")
        print(f"Total editable fields: {info['total_editable_fields']}")
        print(f"Current focus: {info['current_focus']}")
        print("\nFields detail:")
        for field_info in info['fields_detail']:
            print(f"  {field_info['key']}: {field_info['name']} ({field_info['control_type']})")
            print(f"    Row: {field_info['row']}, Field: {field_info['field']}")
            print(f"    Focus method: {field_info['has_focus_method']}, Focused prop: {field_info['has_focused_property']}")
            print(f"    On submit: {field_info['has_on_submit']}")
            print()
        print("========================")
    
    def test_navigation(self):
        """
        Método de prueba para simular navegación entre campos.
        """
        if not self._navigation_map:
            print("No navigation map available. Building...")
            self.build_navigation_map()
        
        if not self._navigation_map:
            print("No editable fields found for navigation.")
            return
        
        # Obtener el primer campo
        first_key = min(self._navigation_map.keys(), key=lambda k: (
            self._navigation_map[k]['row_idx'], 
            self._navigation_map[k]['field_idx']
        ))
        
        print(f"Testing navigation starting from: {first_key}")
        self._navigate_to_next_field(f"row_-1_field_-1")  # Truco para ir al primer campo