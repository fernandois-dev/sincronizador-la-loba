import copy
import flet as ft
from utilities.flet_compat import PaginaFija
from django.core.exceptions import ValidationError

from components.custom_input import DisplayMode, LayoutMode, ManagerField
from utilities.conditions import Conditions


class FieldFactory(PaginaFija, ft.Container):
    def __init__(self, obj, get_parent=None, layout_mode=LayoutMode.VERTICAL, conditions=Conditions(), display_mode=DisplayMode.EDIT,
                 get_children=None, page: ft.Page = None, table_ref=None, row_ref=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.content = None
        self.init_values = {}
        self.list_fields = []
        self.get_parent = get_parent
        self.page = page
        self.conditions = conditions
        self.is_dirty = None
        self.obj = obj
        self.original_obj = copy.deepcopy(obj)
        self.layout_mode = layout_mode
        self.display_mode = display_mode
        self.get_children = get_children
        self.table_ref = table_ref  # Referencia a la tabla
        self.row_ref = row_ref  # Nueva referencia a la fila
        self.expand = 1
        
        self.create_fields()
        
        
    def create_fields(self):
        self.init_values = {}
        self.content = []
        list_fields = []
        
        fields_order = self.conditions.fields_order if (self.conditions and self.conditions.fields_order) else [field.name for field in self.obj._meta.fields]
        
        for field_name in fields_order:
            field = next((field for field in self.obj._meta.fields if field.name == field_name), None)
            if not field: continue
            if self.conditions and self.conditions.fields_excluded and field.name in self.conditions.fields_excluded: continue

            display_mode = self.display_mode if not self.conditions else self.conditions.overrides_display_mode.get(field.name, self.display_mode)

            value = getattr(self.obj, field.name, None)
            # instancia el manejo de los campos
            manager_field = ManagerField(
                display_mode=display_mode,
                input_type=type(field).__name__, 
                layout_mode=self.layout_mode, 
                conditions=self.conditions
            )
            
            # Crear manejadores de foco si estamos en una tabla
            on_focus_handler = None
            on_blur_handler = None
            if self.row_ref and hasattr(self.row_ref, 'notify_focus_gained'):
                on_focus_handler = lambda field_name=field.name: self.row_ref.notify_focus_gained(field_name)
                on_blur_handler = lambda field_name=field.name: self.row_ref.notify_focus_lost(field_name)
            
            manager_field.build_field(label=field.verbose_name, on_change=self.create_on_change_handler(field), 
                                      value=value, 
                                      field=field, 
                                      name=field.name, 
                                      page=self.page, 
                                      obj=self.obj,
                                      on_focus=on_focus_handler,
                                      on_blur=on_blur_handler
                                      )
            if self.layout_mode == LayoutMode.HORIZONTAL and display_mode == DisplayMode.EDIT:
                manager_field.set_light_edit_mode()
            
            list_fields.append(manager_field)
        self.list_fields = list_fields        
           
        for field in self.list_fields:
            if "ForeignKey" in type(field).__name__:
                self.init_values[field.name] = field.related_model(id=field.value) if field.value else " "
            else:
                self.init_values[field.name] = field.value
        
        if self.layout_mode == LayoutMode.VERTICAL:
            self.content = ft.Column(controls=self.list_fields, spacing=5)
        elif self.layout_mode == LayoutMode.HORIZONTAL_WRAP:
            self.content = ft.Row(controls=self.list_fields, wrap=True, spacing=10, run_spacing=10)
        else:
            self.content = ft.Row(controls=self.list_fields, spacing=2)
    
    def get_fields(self):
        return self.list_fields

    def get_original_fields(self):
        return [field.get_field() for field in self.list_fields if field.name in self.init_values]

    def create_on_change_handler(self, col):
        def on_change(e, value = None):
            def update_depentents(obj, col_name, children=None):
                for field_name, depend_calculation in self.conditions.fields_calculations.items():
                    depends = depend_calculation.get("depends", [])
                    calculation = depend_calculation.get("calculation", None)
                    callback_pos_calculation = depend_calculation.get("callback_pos_calculation", None)
                    if col_name in depends:  # Evitar recalcular el mismo campo
                        if"__parent__" in field_name:
                            form_parent, obj_parent = self.get_parent()
                            aux_field_name = field_name.replace("__parent__", "")
                            new_value = calculation(form_parent.obj, children)
                            setattr(obj_parent, aux_field_name, new_value)
                            form_parent.check_is_dirty(recheck=True)
                            # Actualizar el control correspondiente en el formulario del padre
                            control = form_parent.get_filed_by_name(aux_field_name)
                            control.set_value(new_value)
                            control.update()
                        else:
                            new_value = calculation(obj)
                            setattr(obj, field_name, new_value)
                            # Actualizar el control correspondiente
                            for control in self.content.controls:
                                if control.name == field_name:
                                    control.set_value(new_value)
                                    control.update()
                        if callback_pos_calculation:
                            callback_pos_calculation(obj)
                        update_depentents(obj, col_name=field_name, children=children)
                        
             
            setattr(self.obj, col.name, e.control.value if e else value)
            children = [child.obj for child in self.get_children()] if self.get_children else []
            update_depentents(self.obj, col.name, children=children) # Actualizar los campos dependientes
            self.is_dirty = self.compare_objects(self.original_obj, self.obj)

            # Notificar a la tabla que el objeto ha sido modificado
            self._notify_object_modified()
             
        return on_change
    
    def compare_objects(self, original, copia) -> object:
        for field in original._meta.fields:
            value1 = getattr(original, field.name, None)
            value2 = getattr(copia, field.name, None)
            if value1 != value2:
                return copia
        return None
    
    def check_is_dirty(self, recheck=False):
        if recheck:
            self.is_dirty = self.compare_objects(self.original_obj, self.obj)
        return self.is_dirty
    
    def check_is_horizontal(self):
        return self.layout_mode == LayoutMode.HORIZONTAL
    
    def set_original_obj(self, obj):
        self.original_obj = copy.deepcopy(obj)
        self.is_dirty = None
    
    def _notify_object_modified(self):
        """Notifica a la tabla padre que el objeto ha sido modificado."""
        if self.table_ref and hasattr(self.table_ref, 'cache_modified_object'):
            self.table_ref.cache_modified_object(self.obj)
    

class FieldBuilder(PaginaFija, ft.Column):
    def __init__(self, obj, get_parent=None, layout_mode=LayoutMode.VERTICAL, display_mode=DisplayMode.EDIT,  conditions=Conditions(),
                 page: ft.Page= None, get_children=None, table_ref=None, row_ref=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.controls = []
        self.layout_mode = layout_mode
        self.expand = True
        self.conditions = conditions
        self.spacing=0
        self.page = page
        self.obj = obj
        self.table_ref = table_ref  # Referencia a la tabla para notificar cambios
        self.row_ref = row_ref  # Nueva referencia a la fila
        self.form_fields = FieldFactory(
            obj=self.obj, 
            layout_mode=layout_mode, 
            display_mode=display_mode, 
            get_children=get_children,
            conditions=self.conditions, 
            page=self.page, 
            get_parent=get_parent,
            table_ref=table_ref,  # Pasar la referencia a la tabla
            row_ref=row_ref,  # Pasar la referencia a la fila
            *args, **kwargs
        )
        self.controls = [self.form_fields]
        
    def create_button(self, *args, **kwargs):
        self.form_buttons.create_button(*args, **kwargs)
    
    def check_is_dirty(self, recheck=False):
        return self.form_fields.check_is_dirty(recheck=recheck)
    
    def check_is_new(self):
        return self.obj._state.adding
    
    def get_field_by_name(self, field_name):
        for field in self.form_fields.get_fields():
            if field.name == field_name:
                return field.get_field()
        return None
            
    def set_errors(self, errors = []):
        is_horizontal = self.form_fields.check_is_horizontal()
        for manager in self.form_fields.get_fields():
            field = manager.get_field()
            if is_horizontal:
                field.helper_text = None
                if errors and field.name in errors.message_dict:
                    field.border = ft.InputBorder.UNDERLINE
                    field.border_color = "red"
                    field.hint_text = ' - '.join(errors.message_dict[field.name])
                    field.hint_style = ft.TextStyle(color="red", size=9)
                else:
                    field.border_color = None
                    field.hint_text = None
                    field.border = ft.InputBorder.NONE
            else:
                if errors and field.name in errors.message_dict:
                    field.helper_text = ' - '.join(errors.message_dict[field.name])
                    field.helper_style = ft.TextStyle(color="red")
                    field.border_color = "red"
                
                else:
                    field.helper_text = None
                    field.border_color = None
            field.update()
            
    def full_clean(self):
        try:
            self.obj.full_clean()
            self.set_errors()
            return True
        except ValidationError as ex:
            self.set_errors(ex)
            return False
            
    def save(self, parent_obj=None, parent_field_name=None):
        if parent_obj and parent_field_name and self.obj._state.adding:
            setattr(self.obj, parent_field_name, parent_obj)
        if self.obj._state.adding or self.form_fields.check_is_dirty():
            try:
                self.obj.full_clean()
                self.obj.save()
                self.form_fields.set_original_obj(self.obj)
                return True
            except ValidationError as ex:
                self.set_errors(ex)
                return False
        return True
    
    # limpia formulario
    def clean(self):
        self.page.clean()  # Elimina todos los controles de la página
        # Luego vuelve a agregar los controles iniciales
        self.page.add(self)
        self.page.update()
