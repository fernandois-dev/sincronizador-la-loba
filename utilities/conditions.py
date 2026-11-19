class Conditions:
    def __init__(self, fields=None, fields_excluded=None, fields_readonly=None, overrides_input_type=None, overrides_view_type=None, 
                 filter=None, related_objects=None, fields_order=None, fields_expand=None, fields_calculations=None, fields_column_width=None,
                 fields_conditions_display=None, overrides_display_mode=None, fields_descriptions=None, display_mode=None):
        self.fields = fields or []
        self.fields_excluded = fields_excluded or []
        self.fields_readonly = fields_readonly or []
        self.fields_order = fields_order or []
        self.fields_expand = fields_expand or {}
        self.fields_conditions_display = fields_conditions_display or {}
        self.fields_column_width = fields_column_width or {}
        self.overrides_input_type = overrides_input_type or {}
        self.overrides_view_type = overrides_view_type or {}
        self.overrides_display_mode = overrides_display_mode or {}
        self.filter = filter or []
        self.related_objects = related_objects or {}
        self.fields_calculations = fields_calculations or {}
        self.display_mode = display_mode or {}
        self.fields_descriptions = fields_descriptions or {}

    def init_from_dict(self, data):
        self.fields = data.get('fields', [])
        self.fields_excluded = data.get('fields_excluded', [])
        self.fields_readonly = data.get('fields_readonly', [])
        self.fields_order = data.get('fields_order', [])
        self.fields_expand = data.get('fields_expand', {})
        self.fields_column_width = data.get('fields_column_width', {})
        self.overrides_input_type = data.get('overrides_input_type', {})
        self.overrides_view_type = data.get('overrides_view_type', {})
        self.overrides_display_mode = data.get('overrides_display_mode', {})
        self.display_mode = data.get('display_mode', {})
        self.filter = data.get('filter', [])
        self.related_objects = data.get('related_objects', {})
        self.fields_calculations = data.get('fields_calculations', {})
        self.fields_conditions_display = data.get('fields_conditions_display', {})
        self.fields_descriptions = data.get('fields_descriptions', {})
        

    # def to_dict(self):
    #     return {
    #         'fields': self.fields,
    #         'fields_excluded': self.fields_excluded,
    #         'fields_readonly': self.fields_readonly,
    #         'fields_order': self.fields_order,
    #         'fields_expand': self.fields_expand,
    #         'display_mode': self.display_mode,
    #         'filter': self.filter,
    #         'related_objects': self.related_objects
    #     }