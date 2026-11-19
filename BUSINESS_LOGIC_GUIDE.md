# Guía de Uso - Módulo de Lógica de Negocio

## Introducción

El módulo `business_logic.py` centraliza la lógica de negocio común para operaciones repetitivas en el sistema de gestión La Loba. Esto mejora la mantenibilidad, reutilización y consistencia del código.

## Clases Disponibles

### `TablaBaseManager`
Maneja operaciones relacionadas con la carga y gestión de la tabla base desde Google Sheets.

### `OdooSyncManager`
Maneja operaciones de sincronización con Odoo.

## Ejemplos de Uso

### Migración de una página existente

#### Antes (código duplicado):
```python
def carga_tabla_base(self, hojas_seleccionadas):
    # Mostrar loading
    self.loading.show("Cargando datos de Google Sheets...")
    
    try:
        with transaction.atomic():
            self.gestiona_hojas_seleccionadas(hojas_seleccionadas)
            data = [x for hoja in hojas_seleccionadas for x in GoogleService.get_data(hoja)]
            if not data:
                self.page._open(ft.SnackBar(ft.Text("No se encontraron datos...")))
                self.loading.hide()
                return
            
            DataManage.set_data_tabla_base(data)
            DataManage.compare_data_with_odoo()

        self.update_filtered_view()
        self.loading.hide()
        self.page._open(ft.SnackBar(ft.Text("Datos cargados y tabla actualizada.")))

    except Exception as e:
        self.loading.hide()
        self.page._open(ft.SnackBar(ft.Text(f"Error: {str(e)}", bgcolor=ft.Colors.ERROR)))
```

#### Después (usando business_logic):
```python
# 1. Importar el manager
from modules.servidor.business_logic import TablaBaseManager

# 2. Usar el método centralizado
def carga_tabla_base(self, hojas_seleccionadas):
    """Carga la tabla base usando el manager de lógica de negocio"""
    return TablaBaseManager.cargar_tabla_base(
        hojas_seleccionadas=hojas_seleccionadas,
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )
```

### Pasos para migrar una página

1. **Importar los managers:**
```python
from modules.servidor.business_logic import TablaBaseManager, OdooSyncManager
```

2. **Reemplazar método `carga_tabla_base`:**
```python
def carga_tabla_base(self, hojas_seleccionadas):
    return TablaBaseManager.cargar_tabla_base(
        hojas_seleccionadas=hojas_seleccionadas,
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )
```

3. **Reemplazar método `limpiar_tablas`:**
```python
def limpiar_tablas(self):
    return TablaBaseManager.limpiar_tablas(
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )
```

4. **Reemplazar método `carga_odoo`:**
```python
def carga_odoo(self):
    return OdooSyncManager.cargar_datos_odoo_completo(
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )
```

5. **Para métodos específicos de Odoo:**
```python
# Solo productos
def _ejecutar_carga_odoo_products(self):
    return OdooSyncManager.cargar_productos_odoo(
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )

# Solo rutas de abastecimiento
def _ejecutar_carga_odoo_abastecimiento(self):
    return OdooSyncManager.cargar_rutas_odoo(
        loading_widget=self.loading,
        page=self.page,
        update_view_callback=self.update_filtered_view
    )
```

6. **Eliminar métodos duplicados:**
   - `gestiona_hojas_seleccionadas` (ahora privado en TablaBaseManager)
   - Código duplicado de carga y manejo de errores

## Ventajas de la migración

1. **Código DRY (Don't Repeat Yourself):** Elimina duplicación
2. **Mantenimiento centralizado:** Un solo lugar para corregir bugs
3. **Consistencia:** Mismos mensajes y comportamiento en todas las páginas
4. **Testeable:** Lógica separada de la UI
5. **Extensible:** Fácil agregar nuevas funcionalidades

## Páginas que necesitan migración

- `sincroniza_barcode_page.py` ✅ Pendiente
- `sincroniza_stock_page.py` ✅ Pendiente  
- `sincroniza_nuevos_productos_page.py` ✅ Pendiente
- `sincroniza_activo_page.py` ✅ Pendiente
- `impresion_barcode_page.py` ✅ Pendiente
- `sincroniza_abastecimiento_page.py` ✅ Migrado
- `sincroniza_precio_page.py` ✅ Migrado

## Notas importantes

- Los métodos del manager retornan `True`/`False` para indicar éxito/fallo
- El callback `update_view_callback` es opcional
- Los managers manejan automáticamente loading, errores y mensajes
- Compatible con la estructura actual de páginas
