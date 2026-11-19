from django.db import models


class CustomCharField(models.CharField):
    description = "CharField"
    is_searchable = False

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "left"
        self.column_width = column_width

class CustomEmailField(models.EmailField):
    description = "EmailField"
    is_searchable = False

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "left"
        self.column_width = column_width
        
class CustomDateTimeField(models.DateTimeField):
    description = "DateTimeField"
    is_searchable = False

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "right"
        self.column_width = column_width
        
class CustomAutoField(models.AutoField):
    description = "AutoField"

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.aligment = "right"
        self.column_width = column_width

class CustomIntegerField(models.IntegerField):
    description = "IntegerField"

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        # if 'label' in kwargs:
        #     kwargs.pop('label')
            
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "right"
        self.column_width = column_width

class CustomMoneyField(models.IntegerField):
    description = "MoneyField"

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "right"
        self.column_width = column_width

class CustomBooleanField(models.BooleanField):
    description = "BooleanField"

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "center"
        self.column_width = column_width

class CustomForeignKey(models.ForeignKey):
    description = "ForeignKey"

    def __init__(self, *args, hidden=False, is_sortable = False, read_only = False, column_width = None, **kwargs):
        self.hidden = hidden
        self.is_sortable = is_sortable
        self.aligment = "left"
        self.read_only = read_only
        self.column_width = column_width

        super().__init__(*args, **kwargs)

class CustomDateField(models.DateField):
    description = "DateField"
    is_searchable = False

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "right"
        self.column_width = column_width

class CustomDecimalField(models.DecimalField):
    description = "DecimalField"

    def __init__(self, hidden=False, is_searchable = False, is_sortable = False, read_only = False, column_width = None, *args, **kwargs):
        # Establecer valores por defecto para max_digits y decimal_places si no se proporcionan
        if 'max_digits' not in kwargs:
            kwargs['max_digits'] = 10
        if 'decimal_places' not in kwargs:
            kwargs['decimal_places'] = 2
            
        super().__init__(*args, **kwargs)
        
        self.hidden = hidden
        self.is_searchable = is_searchable
        self.is_sortable = is_sortable
        self.read_only = read_only
        self.aligment = "right"
        self.column_width = column_width