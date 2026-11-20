from datetime import datetime, date
import configparser
import os
import socket
import threading
import xmlrpc.client
import re

from logger_config import get_logger
from modules.servidor import registro_stock
from utilities import carpeta_datos

logger = get_logger(__name__)

# Las credenciales de Odoo se leen SOLO de apps/servidor/server_settings.cfg, sección [ODOO]
# (archivo fuera de git; ver apps/servidor/server_settings.example.cfg). No van en el código.
_CLAVES_ODOO = ("url", "db", "username", "password")

# Timeout de socket para las llamadas XML-RPC (segundos). Evita que la UI se
# congele indefinidamente cuando no hay red y una página llama a Odoo desde
# el hilo del evento en vez de un hilo daemon.
_SOCKET_TIMEOUT = 15

# Faults de Odoo cuyo mensaje indica sesión/uid inválido; ante estos se
# reintenta una vez tras invalidar la conexión, en vez de tratarlos como
# errores de negocio.
_SESSION_FAULT_MARKERS = ("session", "access denied", "invalid session")


class OdooConnectionError(Exception):
    """No se pudo establecer o mantener la conexión XML-RPC con Odoo."""


def _load_odoo_config(avisar: bool = True) -> dict:
    """
    Lee la sección [ODOO] de apps/servidor/server_settings.cfg.

    Si falta el archivo, la sección o alguna clave, NO falla al importar (la app
    debe poder abrir sin conexión a Odoo): deja esa clave vacía y el error claro
    aparece en la primera llamada real a Odoo (ver _OdooConnection._ensure_uid).
    """
    config_path = str(carpeta_datos.ruta("server_settings.cfg"))
    parser = configparser.ConfigParser()
    carpeta_datos.leer_ini(parser, config_path)
    cfg = {clave: parser.get("ODOO", clave, fallback="").strip() for clave in _CLAVES_ODOO}
    faltan = [clave for clave, valor in cfg.items() if not valor]
    if faltan and avisar:
        logger.error(
            "Configuración de Odoo incompleta en %s, sección [ODOO]: faltan %s.",
            config_path, ", ".join(faltan),
        )
    return cfg


class _OdooConnection:
    """
    Conexión XML-RPC perezosa con reconexión automática.

    La autenticación ocurre en la primera llamada real, no al importar el
    módulo, para que la app pueda arrancar sin conexión a Odoo.

    xmlrpc.client.ServerProxy no es thread-safe, así que se mantiene un pool
    de proxies: cada llamada toma uno (o crea uno si no hay libres) y lo
    devuelve al terminar. Esto reutiliza las conexiones HTTPS keep-alive
    entre los hilos efímeros de la UI — un ServerProxy nuevo paga ~320 ms de
    handshake TLS por llamada. Un contador de generación descarta los proxies
    creados antes de una reconexión.
    """

    _POOL_MAX = 8

    def __init__(self):
        self._cfg = _load_odoo_config()
        self._lock = threading.RLock()
        self._uid = None
        self._generation = 0
        self._pool = []  # [(proxy, generation)] proxies libres, protegido por _lock

    def _ensure_uid(self) -> int:
        with self._lock:
            if self._uid:
                return self._uid
            # Sin sesión: se relee server_settings.cfg, por si se agregó o cambió después
            # de abrir la app (pantalla de primera configuración o página Configuración).
            self._cfg = _load_odoo_config(avisar=False)
            faltan = [clave for clave in _CLAVES_ODOO if not self._cfg.get(clave)]
            if faltan:
                raise OdooConnectionError(
                    f"Falta configurar Odoo en {carpeta_datos.ruta('server_settings.cfg')}, sección [ODOO]: "
                    f"{', '.join(faltan)}. Usa apps/servidor/server_settings.example.cfg como guía."
                )
            try:
                common = xmlrpc.client.ServerProxy(
                    f"{self._cfg['url']}/xmlrpc/2/common",
                    transport=_TimeoutTransport(_SOCKET_TIMEOUT),
                )
                uid = common.authenticate(self._cfg["db"], self._cfg["username"], self._cfg["password"], {})
            except (OSError, socket.timeout) as exc:
                raise OdooConnectionError(f"Error de red al conectar con Odoo: {exc}") from exc
            except xmlrpc.client.Fault as exc:
                raise OdooConnectionError(f"Fault XML-RPC durante autenticación: {exc.faultString}") from exc

            if not uid:
                raise OdooConnectionError("Autenticación Odoo devolvió uid=False. Verifica usuario/contraseña.")

            self._uid = uid
            self._generation += 1
            logger.info("Conexión Odoo establecida. uid=%s", uid)
            return uid

    def _acquire_proxy(self) -> xmlrpc.client.ServerProxy:
        with self._lock:
            while self._pool:
                proxy, generation = self._pool.pop()
                if generation == self._generation:
                    return proxy
        return xmlrpc.client.ServerProxy(
            f"{self._cfg['url']}/xmlrpc/2/object",
            transport=_TimeoutTransport(_SOCKET_TIMEOUT),
        )

    def _release_proxy(self, proxy: xmlrpc.client.ServerProxy):
        with self._lock:
            if len(self._pool) < self._POOL_MAX:
                self._pool.append((proxy, self._generation))

    def invalidate(self):
        with self._lock:
            self._uid = None
            self._generation += 1
            self._pool.clear()

    def is_connected(self) -> bool:
        return self._uid is not None

    def ping(self) -> bool:
        try:
            self._ensure_uid()
            return True
        except OdooConnectionError:
            return False

    def execute_kw(self, _db, _uid, _password, model, method, *args, **kwargs):
        # _db/_uid/_password se ignoran: se mantienen como parámetros solo
        # por compatibilidad sintáctica con las llamadas existentes en este
        # módulo, que siguen escribiendo models.execute_kw(db, uid, password, ...).
        uid = self._ensure_uid()
        retried = False
        while True:
            proxy = self._acquire_proxy()
            try:
                resultado = proxy.execute_kw(
                    self._cfg["db"], uid, self._cfg["password"], model, method, *args, **kwargs
                )
                self._release_proxy(proxy)
                return resultado
            except (OSError, socket.timeout) as exc:
                # proxy con conexión rota: no vuelve al pool
                self.invalidate()
                raise OdooConnectionError(f"Sin conexión con Odoo: {exc}") from exc
            except xmlrpc.client.Fault as exc:
                mensaje = (exc.faultString or "").lower()
                if not retried and any(marker in mensaje for marker in _SESSION_FAULT_MARKERS):
                    retried = True
                    self.invalidate()
                    uid = self._ensure_uid()
                    continue
                # Fault de negocio: la conexión sigue sana, el proxy se reutiliza
                self._release_proxy(proxy)
                raise


class _TimeoutTransport(xmlrpc.client.SafeTransport):
    """SafeTransport (HTTPS) con timeout de socket configurable."""

    def __init__(self, timeout, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._timeout = timeout

    def make_connection(self, host):
        conn = super().make_connection(host)
        conn.timeout = self._timeout
        return conn


_connection = _OdooConnection()

# ── Compatibilidad hacia atrás ──────────────────────────────────────────────
# Las ~96 llamadas internas de este módulo usan el patrón
# models.execute_kw(db, uid, password, "modelo", "método", ...). `models` es
# ahora el objeto de conexión perezosa; `db`/`uid`/`password` se conservan
# como nombres pero su valor real es ignorado por _OdooConnection.execute_kw.
models = _connection
db = _connection._cfg["db"]
uid = None
password = None


def normalize_barcode(barcode):
    """
    Normaliza un código de barras eliminando caracteres problemáticos
    y aplicando validaciones básicas
    """
    if not barcode:
        return None
    
    # Convertir a string y eliminar espacios
    barcode = str(barcode).strip()
    
    # Eliminar caracteres no alfanuméricos comunes que pueden introducir los escáneres
    # barcode = re.sub(r'[^\w\-]', '', barcode)
    
    # Eliminar caracteres de control y caracteres especiales problemáticos
    barcode = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', barcode)
    
    # Convertir a mayúsculas para consistencia
    barcode = barcode.upper()
    
    # Validar longitud mínima (evitar códigos muy cortos que pueden ser errores)
    if len(barcode) < 3:
        return None
    
    # Validar longitud máxima (códigos de barras típicos no superan 30 caracteres)
    if len(barcode) > 30:
        barcode = barcode[:30]
    
    return barcode if barcode else None


def _accion_sin_respuesta(modelo, metodo, ids):
    """Ejecuta un botón de Odoo que no devuelve nada (button_cancel, button_lock, unlink...).

    En Odoo 19 esos métodos devuelven None y XML-RPC responde con el error
    "cannot marshal None": la acción SÍ se ejecutó. Ese error se ignora; cualquier
    otro se propaga.
    """
    try:
        return models.execute_kw(db, uid, password, modelo, metodo, [ids])
    except Exception as e:
        if "cannot marshal None" in str(e):
            return None
        raise

class OdooService:
    @staticmethod
    def is_connected() -> bool:
        """Estado cacheado (sin red): True si ya hay una sesión autenticada."""
        return _connection.is_connected()

    @staticmethod
    def ping() -> bool:
        """Verifica activamente la conexión (hace red). Nunca lanza excepción."""
        return _connection.ping()

    @staticmethod
    def reconnect() -> bool:
        """Fuerza una reautenticación y devuelve si tuvo éxito."""
        _connection.invalidate()
        return _connection.ping()

    @staticmethod
    def get_config_param(key: str) -> str | None:
        try:
            ids = models.execute_kw(db, uid, password, "ir.config_parameter", "search",
                                    [[["key", "=", key]]])
            if not ids:
                return None
            records = models.execute_kw(db, uid, password, "ir.config_parameter", "read",
                                        [ids], {"fields": ["value"]})
            return records[0]["value"] if records else None
        except Exception as exc:
            logger.error("Error leyendo ir.config_parameter '%s': %s", key, exc)
            return None

    @staticmethod
    def set_config_param(key: str, value: str) -> bool:
        try:
            ids = models.execute_kw(db, uid, password, "ir.config_parameter", "search",
                                    [[["key", "=", key]]])
            if ids:
                models.execute_kw(db, uid, password, "ir.config_parameter", "write",
                                  [ids, {"value": value}])
            else:
                models.execute_kw(db, uid, password, "ir.config_parameter", "create",
                                  [{"key": key, "value": value}])
            return True
        except Exception as exc:
            logger.error("Error escribiendo ir.config_parameter '%s': %s", key, exc)
            return False

    @staticmethod
    def listar_ordenes_compra(proveedor_id=None, fecha_inicio=None, fecha_fin=None):
        # Excluir canceladas y bloqueadas. En Odoo 19 ya no existe el estado "done":
        # "Devolver y bloquear" deja la OC en "purchase" con locked=True.
        domain = [["state", "not in", ["cancel", "done"]], ["locked", "=", False]]
        if proveedor_id:
            domain.append(["partner_id", "=", int(proveedor_id)])
        if fecha_inicio:
            if isinstance(fecha_inicio, datetime):
                fecha_inicio = fecha_inicio.strftime("%Y-%m-%d")
            domain.append(["date_order", ">=", fecha_inicio])
        if fecha_fin:
            if isinstance(fecha_fin, datetime):
                fecha_fin = fecha_fin.strftime("%Y-%m-%d")
            domain.append(["date_order", "<=", fecha_fin])
        # Odoo espera el dominio como lista de condiciones con operadores prefijos "&"
        # Formato: [cond1] o ["&", cond1, cond2] o ["&", cond1, "&", cond2, cond3]
        if len(domain) > 1:
            operators = ["&"] * (len(domain) - 1)
            domain = operators + domain
        ordenes = models.execute_kw(db, uid, password, 'purchase.order', 'search_read',
            [domain],
            {"fields": ["id", "name", "partner_id", "date_order", "state", 
                "amount_total",        # Total con impuestos
                "amount_untaxed",      # Total sin impuestos
                "amount_tax"           # Solo impuestos
                        ]}
        )
        return ordenes
    
    @staticmethod
    def get_rutas():
        list_obj = models.execute_kw(db, uid, password,
            "stock.warehouse.orderpoint", "search_read",  # Método para buscar y leer datos
            [[("active", "=", True)]],  # Aquí podrías agregar filtros, pero lo dejamos vacío para obtener todos
            {"fields": ["id","product_id", "product_tmpl_id", "location_id", "product_min_qty", "product_max_qty",]}  # Campos a recuperar y límite de resultados
        )
        return list_obj
    
    @staticmethod
    def get_productos():
        list_obj = models.execute_kw(db, uid, password,
            "product.template", "search_read",  # Método para buscar y leer datos
            [[]],  # Aquí podrías agregar filtros, pero lo dejamos vacío para obtener todos
            {"fields": ["id",
                        "name",
                        "list_price",
                        "qty_available",
                        "virtual_available",
                        "incoming_qty",
                        "outgoing_qty",
                        "barcode",
                        "categ_id",
                        "default_code",
                        "sale_ok",
                        "is_favorite"]}  # Campos a recuperar y límite de resultados
        )
        # Mostrar los productos obtenidos
        return list_obj
    
    @staticmethod
    def get_product_product(product_tmpl_id):
        list_obj = models.execute_kw(
            db, uid, password, 
            'product.product', 
            'search', 
            [[['product_tmpl_id', '=', product_tmpl_id]]])
        # Mostrar los productos obtenidos
        return list_obj
    
    @staticmethod
    def obtener_ultimo_correlativo_odoo():
        """
        Obtiene el último correlativo de códigos de barras que empiecen con 'LL' 
        y tengan al menos 5 dígitos desde Odoo.
        
        Returns:
            str: El último código de barras encontrado o 'LL00000' si no hay ninguno
        """
        try:
            # Consultar productos en Odoo que tengan código de barras que empiece con 'LL'
            # y que tengan al menos 5 caracteres adicionales (LL + 5 = 7 caracteres mínimo)
            productos = models.execute_kw(db, uid, password,
                'product.product', 
                'search_read',
                [[['barcode', '=like', 'LL_____%']]],  # Al menos 5 guiones bajos para asegurar el largo
                {'fields': ['barcode'], 'order': 'barcode desc', 'limit': 100} 
            )
            
            if productos:
                # Filtrar solo los que después de LL tienen solo dígitos y al menos 5 de ellos
                validos = [p['barcode'] for p in productos if p['barcode'] and p['barcode'][2:].isdigit() and len(p['barcode'][2:]) >= 5]
                if validos:
                    # Ordenar numéricamente por si acaso hay mezcla de largos (ej LL10000 y LL9999)
                    validos.sort(key=lambda x: int(x[2:]), reverse=True)
                    return validos[0]
            
            return 'LL00000'  # Valor por defecto con 5 dígitos
                
        except Exception as e:
            print(f"Error al consultar Odoo: {e}")
            return 'LL00000'
    
    @staticmethod
    def get_proveedores():
        list_obj = models.execute_kw(db, uid, password,
            "res.partner", "search_read",  # Método para buscar y leer datos
            [[]],  # Aquí podrías agregar filtros, pero lo dejamos vacío para obtener todos
            {"fields": ["id", "name", "is_company"]}  # Campos a recuperar y límite de resultados
        )
        return list_obj

    @staticmethod
    def get_tarifas():
        list_obj = models.execute_kw(db, uid, password,
            "product.supplierinfo", "search_read",  # Método para buscar y leer datos
            [[]],  # Aquí podrías agregar filtros, pero lo dejamos vacío para obtener todos
            {"fields": ["id","partner_id", 'product_tmpl_id', 'price',"sequence", "product_code"]}  # Campos a recuperar y límite de resultados
        )
        return list_obj

    @staticmethod
    def get_productos_por_barcodes(barcodes):
        """Productos (template) de Odoo cuyo código de barras está en `barcodes`."""
        barcodes = [b for b in {normalize_barcode(b) for b in barcodes} if b]
        if not barcodes:
            return []
        return models.execute_kw(db, uid, password, "product.template", "search_read",
            [[["barcode", "in", barcodes]]],
            {"fields": ["id", "name", "default_code", "barcode", "list_price", "qty_available"]}
        )

    @staticmethod
    def get_ultimas_compras(product_tmpl_ids):
        """
        Fecha de la última orden de compra confirmada de cada producto a cada proveedor.

        Returns:
            dict: {(product_tmpl_id, partner_id): "YYYY-MM-DD HH:MM:SS"}
        """
        ids = [int(i) for i in product_tmpl_ids if i]
        if not ids:
            return {}
        grupos = models.execute_kw(db, uid, password, "purchase.order.line", "read_group",
            [[["product_id.product_tmpl_id", "in", ids], ["state", "in", ["purchase", "done"]]],
             ["date_order:max"], ["product_id", "partner_id"]],
            {"lazy": False}
        )
        variantes = {g["product_id"][0] for g in grupos if g.get("product_id")}
        template_de = {v["id"]: v["product_tmpl_id"][0] for v in models.execute_kw(
            db, uid, password, "product.product", "search_read",
            [[["id", "in", list(variantes)], ["active", "in", [True, False]]]], {"fields": ["product_tmpl_id"]}
        )} if variantes else {}

        resultado = {}
        for g in grupos:
            if not g.get("product_id") or not g.get("partner_id") or not g.get("date_order"):
                continue
            clave = (template_de.get(g["product_id"][0]), g["partner_id"][0])
            if clave[0] and g["date_order"] > resultado.get(clave, ""):
                resultado[clave] = g["date_order"]
        return resultado

    @staticmethod
    def get_productos_por_ids(product_tmpl_ids):
        """Productos (template) de Odoo por id, con los mismos campos que get_productos_por_barcodes."""
        ids = [int(i) for i in product_tmpl_ids if i]
        if not ids:
            return []
        return models.execute_kw(db, uid, password, "product.template", "read",
            [ids], {"fields": ["id", "name", "default_code", "barcode", "list_price", "qty_available"]}
        )

    @staticmethod
    def archivar_producto(product_tmpl_id):
        """
        Archiva un producto duplicado: primero sus reglas de reabastecimiento
        (Odoo no permite archivar un producto con reglas activas) y luego el
        template, liberando su código de barras para el producto que se conserva.
        """
        try:
            orderpoint_ids = models.execute_kw(db, uid, password, "stock.warehouse.orderpoint", "search",
                                               [[["product_tmpl_id", "=", int(product_tmpl_id)]]])
            if orderpoint_ids:
                models.execute_kw(db, uid, password, "stock.warehouse.orderpoint", "write",
                                  [orderpoint_ids, {"active": False}])
            models.execute_kw(db, uid, password, "product.template", "write",
                              [[int(product_tmpl_id)], {"barcode": False, "active": False}])
            return {"state": "S", "msg": f"Producto {product_tmpl_id} archivado."}
        except Exception as e:
            logger.error("Error al archivar producto %s.", product_tmpl_id, exc_info=True)
            return {"state": "E", "msg": f"Error al archivar el producto {product_tmpl_id}: {e}"}

    @staticmethod
    def get_tarifas_por_productos(product_tmpl_ids):
        """Tarifas de proveedor (product.supplierinfo) de los templates indicados."""
        if not product_tmpl_ids:
            return []
        return models.execute_kw(db, uid, password, "product.supplierinfo", "search_read",
            [[["product_tmpl_id", "in", list(product_tmpl_ids)]]],
            {"fields": ["id", "partner_id", "product_tmpl_id", "price", "sequence", "product_code"]}
        )

    @staticmethod
    def get_rutas_por_productos(product_tmpl_ids):
        """Reglas de reabastecimiento (mín/máx) de los templates indicados."""
        if not product_tmpl_ids:
            return []
        return models.execute_kw(db, uid, password, "stock.warehouse.orderpoint", "search_read",
            [[["product_tmpl_id", "in", list(product_tmpl_ids)], ("active", "=", True)]],
            {"fields": ["id", "product_id", "product_tmpl_id", "product_min_qty", "product_max_qty"]}
        )

    @staticmethod
    def get_last_purchase_price(product_tmpl_id):
        """
        Obtiene el último precio de compra de un producto desde Odoo.
        Prioridad:
        1. Última Orden de Compra confirmada (purchase o done).
        2. Ficha de proveedor (product.supplierinfo).
        3. Precio de venta (list_price) como último recurso.
        """
        try:
            # 1. Obtener IDs de variantes y precio de lista base del template
            product_info = models.execute_kw(db, uid, password, 'product.template', 'read', 
                [product_tmpl_id], {'fields': ['list_price']})
            list_price = product_info[0]['list_price'] if product_info else 0

            product_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', product_tmpl_id]]])
            
            # 2. Buscar la última línea de orden de compra confirmada
            if product_ids:
                order_lines = models.execute_kw(db, uid, password, 'purchase.order.line', 'search_read',
                    [[['product_id', 'in', product_ids], ['state', 'in', ['purchase', 'done']]]],
                    {'fields': ['price_unit'], 'order': 'id desc', 'limit': 1}
                )
                
                if order_lines:
                    return order_lines[0]['price_unit']
            
            # 3. Si no hay OC, intentar ficha de proveedor (supplierinfo)
            supplier_info = models.execute_kw(db, uid, password, 'product.supplierinfo', 'search_read',
                [[['product_tmpl_id', '=', product_tmpl_id]]],
                {'fields': ['price'], 'order': 'sequence asc', 'limit': 1}
            )
            if supplier_info:
                return supplier_info[0]['price']
            
            # 4. Fallback: Precio de venta
            return list_price
        except Exception as e:
            print(f"Error al obtener último precio de compra para {product_tmpl_id}: {e}")
            return 0

    @staticmethod
    def get_last_purchase_prices_batch(product_tmpl_ids):
        """
        Obtiene los últimos precios de compra para una lista de productos en ráfaga.
        Prioridad: 1. OC Confirmada, 2. Supplier Info, 3. List Price.
        """
        try:
            if not product_tmpl_ids:
                return {}
            
            # 1. Obtener información base de templates (incluyendo precio de venta)
            templates = models.execute_kw(db, uid, password, 'product.template', 'read',
                [product_tmpl_ids], {'fields': ['id', 'list_price']}
            )
            results = {t['id']: t['list_price'] for t in templates}
            templates_found_in_po = set()
            templates_found_in_supplier = set()
            
            # 2. Obtener mapeo de variants
            variants = models.execute_kw(db, uid, password, 'product.product', 'search_read',
                [[['product_tmpl_id', 'in', product_tmpl_ids]]],
                {'fields': ['id', 'product_tmpl_id']}
            )
            product_to_template = {v['id']: v['product_tmpl_id'][0] for v in variants}
            all_variant_ids = list(product_to_template.keys())
            
            # 3. Buscar líneas de OC
            if all_variant_ids:
                order_lines = models.execute_kw(db, uid, password, 'purchase.order.line', 'search_read',
                    [[['product_id', 'in', all_variant_ids], ['state', 'in', ['purchase', 'done']]]],
                    {'fields': ['product_id', 'price_unit'], 'order': 'id desc', 'limit': 2000}
                )
                
                for line in order_lines:
                    p_id = line['product_id'][0]
                    t_id = product_to_template.get(p_id)
                    if t_id and t_id not in templates_found_in_po:
                        results[t_id] = line['price_unit']
                        templates_found_in_po.add(t_id)
            
            # 4. Para los que no tengan OC, buscar en supplierinfo
            missing_po = [tid for tid in product_tmpl_ids if tid not in templates_found_in_po]
            if missing_po:
                supplier_info = models.execute_kw(db, uid, password, 'product.supplierinfo', 'search_read',
                    [[['product_tmpl_id', 'in', missing_po]]],
                    {'fields': ['product_tmpl_id', 'price'], 'order': 'sequence asc'}
                )
                for info in supplier_info:
                    t_id = info['product_tmpl_id'][0]
                    if t_id not in templates_found_in_po and t_id not in templates_found_in_supplier:
                        results[t_id] = info['price']
                        templates_found_in_supplier.add(t_id)
            
            # Los que no se encontraron en PO ni Supplier Info ya tienen su list_price en results
            return results
        except Exception as e:
            print(f"Error en batch de precios de compra: {e}")
            return {tid: 0 for tid in product_tmpl_ids}

    @staticmethod
    def set_productos(reg):
        mensage = {}
        try:
            product_id =  None
            if "id" in reg:
                product_id =  int(reg["id"])
                del(reg["id"])
            
            # Normalizar código de barras si existe
            if "barcode" in reg and reg["barcode"]:
                original_barcode = reg["barcode"]
                normalized_barcode = normalize_barcode(reg["barcode"])
                
                if not normalized_barcode:
                    mensage = {"state":"W", "msg":f'Código de barras "{original_barcode}" no es válido después de la normalización.'}
                    return mensage
                
                reg["barcode"] = normalized_barcode
                
                # Mostrar información si hubo cambios en la normalización
                if original_barcode != normalized_barcode:
                    print(f"Código normalizado: '{original_barcode}' -> '{normalized_barcode}'")
            
            valid = True
            if not product_id:
                categ_id = models.execute_kw(
                    db, uid, password,
                    'product.category', 'search',
                    [[['complete_name', '=', reg["categ_id"]]]]
                )

                # Comprobar si encontramos la categoría
                if not categ_id:
                    mensage = {"state":"W", "msg":f'Categoría "{reg["categ_id"]}" no encontrada.'}
                    
                
                # validamos que el codigo de barras sea unico
                if "barcode" in reg and reg["barcode"]:
                    existing_product_ids = models.execute_kw(db, uid, password, 'product.template',
                                                            'search_read', [[['barcode', '=', reg["barcode"]]]], {"fields": ["id", "name"]})
                    if existing_product_ids:
                        mensage = {"state":"W",
                            "msg":f'El codigo de barras {reg["barcode"]} ya existe en {existing_product_ids[0]["name"]}'}
                        valid = False

                # validamos que la referencia interna sea unica
                if valid and "default_code" in reg and reg["default_code"]:
                    existing_ref_ids = models.execute_kw(db, uid, password, 'product.template',
                                                         'search_read', [[['default_code', '=', reg["default_code"]]]], {"fields": ["id", "name"]})
                    if existing_ref_ids:
                        mensage = {"state": "W",
                                   "msg": f'La referencia interna "{reg["default_code"]}" ya existe en "{existing_ref_ids[0]["name"]}"'}
                        valid = False

                if valid:
                    reg["categ_id"] = categ_id[0]
                    reg["type"] = "consu"      # Odoo 17+: 'product' → 'consu' + is_storable
                    reg["is_storable"] = True
                    new_id = models.execute_kw(
                        db, uid, password, 'product.template', 'create', [reg]
                    )
                    if new_id:
                        mensage = {"state":"S", "msg":f'Producto {reg["name"]} creado correctamente.', "id": new_id}
                    else:
                        mensage = {"state":"E", "msg":f'Error al crear el producto {product_id}.'}
            else:
                # validamos que el codigo de barras sea unico
                
                    if "barcode" in reg and reg["barcode"]:
                        existing_product_ids = models.execute_kw(db, uid, password, 'product.template', 
                                                                'search_read', [[['barcode', '=', reg["barcode"]],
                                                                            ['id', '!=', product_id]]], {"fields": ["id", "name"]})
                        if existing_product_ids:
                            mensage = {"state":"W", "msg":f'El codigo de barras {reg["barcode"]} ya existe en {existing_product_ids[0]["name"]}'}
                            valid = False
                    
                    if valid:
                        updated_id = models.execute_kw(
                            db, uid, password, 'product.template', 'write', [[product_id], reg]
                        )


                        if updated_id:
                            mensage = {"state":"S", "msg":f'Producto {product_id} actualizado correctamente.'}
                        else:
                            mensage = {"state":"E", "msg":f'Error al actualizar el producto {product_id}.'}
        except Exception as e:
            mensage = {"state":"E", "msg":f'Error al actualizar el producto {product_id}: {str(e)}'}
                
                            # Buscar variantes en product.product
                
            
        return mensage
    
    @staticmethod
    def set_nombre_producto(product_id, nuevo_nombre):
        """
        Actualiza el nombre (product.template.name) en Odoo.
        Escribe en el contexto de idioma es_ES que es el que usa la UI;
        los campos traducibles requieren el contexto correcto, de lo
        contrario el cambio queda en otro idioma y no se ve en la web.
        """
        try:
            models.execute_kw(
                db, uid, password, 'product.template', 'write',
                [[int(product_id)], {'name': nuevo_nombre}],
                {'context': {'lang': 'es_ES'}},
            )
            return {"state": "S", "msg": f"Nombre actualizado para producto {product_id}"}
        except Exception as e:
            logger.error("Error al actualizar nombre (producto_id=%s).", product_id, exc_info=True)
            return {"state": "E", "msg": f"Error al actualizar nombre: {str(e)}"}

    @staticmethod
    def set_descripcion_producto_odoo(product_id, nueva_descripcion):
        """
        Actualiza la descripción de un producto en Odoo.
        Intenta actualizar varios campos relacionados con la descripción web.
        """
        try:
            # Datos base que siempre se actualizan
            update_data = {
                'name': f"{nueva_descripcion}"
            }
            
            # Intentar actualizar campos opcionales del módulo website
            # Solo se aplicarán si existen en la instalación
            campos_opcionales = {
                'website_description': f"<p>{nueva_descripcion}</p>",
                'description_sale': f"{nueva_descripcion}",
                'website_name': f"{nueva_descripcion}",
                '__last_update': False  # Esto fuerza la invalidación de caché
            }
            
            # Primero actualizar los campos base
            models.execute_kw(db, uid, password, 'product.template', 'write', [
                [product_id], 
                update_data
            ])
            
            # Luego intentar actualizar campos opcionales uno por uno
            for campo, valor in campos_opcionales.items():
                try:
                    models.execute_kw(db, uid, password, 'product.template', 'write', [
                        [product_id], 
                        {campo: valor}
                    ])
                except Exception:
                    # Si el campo no existe, continuar con el siguiente
                    pass
            
            # Forzar republicación si el campo existe
            try:
                models.execute_kw(db, uid, password, 'product.template', 'write', [
                    [product_id], 
                    {'is_published': False}
                ])
                models.execute_kw(db, uid, password, 'product.template', 'write', [
                    [product_id], 
                    {'is_published': True}
                ])
            except Exception:
                pass
            
            return {"state": "S", "msg": f"Descripción actualizada correctamente para producto {product_id}"}
        except Exception as e:
            return {"state": "E", "msg": f"Error al actualizar descripción: {str(e)}"}

    @staticmethod
    def set_inventario(id_producto, new_quantity, ajuste=True, motivo="Ajuste de inventario"):
        """Aplica el stock en Odoo y deja el movimiento en el registro (MovimientoStock)."""
        info = {}
        resultado = OdooService._aplicar_inventario(id_producto, new_quantity, ajuste, info)
        if resultado.get("state") != "S":
            estado = "Error"
        elif info.get("antes") == info.get("final"):
            estado = "Sin cambio"
        else:
            estado = "OK"
        registro_stock.registrar(
            origen=motivo, producto_id=id_producto,
            producto=info.get("producto", ""), ref_interna=info.get("ref", ""),
            stock_anterior=info.get("antes"), valor_ingresado=new_quantity, reemplaza=not ajuste,
            stock_final=info.get("final") if estado != "Error" else info.get("verificado"),
            estado=estado, mensaje=resultado.get("msg", ""),
        )
        return resultado

    @staticmethod
    def _aplicar_inventario(id_producto, new_quantity, ajuste, info):
        """Hace el ajuste en Odoo. Va dejando en `info` producto, ref, stock antes y final."""
        try:
            product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', id_producto]]])
            if not product_variant_ids:
                return {"state": "E", "msg": f"No se encontró variante del producto {id_producto}"}

            product_variant_id = product_variant_ids[0]
            location_id = 8

            current_stock = models.execute_kw(db, uid, password, 'product.product', 'read',
                                              [product_variant_id], {'fields': ['qty_available', 'display_name', 'default_code']})
            current_qty = current_stock[0]['qty_available'] if current_stock else 0
            if current_stock:
                info["producto"] = current_stock[0].get('display_name') or ""
                info["ref"] = current_stock[0].get('default_code') or ""

            final_qty = current_qty + new_quantity if ajuste else new_quantity
            info["antes"] = current_qty
            info["final"] = final_qty

            if current_qty == final_qty:
                return {"state": "S", "msg": f"El stock ya es {final_qty}, no se requiere ajuste."}

            # Odoo 17+: ajuste de inventario via stock.quant + action_apply_inventory
            quants = models.execute_kw(db, uid, password, 'stock.quant', 'search_read',
                                       [[['product_id', '=', product_variant_id], ['location_id', '=', location_id]]],
                                       {'fields': ['id']})
            if quants:
                quant_id = quants[0]['id']
                models.execute_kw(db, uid, password, 'stock.quant', 'write',
                                  [[quant_id], {'inventory_quantity': final_qty}])
            else:
                quant_id = models.execute_kw(db, uid, password, 'stock.quant', 'create', [{
                    'product_id': product_variant_id,
                    'location_id': location_id,
                    'inventory_quantity': final_qty,
                }])

            try:
                models.execute_kw(db, uid, password, 'stock.quant', 'action_apply_inventory', [[quant_id]])
            except xmlrpc.client.Fault as fault:
                # Odoo 19: action_apply_inventory no retorna nada y el XML-RPC de esta
                # instancia ya no permite serializar None (allow_none=False), así que la
                # acción se aplica en el servidor pero la respuesta llega como Fault.
                # Se verifica leyendo el stock resultante antes de decidir si fue un error real.
                if "cannot marshal None" not in str(fault):
                    raise
                stock_verificado = models.execute_kw(db, uid, password, 'product.product', 'read',
                                                       [product_variant_id], {'fields': ['qty_available']})
                qty_verificada = stock_verificado[0]['qty_available'] if stock_verificado else None
                info["verificado"] = qty_verificada
                if qty_verificada != final_qty:
                    return {"state": "E", "msg": f"Error al ajustar inventario: {str(fault)}"}

            action = "aumentado" if final_qty > current_qty else "disminuido"
            difference = abs(final_qty - current_qty)
            return {"state": "S", "msg": f"Stock {action} en {difference} unidades. Stock actual: {final_qty}"}

        except Exception as e:
            return {"state": "E", "msg": f"Error al ajustar inventario: {str(e)}"}

    @staticmethod
    def set_tarifas(dict_datos):
        mensage = {}
        
        for i in dict_datos:
            dict_datos[i] = int(dict_datos[i]) if str(i).endswith("_id") else dict_datos[i]

        # Buscar si ya existe un stock.quant para este producto en esta ubicación
        if dict_datos["id"]:
            # Si existe, actualizar la información. Solo se escriben los campos
            # informados: price=None evita pisar un precio real con 0.
            valores = {campo: dict_datos[campo] for campo in ("price", "sequence", "product_code")
                       if dict_datos.get(campo) is not None}
            updated = models.execute_kw(db, uid, password, 'product.supplierinfo', 'write', [[int(dict_datos["id"])], valores])
            if updated:
                mensage = {"state":"S", "msg":f"Tarifa actualizada para '{dict_datos["product_tmpl_id"]}' con '{dict_datos["partner_id"]}'.", "id": int(dict_datos["id"])}
            else:
                mensage = {"state":"E", "msg":f"Error al actualizar la tarifa."}
        else:
            # Si no existe, crearlo
            try:
                new_supplierinfo_id = models.execute_kw(db, uid, password, 'product.supplierinfo', 'create', [{
                    'product_tmpl_id': dict_datos["product_tmpl_id"],
                    'partner_id': dict_datos["partner_id"],
                    'sequence': dict_datos["sequence"],
                    'price': dict_datos["price"] or 0,
                    'product_code': dict_datos.get("product_code") or False,
                    'delay': 1
                }])
                mensage = {"state":"S", "msg":f"Nuevo registro de tarifa creado con ID {new_supplierinfo_id} para '{dict_datos['product_tmpl_id']}' con '{dict_datos["partner_id"]}'.", "id": new_supplierinfo_id}
            except Exception as e:
                mensage = {"state":"E", "msg":f"Error al crear la tarifa: {str(e)}"}
        return mensage
    
    @staticmethod   
    def set_rutas(dict_datos):
        mensage = {}
        for i in dict_datos:
            dict_datos[i] = int(dict_datos[i]) if str(i).endswith("_id") else dict_datos[i]

        # Odoo rechaza mínimo > máximo y el error cortaba toda la sincronización.
        minimo, maximo = dict_datos.get("product_min_qty"), dict_datos.get("product_max_qty")
        if minimo is not None and maximo is not None and float(minimo) > float(maximo):
            return {"state": "E", "msg": (
                f"Mínimo ({minimo}) mayor que máximo ({maximo}) en la planilla para el producto "
                f"{dict_datos.get('product_id')}. Corrígelo en la Tabla Base.")}

        # Buscar si ya existe un stock.quant para este producto en esta ubicación
        if dict_datos["id"]:
            # Si existe, actualizar la información
            try:
                updated = models.execute_kw(db, uid, password, 'stock.warehouse.orderpoint', 'write', [[int(dict_datos["id"])], {
                    'product_min_qty': dict_datos["product_min_qty"],  # Cuando el stock baja de 10, se activa el reabastecimiento
                    'product_max_qty': dict_datos["product_max_qty"],
                }])
            except Exception as e:
                return {"state": "E", "msg": f"Error al actualizar la Ruta de '{dict_datos['product_id']}': {e}"}
            if updated:
                mensage = {"state":"S", "msg":f"Ruta actualizada para '{dict_datos["product_id"]}'.", "id": int(dict_datos["id"])}
            else:
                mensage = {"state":"E", "msg":f"Error al actualizar la Ruta."}
        else:
            try:
                product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', dict_datos["product_id"]]]])
                product_variant_id = product_variant_ids[0]
                # Si no existe, crearlo
                ret = models.execute_kw(db, uid, password, 'stock.warehouse.orderpoint', 'create', [{
                    'product_id': product_variant_id,
                    'location_id': dict_datos["location_id"],
                    'product_min_qty': dict_datos["product_min_qty"],  # Cuando el stock baja de 10, se activa el reabastecimiento
                    'product_max_qty': dict_datos["product_max_qty"],
                }])
                mensage = {"state":"S", "msg":f"Nuevo registro de ruta creado con ID {ret} para '{dict_datos['product_id']}'.", "id": ret}
            except Exception as e:
                mensage = {"state":"E", "msg":f"Error al crear la ruta: {str(e)}"}
        return mensage
    
    @staticmethod    
    def buscar_proveedor_odoo(id):
        # Busca el proveedor por ID en Odoo
        proveedores = models.execute_kw(db, uid, password, 'res.partner', 'search_read', [[['id', '=', id]]], {'fields': ['id', 'name']})
        return proveedores[0] if proveedores else None

    @staticmethod
    def buscar_producto_odoo(id):
        # Busca el producto por ID en Odoo
        productos = models.execute_kw(db, uid, password, 'product.product', 'search_read', [[['product_tmpl_id', '=', id]]], {'fields': ['id', 'name', 'uom_id', 'qty_available']})
        return productos[0] if productos else None

    @staticmethod
    def crear_orden_compra_odoo(proveedor_id):
        # Crea la orden de compra en Odoo
        po_id = models.execute_kw(db, uid, password, 'purchase.order', 'create', [{
            'partner_id': proveedor_id,
            'state': 'draft',
        }])
        return po_id
    
    def obtiene_name_compra_odoo(purchase_id):
        # Obtiene el nombre para mostrar de la orden de compra
        purchase = models.execute_kw(db, uid, password, 'purchase.order', 'search_read', [[['id', '=', purchase_id]]], {'fields': ['name']})
        return purchase[0]['name'] if purchase else None

    @staticmethod
    def crear_detalle_orden_compra_odoo(purchase_id, order_lines):
        # Agrega las líneas de la orden de compra en Odoo
        for line in order_lines:
            product_id = OdooService.get_product_product(line['product_id'])
            if product_id:
                line_id = models.execute_kw(db, uid, password, 'purchase.order.line', 'create', [{
                    'order_id': purchase_id,
                    'product_id': product_id[0],
                    'product_qty': line['product_qty'],
                    'price_unit': line['price_unit'],
                    'name': line['name'],
                }])
        return True

    # # obtener lista de precios
    # @staticmethod
    # def obtener_lista_precios(producto_id):
    #     precios = models.execute_kw(db, uid, password, 'product.pricelist', 'search_read', [], {'fields': ['id', 'pricelist_id', 'fixed_price']})
    #     return precios

    @staticmethod
    def confirmar_orden_compra_odoo(purchase_id):
        # Confirma la orden de compra
        models.execute_kw(db, uid, password, 'purchase.order', 'button_confirm', [[purchase_id]])

    @staticmethod
    def validar_recepcion_odoo(name):
        # Busca el picking generado y valida la recepción
        pickings = models.execute_kw(db, uid, password, 'stock.picking', 'search_read', [[['origin', '=', name]]], {'fields': ['id']})
        if pickings:
            picking_id = pickings[0]['id']
            models.execute_kw(db, uid, password, 'stock.picking', 'button_validate', [[picking_id]])
            
    @staticmethod
    def cancelar_y_eliminar_orden_compra_odoo(purchase_id):
        # Cancela y elimina la orden de compra
        try:
            # Con recepciones validadas no se elimina: el stock quedaría sumado sin OC.
            recibidas = models.execute_kw(
                db, uid, password, 'stock.picking', 'search_count',
                [[['purchase_id', '=', purchase_id], ['state', '=', 'done'], ['return_id', '=', False]]],
            )
            if recibidas:
                return {"state": "E", "msg": (
                    f"La orden de compra {purchase_id} ya tiene recepciones validadas en Odoo. "
                    "Usa 'Devolver y bloquear' para regresar el stock y bloquearla.")}
            _accion_sin_respuesta('purchase.order', 'button_cancel', [purchase_id])
            _accion_sin_respuesta('purchase.order', 'unlink', [purchase_id])
            return {"state": "S", "msg": f"Orden de compra {purchase_id} cancelada y eliminada."}
        except Exception as e:
            logger.error("Error al cancelar/eliminar la orden de compra %s.", purchase_id, exc_info=True)
            if 'cannot marshal None' in str(e):
                # Bug conocido de Odoo: al fallar la validación de button_cancel/unlink
                # (p.ej. la OC ya tiene recepciones validadas), el servidor intenta
                # serializar un Fault XML-RPC con mensaje None, lo que revienta el
                # marshalling y devuelve un traceback crudo en vez de un UserError legible.
                msg = (
                    f"No se pudo cancelar la orden de compra {purchase_id} en Odoo. "
                    "Esto ocurre normalmente cuando la orden ya tiene recepciones "
                    "(entradas de stock) validadas. Usa la opción 'Devolver y bloquear' "
                    "para regresar el stock y bloquearla."
                )
            else:
                msg = f"Error al cancelar/eliminar la orden de compra {purchase_id}: {str(e)}"
            return {"state": "E", "msg": msg}

    @staticmethod
    def devolver_y_bloquear_orden_compra_odoo(purchase_id):
        """
        1. Crea devoluciones para todas las recepciones validadas de la OC.
        2. Valida cada devolución (regresa el stock).
        3. Bloquea la OC (button_lock), ya que con recepciones no se puede cancelar.
        """
        try:
            # Buscar recepciones validadas asociadas a la OC
            pickings = models.execute_kw(
                db, uid, password,
                'stock.picking', 'search_read',
                [[['purchase_id', '=', purchase_id], ['state', '=', 'done']]],
                {'fields': ['id', 'name', 'return_id']},
            )
            # Las devoluciones también quedan asociadas a la OC: solo se devuelven recepciones.
            pickings = [p for p in pickings if not p.get('return_id')]

            def crear_devolucion(picking_id):
                """Crea la devolución de una recepción con todo lo recibido. Devuelve su id."""
                wizard_id = models.execute_kw(
                    db, uid, password,
                    'stock.return.picking', 'create',
                    [{'picking_id': picking_id}],
                )
                # Desde Odoo 17 las líneas parten con cantidad 0 y action_create_returns
                # falla: se pone en cada línea la cantidad recibida en su movimiento.
                lineas = models.execute_kw(
                    db, uid, password,
                    'stock.return.picking.line', 'search_read',
                    [[['wizard_id', '=', wizard_id]]],
                    {'fields': ['id', 'quantity', 'move_quantity']},
                )
                for linea in lineas:
                    if not linea.get('quantity') and linea.get('move_quantity'):
                        models.execute_kw(
                            db, uid, password,
                            'stock.return.picking.line', 'write',
                            [[linea['id']], {'quantity': linea['move_quantity']}],
                        )
                action = models.execute_kw(
                    db, uid, password,
                    'stock.return.picking', 'action_create_returns',
                    [[wizard_id]],
                )
                return action.get('res_id') if isinstance(action, dict) else None

            def validar(picking_id):
                """Valida la devolución con todas sus cantidades (Odoo 17+: quantity y picked)."""
                moves = models.execute_kw(
                    db, uid, password,
                    'stock.move', 'search_read',
                    [[['picking_id', '=', picking_id], ['state', 'not in', ['done', 'cancel']]]],
                    {'fields': ['id', 'product_uom_qty', 'quantity']},
                )
                for mv in moves:
                    valores = {'picked': True}
                    if (mv.get('quantity') or 0) < (mv.get('product_uom_qty') or 0):
                        valores['quantity'] = mv['product_uom_qty']
                    models.execute_kw(db, uid, password, 'stock.move', 'write', [[mv['id']], valores])
                result = _accion_sin_respuesta('stock.picking', 'button_validate', [picking_id])
                if isinstance(result, dict) and result.get('res_model') == 'stock.backorder.confirmation':
                    wiz_id = result.get('res_id') or models.execute_kw(
                        db, uid, password,
                        'stock.backorder.confirmation', 'create',
                        [{'pick_ids': [(4, picking_id)], 'show_transfers': False}],
                    )
                    _accion_sin_respuesta('stock.backorder.confirmation', 'process', [wiz_id])

            devoluciones = []
            for picking in pickings:
                # Si un intento anterior ya creó la devolución, se reutiliza (y si ya
                # está hecha no se devuelve dos veces).
                previas = models.execute_kw(
                    db, uid, password,
                    'stock.picking', 'search_read',
                    [[['return_id', '=', picking['id']], ['state', '!=', 'cancel']]],
                    {'fields': ['id', 'state']},
                )
                if any(p['state'] == 'done' for p in previas):
                    continue
                pendiente = next((p['id'] for p in previas), None)
                new_picking_id = pendiente or crear_devolucion(picking['id'])
                if not new_picking_id:
                    continue
                validar(new_picking_id)
                devoluciones.append(new_picking_id)

            # Bloquear la OC (no se puede cancelar con recepciones)
            estado = models.execute_kw(db, uid, password, 'purchase.order', 'read',
                                       [[purchase_id]], {'fields': ['state']})[0]['state']
            if estado != 'cancel':
                _accion_sin_respuesta('purchase.order', 'button_lock', [purchase_id])

            return {
                "state": "S",
                "msg": f"OC {purchase_id} devuelta y bloqueada. Devoluciones: {devoluciones}",
                "devoluciones": devoluciones,
            }
        except Exception as e:
            logger.error("Error al devolver/bloquear OC %s.", purchase_id, exc_info=True)
            return {"state": "E", "msg": f"Error al devolver/bloquear OC {purchase_id}: {str(e)}"}
        
    @staticmethod
    def obtiene_detalle_compra_odoo(purchase_id):
        # Obtiene el detalle de la orden de compra
        try:
            detalle = models.execute_kw(db, uid, password, 'purchase.order.line', 'search_read', [[['order_id', '=', purchase_id]]], {'fields': ['product_id', 'product_qty', 'price_unit', 'name']})
            return {"state": "S", "msg": f"Detalle obtenido correctamente.", "detalle": detalle}
        except Exception as e:
            logger.error("Error al obtener el detalle de la orden de compra %s.", purchase_id, exc_info=True)
            return {"state": "E", "msg": f"Error al obtener el detalle de la orden de compra {purchase_id}: {str(e)}"}
    
    @staticmethod
    def obtener_resumen_existencias(producto=None, mes=None, anio=None, incluir_precios=True):
        """
        Obtiene el resumen de movimientos de existencias para un mes y año específicos
        
        Args:
            producto: ID del producto a filtrar (opcional)
            mes: Mes a consultar (opcional)  
            anio: Año a consultar (opcional)
            incluir_precios: Si incluir precios de venta/compra (opcional)
        """
        # Construir el dominio de filtros
        domain = []
        
        # Filtro por producto si se especifica
        if producto:
            product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', producto]]])
            if not product_variant_ids:
                return {"state": "E", "msg": f"No se encontró variante del producto {producto}"}
            product_variant_id = product_variant_ids[0]
            domain.append(['product_id', '=', int(product_variant_id)])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['date', '>=', f'{anio}-{mes:02d}-01'])
            # Calcular el último día del mes
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['date', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Solo movimientos confirmados
        domain.append(['state', '=', 'done'])
        
        # Obtiene el resumen de movimientos
        movimientos = models.execute_kw(
            db, 
            uid, 
            password, 
            'stock.move.line', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'location_id', 'location_dest_id', 'qty_done', 'date', 'move_id', 'reference', 'picking_id']}
        )
        
        if incluir_precios and movimientos:
            # Obtener información adicional de precios para cada movimiento
            for movimiento in movimientos:
                movimiento['precio_unitario'] = 0
                movimiento['tipo_operacion'] = 'interno'
                
                # Obtener información del stock.move para tener más contexto
                if movimiento.get('move_id'):
                    move_info = models.execute_kw(db, uid, password, 'stock.move', 'read', 
                                                [movimiento['move_id'][0]], 
                                                {'fields': ['origin', 'purchase_line_id', 'sale_line_id']})
                    
                    if move_info and len(move_info) > 0:
                        move_data = move_info[0]
                        
                        # Si tiene purchase_line_id, es una compra
                        if move_data.get('purchase_line_id'):
                            movimiento['tipo_operacion'] = 'compra'
                            # Obtener precio de compra
                            purchase_line = models.execute_kw(db, uid, password, 'purchase.order.line', 'read', 
                                                            [move_data['purchase_line_id'][0]], 
                                                            {'fields': ['price_unit']})
                            if purchase_line:
                                movimiento['precio_unitario'] = purchase_line[0]['price_unit']
                        
                        # Si tiene sale_line_id, es una venta
                        elif move_data.get('sale_line_id'):
                            movimiento['tipo_operacion'] = 'venta'
                            # Obtener precio de venta
                            sale_line = models.execute_kw(db, uid, password, 'sale.order.line', 'read', 
                                                        [move_data['sale_line_id'][0]], 
                                                        {'fields': ['price_unit']})
                            if sale_line:
                                movimiento['precio_unitario'] = sale_line[0]['price_unit']
                
                # Calcular valor total del movimiento
                movimiento['valor_total'] = movimiento['qty_done'] * movimiento['precio_unitario']
        
        return movimientos

    @staticmethod
    def obtener_resumen_ventas(producto=None, mes=None, anio=None):
        """
        Obtiene específicamente las ventas con sus precios
        """
        # Construir dominio para líneas de venta
        domain = []
        
        # if producto:
        #     product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['id', '=', producto]]])
        #     if not product_variant_ids:
        #         return []
        #     product_variant_id = product_variant_ids[0]
        domain.append(['product_id', '=', producto])
        
        # Filtro por órdenes confirmadas
        domain.append(['order_id.state', 'in', ['sale', 'done']])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['order_id.date_order', '>=', f'{anio}-{mes:02d}-01'])
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['order_id.date_order', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Obtener líneas de venta
        ventas = models.execute_kw(
            db, 
            uid, 
            password, 
            'sale.order.line', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'product_uom_qty', 'qty_delivered', 'price_unit', 'price_subtotal', 'order_id', 'name']}
        )
        
        return ventas

    @staticmethod
    def obtener_compras(producto=None, mes=None, anio=None):
        """
        Obtiene específicamente las compras con sus precios e información del proveedor
        """
        # Construir dominio para líneas de compra
        domain = []
        
        if producto:
            product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', producto]]])
            if not product_variant_ids:
                return {"state": "E", "msg": f"No se encontró variante del producto {producto}"}
            product_variant_id = product_variant_ids[0]
            domain.append(['product_id', '=', int(product_variant_id)])
        
        # Filtro por órdenes confirmadas
        domain.append(['order_id.state', 'in', ['purchase', 'done']])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['order_id.date_order', '>=', f'{anio}-{mes:02d}-01'])
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['order_id.date_order', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Obtener líneas de compra con información de la orden (incluyendo partner)
        compras = models.execute_kw(
            db, 
            uid, 
            password, 
            'purchase.order.line', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'product_qty', 'qty_received', 'price_unit', 'price_subtotal', 'order_id', 'name']}
        )
        
        # Procesar compras para agregar información del proveedor
        compras_con_proveedor = []
        for compra in compras:
            if compra.get('order_id'):
                # Obtener datos completos de la orden de compra (incluyendo proveedor)
                orden_info = models.execute_kw(
                    db, 
                    uid, 
                    password, 
                    'purchase.order', 
                    'read', 
                    [compra['order_id'][0]], 
                    {'fields': ['partner_id', 'date_order']}
                )
                
                if orden_info:
                    # Agregar información del proveedor a la línea de compra
                    compra['partner_id'] = orden_info[0].get('partner_id')
                    compra['date_order'] = orden_info[0].get('date_order')
            
            compras_con_proveedor.append(compra)
        
        return compras_con_proveedor
    
    
    @staticmethod
    def obtener_resumenes_ventas(productos: list = None, mes: int = None, anio: int = None):
        """
        Obtiene específicamente las ventas con sus precios
        """
        # Construir dominio para líneas de venta
        domain = []
        
        # if productos:
        #     product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', 'in', productos]]])
        #     if not product_variant_ids:
        #         return {"state": "E", "msg": f"No se encontraron variantes para los productos {productos}"}
        domain.append(['product_id', 'in', productos])
        
        # Filtro por órdenes confirmadas
        domain.append(['order_id.state', 'in', ['sale', 'done']])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['order_id.date_order', '>=', f'{anio}-{mes:02d}-01'])
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['order_id.date_order', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Obtener líneas de venta
        ventas = models.execute_kw(
            db, 
            uid, 
            password, 
            'sale.order.line', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'product_uom_qty', 'qty_delivered', 'price_unit', 'price_subtotal', 'order_id', 'name', 'create_date']}
        )
        
        return ventas

    @staticmethod
    def obtener_resumenes_ventas_rango(productos: list = None, fecha_desde: date = None, fecha_hasta: date = None):
        """
        Obtiene líneas de ventas para una lista de productos en un rango de fechas.

        Args:
            productos: Lista de IDs de product.product
            fecha_desde: Fecha inicial (incluida)
            fecha_hasta: Fecha final (incluida)
        """
        domain = [
            ['order_id.state', 'in', ['sale', 'done']]
        ]

        if productos:
            domain.append(['product_id', 'in', productos])

        if fecha_desde:
            domain.append(['order_id.date_order', '>=', f"{fecha_desde.strftime('%Y-%m-%d')} 00:00:00"])

        if fecha_hasta:
            domain.append(['order_id.date_order', '<=', f"{fecha_hasta.strftime('%Y-%m-%d')} 23:59:59"])

        ventas = models.execute_kw(
            db,
            uid,
            password,
            'sale.order.line',
            'search_read',
            [domain],
            {'fields': ['product_id', 'product_uom_qty', 'qty_delivered', 'price_unit', 'price_subtotal', 'order_id', 'name', 'create_date']}
        )

        return ventas

    @staticmethod
    def obtener_ventas(producto=None, mes=None, anio=None):
        """
        Obtiene específicamente las ventas de un producto con sus precios
        Similar a obtener_compras pero para ventas
        """
        # Construir dominio para líneas de venta
        domain = []
        
        if producto:
            product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', producto]]])
            if not product_variant_ids:
                return {"state": "E", "msg": f"No se encontró variante del producto {producto}"}
            product_variant_id = product_variant_ids[0]
            domain.append(['product_id', '=', int(product_variant_id)])
        
        # Filtro por órdenes confirmadas
        domain.append(['order_id.state', 'in', ['sale', 'done']])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['order_id.date_order', '>=', f'{anio}-{mes:02d}-01'])
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['order_id.date_order', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Obtener líneas de venta
        ventas = models.execute_kw(
            db, 
            uid, 
            password, 
            'sale.order.line', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'product_uom_qty', 'qty_delivered', 'price_unit', 'price_subtotal', 'order_id', 'name']}
        )
        
        return ventas
    
    @staticmethod
    def obtener_ajustes_inventario(producto=None, mes=None, anio=None):
        """
        Obtiene los ajustes de inventario (movimientos de stock sin compra/venta)
        Estos son movimientos desde/hacia ubicaciones de inventario de ajuste
        
        Args:
            producto: ID del producto template
            mes: Mes (1-12)
            anio: Año
            
        Returns:
            list: Lista de ajustes con cantidad y tipo (entrada/salida)
        """
        # Construir dominio para movimientos de stock
        domain = []
        
        if producto:
            product_variant_ids = models.execute_kw(db, uid, password, 'product.product', 'search', [[['product_tmpl_id', '=', producto]]])
            if not product_variant_ids:
                return []
            product_variant_id = product_variant_ids[0]
            domain.append(['product_id', '=', int(product_variant_id)])
        
        # Filtro por movimientos confirmados
        domain.append(['state', '=', 'done'])
        
        # Filtros por fecha si se especifican
        if mes and anio:
            domain.append(['date', '>=', f'{anio}-{mes:02d}-01'])
            if mes == 12:
                siguiente_mes = 1
                siguiente_anio = anio + 1
            else:
                siguiente_mes = mes + 1
                siguiente_anio = anio
            domain.append(['date', '<', f'{siguiente_anio}-{siguiente_mes:02d}-01'])
        
        # Obtener ubicaciones de ajuste de inventario
        inventory_locations = models.execute_kw(
            db, uid, password, 
            'stock.location', 
            'search', 
            [[['usage', '=', 'inventory']]]
        )
        
        if not inventory_locations:
            return []
        
        # Obtener movimientos desde o hacia ubicaciones de inventario
        # Esto captura los ajustes manuales de stock
        movimientos = models.execute_kw(
            db, 
            uid, 
            password, 
            'stock.move', 
            'search_read', 
            [domain], 
            {'fields': ['product_id', 'product_uom_qty', 'location_id', 'location_dest_id', 'date', 'origin', 'reference']}
        )
        
        ajustes = []
        for mov in movimientos:
            location_id = mov.get('location_id', [False])[0] if mov.get('location_id') else False
            location_dest_id = mov.get('location_dest_id', [False])[0] if mov.get('location_dest_id') else False
            
            # Verificar si es un ajuste de inventario
            is_inventory_adjustment = (
                location_id in inventory_locations or 
                location_dest_id in inventory_locations
            )
            
            if is_inventory_adjustment:
                # Determinar si es entrada o salida
                if location_id in inventory_locations:
                    # Desde inventario a ubicación normal = ENTRADA (positivo)
                    ajuste_tipo = 'entrada'
                    cantidad = mov.get('product_uom_qty', 0)
                else:
                    # Desde ubicación normal a inventario = SALIDA (negativo)
                    ajuste_tipo = 'salida'
                    cantidad = -mov.get('product_uom_qty', 0)
                
                ajustes.append({
                    'product_id': mov.get('product_id'),
                    'cantidad': cantidad,
                    'tipo': ajuste_tipo,
                    'date': mov.get('date'),
                    'origin': mov.get('origin', 'Ajuste Manual'),
                    'reference': mov.get('reference', '')
                })
        
        return ajustes
    
    # funcion que trae los ids de los productos, su stock en funcion de su codigo de referencia interna
    @staticmethod
    def get_productos_odoo_by_refs(codigos_internos: list):
        return models.execute_kw(db, uid, password, 'product.product', 'search_read', [[['default_code', 'in', codigos_internos]]], {'fields': ['id', 'default_code', 'qty_available', 'name', 'is_favorite']})

    @staticmethod
    def get_favoritos_por_ids(tmpl_ids: list) -> list:
        """Retorna [{"id": int, "is_favorite": bool}] para una lista de product.template IDs."""
        if not tmpl_ids:
            return []
        return models.execute_kw(
            db, uid, password,
            "product.template", "read",
            [tmpl_ids],
            {"fields": ["id", "is_favorite"]},
        )

    @staticmethod
    def set_priority_productos(producto_id, prioridad):
        try:
            val_favorito = prioridad is True or prioridad == "1" or prioridad == 1
            models.execute_kw(db, uid, password, 'product.template', 'write', [
                [producto_id],
                {'is_favorite': val_favorito}
            ])
            return {"state": "S", "msg": f"Favorito actualizado correctamente para producto {producto_id}"}
        except Exception as e:
            return {"state": "E", "msg": f"Error al actualizar favorito: {str(e)}"}
                
    @staticmethod
    def set_sale_ok_productos(producto_id, sale_ok):
        """
        Actualiza el estado sale_ok (Puede ser vendido) del producto en Odoo.
        """
        try:
            val_sale_ok = True if sale_ok is True or sale_ok == "1" else False
            
            models.execute_kw(db, uid, password, 'product.template', 'write', [
                [producto_id], 
                {'sale_ok': val_sale_ok}
            ])
            return {"state": "S", "msg": f"Estado de venta actualizado correctamente para producto {producto_id}"}
        except Exception as e:
            return {"state": "E", "msg": f"Error al actualizar estado de venta: {str(e)}"}
    
    @staticmethod
    def get_ventas_hoy():
        """
        Obtiene las órdenes de venta (sale.order) del día de hoy (America/Santiago).
        Si hoy no tiene órdenes, devuelve las del último día con ventas.
        Odoo almacena fechas en UTC; se convierte el rango local a UTC para filtrar.
        Retorna: {"ordenes": [...], "label": "Hoy DD/MM/YYYY" | "Último día con ventas: DD/MM/YYYY"}
        """
        from zoneinfo import ZoneInfo
        from datetime import datetime

        tz = ZoneInfo("America/Santiago")
        tz_utc = ZoneInfo("UTC")

        def _to_local(date_str):
            if not date_str:
                return ""
            dt_utc = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_utc)
            return dt_utc.astimezone(tz).strftime("%Y-%m-%d %H:%M:%S")

        def _query(start_utc_str, end_utc_str):
            domain = [
                ["date_order", ">=", start_utc_str],
                ["date_order", "<=", end_utc_str],
                ["state", "in", ["sale", "done"]],
            ]
            return models.execute_kw(
                db, uid, password,
                "sale.order", "search_read",
                [domain],
                {"fields": ["id", "name", "date_order", "amount_total", "team_id"],
                 "order": "date_order desc"},
            )

        # Rango de hoy en hora local → UTC
        now_local = datetime.now(tz)
        start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_local   = now_local.replace(hour=23, minute=59, second=59, microsecond=0)
        start_utc = start_local.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S")
        end_utc   = end_local.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S")

        ordenes = _query(start_utc, end_utc)
        label = f"Hoy {now_local.strftime('%d/%m/%Y')}"

        # Fallback: si hoy no tiene ventas buscar el último día con órdenes
        if not ordenes:
            ultima = models.execute_kw(
                db, uid, password,
                "sale.order", "search_read",
                [[["state", "in", ["sale", "done"]]]],
                {"fields": ["date_order"], "order": "date_order desc", "limit": 1},
            )
            if ultima:
                last_utc = datetime.strptime(ultima[0]["date_order"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_utc)
                last_local = last_utc.astimezone(tz)
                day_start = last_local.replace(hour=0, minute=0, second=0, microsecond=0)
                day_end   = last_local.replace(hour=23, minute=59, second=59, microsecond=0)
                ordenes = _query(
                    day_start.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S"),
                    day_end.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S"),
                )
                label = f"Último día con ventas: {last_local.strftime('%d/%m/%Y')}"

        # Convertir fechas a hora local
        for o in ordenes:
            o["date_order"] = _to_local(o.get("date_order", ""))

        return {"ordenes": ordenes, "label": label}

    @staticmethod
    def get_detalle_venta(order_id: int):
        """Obtiene las líneas de una orden de venta (sale.order.line) por su ID."""
        return models.execute_kw(
            db, uid, password,
            "sale.order.line", "search_read",
            [[["order_id", "=", order_id]]],
            {"fields": ["product_id", "name", "product_uom_qty", "price_unit", "discount", "price_subtotal"],
             "order": "id asc"},
        )

    @staticmethod
    def get_ventas_semana():
        """
        Obtiene los totales de ventas de los últimos 7 días (America/Santiago).
        Retorna lista de {"fecha": "DD/MM", "total": float}
        """
        from zoneinfo import ZoneInfo
        from datetime import timedelta

        tz = ZoneInfo("America/Santiago")
        tz_utc = ZoneInfo("UTC")
        now_local = datetime.now(tz)

        result = []
        for i in range(6, -1, -1):
            day = now_local - timedelta(days=i)
            start_utc = day.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S")
            end_utc = day.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S")
            ordenes = models.execute_kw(
                db, uid, password, "sale.order", "search_read",
                [[["date_order", ">=", start_utc], ["date_order", "<=", end_utc], ["state", "in", ["sale", "done"]]]],
                {"fields": ["amount_total"]},
            )
            result.append({"fecha": day.strftime("%d/%m"), "total": sum(o["amount_total"] for o in ordenes)})
        return result

    @staticmethod
    def get_ventas_dias(dias=14):
        """
        Totales de venta de los últimos `dias` días (America/Santiago), del más antiguo al de hoy.
        Una sola consulta a Odoo. Retorna lista de {"fecha": "DD/MM", "total": float}.
        """
        from zoneinfo import ZoneInfo
        from datetime import timedelta

        tz = ZoneInfo("America/Santiago")
        tz_utc = ZoneInfo("UTC")
        hoy = datetime.now(tz).replace(hour=0, minute=0, second=0, microsecond=0)
        inicio = hoy - timedelta(days=dias - 1)
        desde_utc = inicio.astimezone(tz_utc).strftime("%Y-%m-%d %H:%M:%S")

        ordenes = models.execute_kw(
            db, uid, password, "sale.order", "search_read",
            [[["date_order", ">=", desde_utc], ["state", "in", ["sale", "done"]]]],
            {"fields": ["date_order", "amount_total"]},
        )
        totales = {}
        for o in ordenes:
            fecha = datetime.strptime(o["date_order"], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz_utc).astimezone(tz).date()
            totales[fecha] = totales.get(fecha, 0) + o["amount_total"]
        return [
            {"fecha": (inicio + timedelta(days=i)).strftime("%d/%m"),
             "total": totales.get((inicio + timedelta(days=i)).date(), 0)}
            for i in range(dias)
        ]

    @staticmethod
    def get_movimientos_producto(producto_nombre, limit=25):
        """
        Obtiene los últimos movimientos de stock completados para un producto dado su nombre.
        """
        products = models.execute_kw(db, uid, password, "product.template", "search_read",
            [[["name", "ilike", producto_nombre]]],
            {"fields": ["id"], "limit": 5},
        )
        if not products:
            return []
        product_tmpl_ids = [p["id"] for p in products]
        product_ids = models.execute_kw(db, uid, password, "product.product", "search",
            [[["product_tmpl_id", "in", product_tmpl_ids]]]
        )
        if not product_ids:
            return []
        move_lines = models.execute_kw(db, uid, password, "stock.move.line", "search_read",
            [[["product_id", "in", product_ids], ["state", "=", "done"]]],
            {"fields": ["date", "qty_done", "location_id", "location_dest_id", "reference", "picking_id"],
             "order": "date desc", "limit": limit},
        )
        if not move_lines:
            return []

        # Obtener origin desde stock.picking (contiene el número de venta S17983)
        picking_ids = [ml["picking_id"][0] for ml in move_lines if ml.get("picking_id")]
        origin_map = {}
        if picking_ids:
            pickings = models.execute_kw(db, uid, password, "stock.picking", "read",
                [list(set(picking_ids))], {"fields": ["id", "origin", "name"]},
            )
            origin_map = {p["id"]: p.get("origin") or p.get("name") or "" for p in pickings}

        for ml in move_lines:
            pid = ml.get("picking_id")
            ml["origin"] = origin_map.get(pid[0] if isinstance(pid, (list, tuple)) else pid, "")

        return move_lines

    @staticmethod
    def get_ventas_por_producto_tmpl(fecha_desde: str, fecha_hasta: str, product_tmpl_ids: list = None):
        """
        Retorna cantidades vendidas agrupadas por product.template en un rango de fechas.
        fecha_desde / fecha_hasta: "YYYY-MM-DD"
        Retorna: {tmpl_id: {"nombre": str, "qty": float}}
        """
        def _acumular(lines):
            result = {}
            for line in lines:
                tmpl = line.get("product_template_id")
                if not tmpl:
                    continue
                tmpl_id, nombre = tmpl[0], tmpl[1]
                qty = line.get("product_uom_qty") or 0
                if tmpl_id in result:
                    result[tmpl_id]["qty"] += qty
                else:
                    result[tmpl_id] = {"nombre": nombre, "qty": qty}
            return result

        if product_tmpl_ids:
            # Camino rápido: Odoo filtra por producto server-side en una sola query.
            # sale.order.line con dominio relacional solo es eficiente cuando el
            # conjunto de productos es pequeño (Odoo usa índice en product_id).
            lines = models.execute_kw(
                db, uid, password,
                "sale.order.line", "search_read",
                [[
                    ["order_id.date_order", ">=", f"{fecha_desde} 00:00:00"],
                    ["order_id.date_order", "<=", f"{fecha_hasta} 23:59:59"],
                    ["order_id.state", "in", ["sale", "done"]],
                    ["product_uom_qty", ">", 0],
                    ["product_id.product_tmpl_id", "in", product_tmpl_ids],
                ]],
                {"fields": ["product_template_id", "product_uom_qty"]},
            )
            return _acumular(lines)

        # Camino general (sin filtro de productos): buscar primero en sale.order
        # que tiene índice en date_order y state, luego bajar a las líneas.
        order_ids = models.execute_kw(
            db, uid, password,
            "sale.order", "search",
            [[
                ["date_order", ">=", f"{fecha_desde} 00:00:00"],
                ["date_order", "<=", f"{fecha_hasta} 23:59:59"],
                ["state", "in", ["sale", "done"]],
            ]],
        )
        if not order_ids:
            return {}
        lines = models.execute_kw(
            db, uid, password,
            "sale.order.line", "search_read",
            [[["order_id", "in", order_ids], ["product_uom_qty", ">", 0]]],
            {"fields": ["product_template_id", "product_uom_qty"]},
        )
        return _acumular(lines)

    #main
if __name__ == "__main__":
    # Ejemplo de uso
    odoo_service = OdooService()
    productos = odoo_service.get_productos_odoo_by_refs(codigos_internos=["KROMA001", "KROMA002", "KROMA003", "KROMA004", "KROMA005", "KROMA006", "KROMA007", "KROMA008", "KROMA009", "KROMA010", "KROMA011", "KROMA012", "KROMA013", "KROMA014", "KROMA015", "KROMA016", "KROMA017", "KROMA018", "KROMA019", "KROMA020", "KROMA021", "KROMA022", "KROMA023", "KROMA024", "KROMA025", "KROMA026", "KROMA027", "KROMA028", "KROMA029", "KROMA030", "KROMA031", "KROMA032", "KROMA033", "KROMA034"])
    print(productos)