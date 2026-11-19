import gspread
from gspread.utils import ValueRenderOption, rowcol_to_a1
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from logger_config import get_logger

logger = get_logger(__name__)

scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]

# Las credenciales se cargan la primera vez que se usan (no al importar), así la
# app puede abrir y mostrar la pantalla de configuración si falta credentials.json.
_conexion: dict = {}


def _credenciales():
    if "creds" not in _conexion:
        from modules.mercadolibre.rutas import raiz
        _conexion["creds"] = Credentials.from_service_account_file(
            str(raiz() / "credentials.json"), scopes=scopes)
    return _conexion["creds"]


def _cliente():
    if "client" not in _conexion:
        _conexion["client"] = gspread.authorize(_credenciales())
    return _conexion["client"]


def _drive():
    if "drive" not in _conexion:
        _conexion["drive"] = build('drive', 'v3', credentials=_credenciales())
    return _conexion["drive"]


def __getattr__(nombre):
    """Compatibilidad: google_sheet.creds / client / drive_service siguen existiendo."""
    accesos = {"creds": _credenciales, "client": _cliente, "drive_service": _drive}
    if nombre in accesos:
        return accesos[nombre]()
    raise AttributeError(nombre)

# IDs de planillas y carpetas: en server_settings.cfg, sección [GOOGLE]
# (ver apps/servidor/server_settings.example.cfg). No van en el código.
_CLAVES_GOOGLE = {
    "workbook":                   "principal",
    "workbook_gestor":            "gestor",
    "workbook_propuesta_compras": "propuesta_compras",
    "workbook_table_base":        "tabla_base",
    "workbook_correlativos":      "correlativos",
    "workbook_conteo":            "conteo",
}


def _config_google(seccion: str = "GOOGLE") -> dict:
    """Lee una sección de server_settings.cfg (se relee siempre: puede cambiar
    después de la pantalla de primera configuración)."""
    import configparser
    from utilities import carpeta_datos
    cfg = configparser.ConfigParser()
    carpeta_datos.leer_ini(cfg, str(carpeta_datos.ruta("server_settings.cfg")))
    return dict(cfg[seccion]) if cfg.has_section(seccion) else {}


def _id_google(clave: str) -> str:
    valor = _config_google().get(clave, "").strip()
    if not valor:
        raise RuntimeError(
            f"Falta '{clave}' en la sección [GOOGLE] de server_settings.cfg "
            "(ver server_settings.example.cfg).")
    return valor


def empresa() -> dict:
    """Datos de la empresa para documentos (orden de compra): sección [EMPRESA]."""
    datos = _config_google("EMPRESA")
    return {
        "nombre": datos.get("nombre", ""),
        "ciudad": datos.get("ciudad", ""),
        "correo": datos.get("correo", ""),
    }


# ── Caché de workbooks ─────────────────────────────────────────────────────────
# Los workbooks se abren la primera vez que se necesitan (lazy).
# Si la API responde con error en el import, la app arranca igual y reintenta
# al usar el servicio por primera vez.
_wb_cache: dict = {}

# Nombre interno → clave en [GOOGLE]
_SHEETS = _CLAVES_GOOGLE


def _get_workbook(name: str):
    """Devuelve el workbook cacheado; lo abre si aún no se conectó o si falló antes."""
    if _wb_cache.get(name) is not None:
        return _wb_cache[name]

    sid = _id_google(_SHEETS[name])
    try:
        logger.debug("Abriendo Google Sheet '%s' (id=%s)", name, sid)
        wb = _cliente().open_by_key(sid)
        _wb_cache[name] = wb
        logger.info("Google Sheet '%s' conectado correctamente.", name)
        return wb
    except Exception:
        logger.error(
            "Error al abrir Google Sheet '%s' (id=%s). "
            "Verifica que el Sheet exista, que las credenciales tengan acceso "
            "y que la API de Google no tenga incidencias.",
            name, sid,
            exc_info=True,
        )
        raise


# Conectar en el momento de la importación, pero sin bloquear el arranque.
# Cada workbook falla de forma independiente; si uno tiene error 500, los demás
# siguen funcionando.
# Si todavía no está credentials.json (programa recién instalado) no se intenta:
# la app muestra la pantalla de primera configuración.
def _hay_credenciales() -> bool:
    from modules.mercadolibre.rutas import raiz
    return (raiz() / "credentials.json").exists()


for _name in (_SHEETS if _hay_credenciales() and _config_google() else ()):
    try:
        _get_workbook(_name)
    except Exception:
        pass  # El error ya quedó logueado; la app puede iniciar igual.



class GoogleService():
    # botiene el listado de hojas del libro de trabajo
    @staticmethod
    def get_hojas():
        sheets = _get_workbook("workbook_table_base").worksheets()

        sheet_names = [ws.title for ws in sheets]
        return sheet_names
    
    # obtiene la data de una hoja especifica
    @staticmethod
    def get_data(worksheet_name):
        sheet = _get_workbook("workbook_table_base").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A3:AK", value_render_option=ValueRenderOption.unformatted) if any(row)]
        if len(range_data) == 0:
            return []
        headers = range_data[:1][0]
        rows = range_data[1:len(range_data)]
        dict_list = [{header: row[i] if i < len(row) else "" for i, header in enumerate(headers)} for row in rows]
        return dict_list

    # ── Búsqueda / edición de filas de producto en la tabla base ───────────────
    # Layout de cada pestaña: B1 = id proveedor Odoo, C1 = nombre, fila 3 =
    # encabezados (cambian de orden según la pestaña), fila 4+ = productos.
    FILA_ENCABEZADOS_TB = 3

    @staticmethod
    def _normaliza_codigo(valor):
        return str(valor if valor is not None else "").strip().upper()

    @staticmethod
    def buscar_filas_producto(barcodes=(), refs=(), hojas=None):
        """
        Busca en las pestañas de la tabla base (todas, o solo `hojas`) las filas
        cuyo CODIGO BARRAS esté en `barcodes` o cuya REF INTERNA esté en `refs`.
        Lee todo en una sola llamada a la API, en modo FORMULA para poder
        detectar celdas calculadas que no se deben sobreescribir.

        Returns:
            list[dict]: {hoja, fila, proveedor_id, ref, producto, barcode,
                         precio, min, max, columnas: {encabezado: col 1-based},
                         formulas: {encabezados con fórmula}}
        """
        barcodes = {GoogleService._normaliza_codigo(b) for b in barcodes if b}
        refs = {GoogleService._normaliza_codigo(r) for r in refs if r}
        wb = _get_workbook("workbook_table_base")
        if hojas is None:
            hojas = [ws.title for ws in wb.worksheets()]
        hojas = list(hojas)
        if not hojas:
            return []

        rangos = [f"'{h}'!A1:AK" for h in hojas]
        value_ranges = wb.values_batch_get(rangos, params={"valueRenderOption": "FORMULA"}).get("valueRanges", [])

        encontrados = []
        idx_encabezados = GoogleService.FILA_ENCABEZADOS_TB - 1
        for hoja, vr in zip(hojas, value_ranges):
            filas = vr.get("values", [])
            if len(filas) <= idx_encabezados:
                continue
            columnas = {}
            for i, encabezado in enumerate(filas[idx_encabezados]):
                nombre = str(encabezado).strip().upper()
                if nombre and nombre not in columnas:
                    columnas[nombre] = i
            if "PRODUCTO" not in columnas:
                continue
            proveedor_id = filas[0][1] if len(filas[0]) > 1 else None

            def celda(row, nombre):
                i = columnas.get(nombre)
                return row[i] if i is not None and i < len(row) else ""

            for n_fila, row in enumerate(filas[idx_encabezados + 1:], start=idx_encabezados + 2):
                barcode = GoogleService._normaliza_codigo(celda(row, "CODIGO BARRAS"))
                ref = GoogleService._normaliza_codigo(celda(row, "REF INTERNA"))
                if not ((barcode and barcode in barcodes) or (ref and ref in refs)):
                    continue
                encontrados.append({
                    "hoja": hoja,
                    "fila": n_fila,
                    "proveedor_id": proveedor_id,
                    "ref": ref,
                    "producto": str(celda(row, "PRODUCTO")).strip(),
                    "barcode": barcode,
                    "precio": celda(row, "VENTA FLB"),
                    "min": celda(row, "MIN"),
                    "max": celda(row, "MAX"),
                    "columnas": {nombre: i + 1 for nombre, i in columnas.items()},
                    "formulas": {nombre for nombre, i in columnas.items()
                                 if i < len(row) and isinstance(row[i], str) and row[i].startswith("=")},
                })
        return encontrados

    @staticmethod
    def get_hojas_por_proveedor():
        """
        {id proveedor Odoo: [pestañas]} según el B1 de cada pestaña de la tabla
        base. Una sola llamada a la API para todas las pestañas.
        """
        wb = _get_workbook("workbook_table_base")
        hojas = [ws.title for ws in wb.worksheets()]
        value_ranges = wb.values_batch_get([f"'{h}'!B1" for h in hojas]).get("valueRanges", [])
        resultado = {}
        for hoja, vr in zip(hojas, value_ranges):
            valor = (vr.get("values") or [[None]])[0]
            try:
                proveedor_id = int(float(valor[0]))
            except (TypeError, ValueError, IndexError):
                continue
            resultado.setdefault(proveedor_id, []).append(hoja)
        return resultado

    @staticmethod
    def actualizar_celdas_tabla_base(cambios):
        """
        Escribe en lote celdas de la tabla base.

        Args:
            cambios (list[tuple]): (hoja, fila, columna 1-based, valor)
        """
        if not cambios:
            return
        data = [
            {"range": f"'{hoja}'!{rowcol_to_a1(fila, columna)}", "values": [[valor]]}
            for hoja, fila, columna, valor in cambios
        ]
        _get_workbook("workbook_table_base").values_batch_update(
            {"valueInputOption": "RAW", "data": data}
        )

    @staticmethod
    def get_proveedor(worksheet_name):
        sheet = _get_workbook("workbook_table_base").worksheet(worksheet_name)
        proveedor = sheet.get('B1:C1')[0]
        return {"id": proveedor[0], "nombre": proveedor[1]} if proveedor else {"id": None, "nombre": None}

    # ── Hojas de conteo por proveedor (app "ferreteria-conteo-app") ────────────
    @staticmethod
    def get_hojas_conteo():
        """Retorna el listado de pestañas (una por proveedor) del workbook de conteo."""
        sheets = _get_workbook("workbook_conteo").worksheets()
        return [ws.title for ws in sheets]

    @staticmethod
    def get_ultimo_conteo(worksheet_name):
        """
        Lee la pestaña de conteo de un proveedor y retorna los productos con
        registro en la sesión de conteo más reciente (la columna "Conteo" más
        a la derecha), incluyendo los que se contaron con valor 0.

        Layout de la hoja (agregado por la app de conteo):
          fila 1: fecha de cada sesión (vacía en columnas A y B)
          fila 2: encabezados -> "REF INTERNA", "PRODUCTO", "Conteo"/"Stock", "Odoo"...
          fila 3+: datos. "-" indica que el producto no fue contado en esa sesión.

        La columna con el conteo físico se etiqueta "Conteo" o "Stock" según
        la sesión (la app de conteo no usa siempre la misma etiqueta).
        """
        ETIQUETAS_CONTEO = {"conteo", "stock"}

        sheet = _get_workbook("workbook_conteo").worksheet(worksheet_name)
        range_data = sheet.get("A1:AX", value_render_option=ValueRenderOption.unformatted)
        if len(range_data) < 3:
            return []

        fila_labels = range_data[1]
        filas_datos = [row for row in range_data[2:] if any(row)]

        col_conteo = None
        for i in range(len(fila_labels) - 1, -1, -1):
            if str(fila_labels[i]).strip().lower() in ETIQUETAS_CONTEO:
                col_conteo = i
                break
        if col_conteo is None:
            return []

        resultados = []
        for row in filas_datos:
            ref_interna = str(row[0]).strip() if len(row) > 0 else ""
            producto = str(row[1]).strip() if len(row) > 1 else ""
            valor = str(row[col_conteo]).strip() if len(row) > col_conteo else ""
            if not ref_interna or valor in ("", "-"):
                continue
            try:
                stock = float(valor)
            except ValueError:
                continue
            resultados.append({"ref_interna": ref_interna, "producto": producto, "stock": stock})
        return resultados

    # @staticmethod
    # def leer_handler(worksheets: list):
    #     global products
    #     # Google Sheets API setup
    #     SCOPES = ['https://www.googleapis.com/auth/spreadsheets.readonly']
    #     SERVICE_ACCOUNT_FILE = 'credentials.json'
    #     creds = ServiceAccountCredentials.from_json_keyfile_name(SERVICE_ACCOUNT_FILE, SCOPES)
    #     client = gspread.authorize(creds)

    #     # The ID and range of the spreadsheet
    #     SPREADSHEET_ID = '...'
    #     sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    #     # Read data from the first two columns
    #     values = sheet.get_all_values()


    @staticmethod
    def set_tarifas(data):
        worksheet_name = "Tarifas"
        sheet = _get_workbook("workbook").worksheet(worksheet_name)
        sheet.clear()
        sheet.update("A1", data)
        return [{"state":"S", "msg":"Tarifas cargadas correctamente"}]
        
    @staticmethod
    def set_productos(data):
        worksheet_name = "Productos"
        sheet = _get_workbook("workbook").worksheet(worksheet_name)
        sheet.clear()
        sheet.update("A1", data)
        return [{"state":"S", "msg":"Productos cargados correctamente"}]
        
    @staticmethod
    def set_rutas(data):
        worksheet_name = "Rutas"
        sheet = _get_workbook("workbook").worksheet(worksheet_name)
        sheet.clear()
        sheet.update("A1", data)
        return [{"state":"S", "msg":"Rutas de Abastecimiento cargados correctamente"}]
        
    @staticmethod
    def set_proveedores(data):
        worksheet_name = "Proveedores"
        sheet = _get_workbook("workbook").worksheet(worksheet_name)
        sheet.clear()
        sheet.update("A1", data)
        return [{"state":"S", "msg":"Proveedores cargados correctamente"}]
        
    @staticmethod
    def get_productos():
        worksheet_name = "Actualiza Productos"
        sheet = _get_workbook("workbook_gestor").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A9:Z") if any(row)]
        return range_data

    # @staticmethod
    # def cleanup_drive_quota(folder_id):
    #     """Limpia TODO lo que pertenezca a la cuenta de servicio para liberar espacio real."""
    #     try:
    #         print("Iniciando limpieza profunda de cuota...")
    #         # 1. Vaciar papelera inmediatamente
    #         drive_service.files().emptyTrash().execute()
            
    #         # 2. Buscar TODOS los archivos que posee la cuenta de servicio, no solo en una carpeta
    #         # Esto ayudará si hay archivos "huérfanos" o en otras carpetas consumiendo cuota.
    #         results = drive_service.files().list(
    #             pageSize=50, 
    #             fields="files(id, name)",
    #             q="mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false",
    #             orderBy="modifiedTime" # Los más antiguos primero
    #         ).execute()
            
    #         files = results.get('files', [])
    #         # Borrar los 20 más antiguos de golpe para asegurar espacio
    #         for f in files[:20]:
    #             try:
    #                 drive_service.files().delete(fileId=f['id']).execute()
    #                 print(f"Eliminado permanentemente por cuota: {f['name']}")
    #             except: continue
            
    #         # 3. Vaciar papelera de nuevo
    #         drive_service.files().emptyTrash().execute()
    #         print("Limpieza finalizada.")
    #     except Exception as e:
    #         print(f"Error crítico en limpieza global: {e}")

    # @staticmethod
    # def cleanup_old_sheets(workbook, days=3): # Reducido a 3 días
    #     """Elimina hojas antiguas para liberar espacio de cuota."""
    #     from datetime import datetime, timedelta
    #     try:
    #         worksheets = workbook.worksheets()
    #         cutoff_date = datetime.now() - timedelta(days=days)
            
    #         for ws in worksheets:
    #             if ws.title.startswith("C-"):
    #                 try:
    #                     # Extraer fecha del título C-dd-mm-yy ...
    #                     date_str = ws.title.split(" ")[0].replace("C-", "")
    #                     ws_date = datetime.strptime(date_str, "%d-%m-%y")
    #                     if ws_date < cutoff_date:
    #                         workbook.del_worksheet(ws)
    #                 except Exception:
    #                     continue
    #     except Exception as e:
    #         print(f"Error limpiando hojas: {e}")

    @staticmethod
    def get_provider_workbook(provider_name):
        """Busca o crea el archivo. Si falla por cuota, devuelve el error para pedir ayuda al usuario."""
        folder_id = _id_google("carpeta_proveedores")
        
        def try_get_or_create():
            safe_name = provider_name.replace("'", "\\'")
            query = f"name = '{safe_name}' and '{folder_id}' in parents and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed = false"
            results = _drive().files().list(
                q=query, 
                fields="files(id, name)",
                supportsAllDrives=True,
                includeItemsFromAllDrives=True
            ).execute()
            files = results.get('files', [])
            
            if files:
                return _cliente().open_by_key(files[0]['id'])
            
            file_metadata = {
                'name': provider_name,
                'mimeType': 'application/vnd.google-apps.spreadsheet',
                'parents': [folder_id]
            }
            file = _drive().files().create(
                body=file_metadata, 
                fields='id',
                supportsAllDrives=True
            ).execute()
            return _cliente().open_by_key(file.get('id'))

        try:
            return try_get_or_create(), None
        except Exception as e:
            error_msg = str(e).lower()
            if "quota" in error_msg or "403" in error_msg:
                # Intentar limpiar basura una vez de forma silenciosa
                try: _drive().files().emptyTrash().execute()
                except: pass
                return None, "CUOTA_EXCEDIDA"
            return None, str(e)

    @staticmethod
    def get_next_correlative():
        """
        Obtiene el siguiente número correlativo único global de la hoja de control.
        """
        try:
            sheet = _get_workbook("workbook_correlativos").get_worksheet(0)
            data = sheet.get_all_values()
            
            # Si la hoja está vacía o no tiene el encabezado esperado, inicializar
            if not data or data[0][0] != "KEY":
                sheet.clear()
                sheet.append_row(["KEY", "VALOR"])
                sheet.append_row(["CORRELATIVO_GLOBAL", 1])
                return 1
                
            found_row = -1
            next_num = 1
            
            for i, row in enumerate(data):
                if len(row) > 0 and row[0].strip().upper() == "CORRELATIVO_GLOBAL":
                    found_row = i + 1 # 1-based index
                    try:
                        next_num = int(row[1]) + 1
                    except:
                        next_num = 1
                    break
                    
            if found_row != -1:
                sheet.update_cell(found_row, 2, next_num)
            else:
                sheet.append_row(["CORRELATIVO_GLOBAL", 1])
                next_num = 1
                
            return next_num
        except Exception as e:
            from datetime import datetime
            print(f"Error al obtener correlativo global: {e}")
            return datetime.now().strftime("%H%M%S")

    @staticmethod
    def export_reporte_stock(data_rows):
        """
        Exporta los productos seleccionados a archivos de Google Sheets por proveedor.
        Cada proveedor tiene su propio archivo en la carpeta especificada.
        """
        from datetime import datetime
        try:
            # Agrupar por proveedor
            grupos = {}
            for p in data_rows:
                prov = p.get("proveedor", "Sin Proveedor")
                if prov not in grupos:
                    grupos[prov] = []
                grupos[prov].append(p)
            
            proveedores_procesados = []
            requiere_accion_manual = []

            for proveedor, productos in grupos.items():
                wb, error = GoogleService.get_provider_workbook(proveedor)
                if error == "CUOTA_EXCEDIDA":
                    requiere_accion_manual.append(proveedor)
                    continue
                elif not wb:
                    print(f"No se pudo acceder al archivo del proveedor: {proveedor}. Error: {error}")
                    continue
                
                # Obtener correlativo global y generar nombre de hoja
                correlativo = GoogleService.get_next_correlative()
                # timestamp = datetime.now().strftime("%d-%m-%y %H:%M:%S")
                # Formatear correlativo con ceros a la izquierda (ej: 00015)
                correlativo_str = str(correlativo).zfill(5)
                oc_label = f"{correlativo_str}"
                worksheet_name = f"OC-{correlativo}"

                # Crear nueva hoja en el archivo del proveedor
                sheet = wb.add_worksheet(title=worksheet_name, rows="100", cols="10")
                
                datos_empresa = empresa()
                rows = [
                    [datos_empresa["nombre"].upper(), "", "", "", "", "ORDEN DE COMPRA"],
                    [datos_empresa["ciudad"], "", "", "", "", oc_label],
                    [f"Contacto: {datos_empresa['correo']}", "", "", "", "", ""],
                    [""], # Fila 4 vacía
                    [f"PROVEEDOR: {proveedor}", "", "", "", "FECHA OC:", datetime.now().strftime("%d-%m-%Y")],
                    [""], # Fila 6 vacía
                ]
                
                r = 6 # Contador de filas actualizadas en 'rows'
                
                table_header_rows = []
                provider_total_rows = []

                r += 1
                table_header_rows.append(r)
                rows.append(["#", "Producto", "Cant. Comprar", "Precio Unit. (Neto)", "Subtotal (Neto)", "Observaciones"]) # Encabezados
                
                start_prod_row = r + 1
                line_number = 1
                for p in productos:
                    r += 1
                    producto = p.get("producto", "")
                    stock = float(p.get("stock", 0))
                    stock_max = float(p.get("stock_max", 0))
                    cant_comprar = max(0, stock_max - stock)
                    precio = float(p.get("precio_compra", 0))
                    
                    # Fórmula para subtotal de la línea: Cantidad * Precio
                    formula_subtotal = f"=C{r}*D{r}"
                    
                    rows.append([
                        line_number,
                        producto,
                        cant_comprar,
                        precio,
                        formula_subtotal,
                        "" # Columna de Observaciones vacía
                    ])
                    line_number += 1
                
                end_prod_row = r
                r += 1
                provider_total_rows.append(r)
                # Fórmula para el total del proveedor
                formula_vendor_subtotal = f"=SUM(E{start_prod_row}:E{end_prod_row})"
                rows.append(["", "", "", "TOTAL NETO:", formula_vendor_subtotal, ""])
                
                # 1. ACTUALIZAR DATOS
                sheet.update("A1", rows, value_input_option='USER_ENTERED')
                
                # 2. APLICAR FORMATO
                # Formato numérico estándar (Separador de miles, sin decimales)
                number_format = {
                    "numberFormat": {"type": "NUMBER", "pattern": "#,##0"}
                }
                # Formato para el Total (Signo peso + miles, sin decimales)
                total_money_format = {
                    "numberFormat": {"type": "NUMBER", "pattern": '"$"#,##0'}
                }

                # --- ESTILO ENCABEZADO PROFESIONAL ---
                # Nombre Empresa
                sheet.format("A1:C1", {"textFormat": {"bold": True, "fontSize": 16, "foregroundColor": {"red": 0.1, "green": 0.2, "blue": 0.5}}})
                sheet.merge_cells("A1:C1")
                
                # Cuadro Orden de Compra (Derecha)
                sheet.format("F1:F2", {
                    "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                    "textFormat": {"bold": True, "fontSize": 12},
                    "horizontalAlignment": "CENTER",
                    "borders": {
                        "top": {"style": "SOLID_MEDIUM"},
                        "bottom": {"style": "SOLID_MEDIUM"},
                        "left": {"style": "SOLID_MEDIUM"},
                        "right": {"style": "SOLID_MEDIUM"}
                    }
                })

                # Datos del Proveedor y Fecha
                sheet.format("A5:F5", {"textFormat": {"bold": True}, "backgroundColor": {"red": 0.98, "green": 0.98, "blue": 0.98}})
                # sheet.format("A5:B5", {"horizontalAlignment": "RIGHT"})
                sheet.format("E5", {"horizontalAlignment": "RIGHT"})
                
                # Encabezados de Tabla
                for th_row in table_header_rows:
                    # Aplicar bordes a toda la tabla (incluyendo interior)
                    table_range = f"A{th_row}:F{end_prod_row}"
                    sheet.format(table_range, {
                        "borders": {
                            "top": {"style": "SOLID"},
                            "bottom": {"style": "SOLID"},
                            "left": {"style": "SOLID"},
                            "right": {"style": "SOLID"}
                        }
                    })
                    
                    # Estilo específico para la fila de encabezado
                    sheet.format(f"A{th_row}:F{th_row}", {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        "backgroundColor": {"red": 0.2, "green": 0.2, "blue": 0.2},
                        "horizontalAlignment": "CENTER"
                    })

                # Formato numérico para cantidades y precios (C a E)
                sheet.format(f"C{table_header_rows[0]}:E{r}", number_format)

                # Formato especial SÓLO para las celdas de Total
                for pt_row in provider_total_rows:
                    sheet.format(f"E{pt_row}", total_money_format)
                    sheet.format(f"D{pt_row}:E{pt_row}", {
                        "textFormat": {"bold": True, "fontSize": 12},
                        "backgroundColor": {"red": 0.9, "green": 0.9, "blue": 0.9},
                        "borders": {
                            "top": {"style": "SOLID_MEDIUM"},
                            "bottom": {"style": "SOLID_MEDIUM"}
                        }
                    })
                
                # Formato columna de producto (alineación izquierda)
                sheet.format(f"B{table_header_rows[0]+1}:B{end_prod_row}", {"horizontalAlignment": "LEFT"})

                # Ajustar anchos
                requests = [
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": 0,
                                "endIndex": 1
                            },
                            "properties": {"pixelSize": 40},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": 1,
                                "endIndex": 2
                            },
                            "properties": {"pixelSize": 400},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": 2,
                                "endIndex": 5
                            },
                            "properties": {"pixelSize": 120},
                            "fields": "pixelSize",
                        }
                    },
                    {
                        "updateDimensionProperties": {
                            "range": {
                                "sheetId": sheet.id,
                                "dimension": "COLUMNS",
                                "startIndex": 5,
                                "endIndex": 6
                            },
                            "properties": {"pixelSize": 250},
                            "fields": "pixelSize",
                        }
                    }
                ]
                wb.batch_update({"requests": requests})
                proveedores_procesados.append(proveedor)

            msg = ""
            if proveedores_procesados:
                msg += f"✅ Exportados: {', '.join(proveedores_procesados)}. "
            if requiere_accion_manual:
                msg += f"\n⚠️ CUOTA EXCEDIDA: Por favor crea manualmente un Google Sheet llamado '{', '.join(requiere_accion_manual)}' en la carpeta o comparte uno existente con el bot."
            
            return msg if msg else "No se pudo procesar ningún proveedor por problemas de espacio o permisos."
        except Exception as e:
            print(f"Error al exportar a Google Sheets: {e}")
            return False

    @staticmethod
    def get_inventario():
        worksheet_name = "Ajusta Inventario"
        sheet = _get_workbook("workbook_gestor").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A6:Z") if any(row)]
        sheet.batch_clear(["A6:Z"])
        if len(range_data) == 0:
            return []
        headers = range_data[:1][0]
        rows = range_data[1:len(range_data)]
        dict_list = [{header: row[i] if i < len(row) else "" for i, header in enumerate(headers)} for row in rows]
        return dict_list

    @staticmethod
    def get_tarifas():
        worksheet_name = "Tarifa Prov"
        sheet = _get_workbook("workbook_gestor").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A6:Z") if any(row)]
        sheet.batch_clear(["A6:Z"])
        if len(range_data) == 0:
            return []
        headers = range_data[:1][0]
        rows = range_data[1:len(range_data)]
        dict_list = [{header: row[i] if i < len(row) else "" for i, header in enumerate(headers)} for row in rows]
        return dict_list
    
    @staticmethod
    def get_rutas():
        worksheet_name = "Abastecimiento"
        sheet = _get_workbook("workbook_gestor").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A6:Z") if any(row)]
        sheet.batch_clear(["A6:Z"])
        if len(range_data) == 0:
            return []
        headers = range_data[:1][0]
        rows = range_data[1:len(range_data)]
        dict_list = [{header: row[i] if i < len(row) else "" for i, header in enumerate(headers)} for row in rows]
        return dict_list
    
    @staticmethod
    def limpia_celdas_cant_compra(worksheet_name, productos):
        sheet = _get_workbook("workbook_table_base").worksheet(worksheet_name)
        range_data = [row for row in sheet.get("A3:Z") if any(row)]
        if not range_data:
            return [{"state": "E", "msg": "No hay datos en la hoja"}]

        headers = range_data[0]
        try:
            col_producto = headers.index("PRODUCTO")
            col_cant_comp = headers.index("CANT. COMP")
        except ValueError:
            return [{"state": "E", "msg": "No se encontró alguna de las cabeceras requeridas"}]

        # Limpiar la columna "CANT. COMP" para los productos indicados
        for i, row in enumerate(range_data[1:], start=1):
            if len(row) > col_producto:
                producto = row[col_producto].upper().replace("   "," ").replace("  "," ").lstrip().rstrip()# start=1 para saltar headers
                if len(row) > col_producto and producto in productos:
                    # La columna es col_cant_comp + 1 (porque es 1-based)
                    fila = i + 3  # +2 porque range_data[0] es headers y A3 es fila 3
                    columna = col_cant_comp + 1
                    sheet.update_cell(fila, columna, "OK")

        return [{"state": "S", "msg": "Celdas limpiadas correctamente"}]