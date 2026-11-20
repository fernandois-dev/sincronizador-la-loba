"""
Herramientas del asistente. TODAS son de solo lectura.

El modelo nunca ve este código: solo ve ESQUEMAS (nombre, descripción y
parámetros de cada herramienta). Por eso las descripciones importan tanto:
son lo único que usa para decidir qué herramienta llamar y cómo.
"""
import json

from django.db.models import Q

from modules.servidor.models import MovimientoProductoMes, OdooProducto

MAX_RESULTADOS = 15        # tope de filas que se le devuelven al modelo
MIN_RESULTADOS_BUSQUEDA = 6  # piso: con menos, el modelo no ve las variantes (19-nov, espuma picada)
MAX_CARACTERES = 8000      # tope del texto de cada resultado (cuida tokens y costo)


# ── Implementaciones ─────────────────────────────────────────────────────────

def buscar_producto_v1(texto: str, limite: int = 10) -> dict:
    """Versión anterior (paso 2): subcadenas con icontains, todas las palabras deben aparecer.

    Ya no la usa el agente; se conserva para comparar en scripts/ia_rag3_buscar.py.
    """
    palabras = [p for p in str(texto).split() if len(p) > 1][:6]
    if not palabras:
        return {"error": "Indica al menos una palabra para buscar."}

    filtro = Q()
    for p in palabras:
        filtro &= Q(name__icontains=p) | Q(default_code__icontains=p) | Q(barcode__icontains=p)

    limite = max(1, min(int(limite), MAX_RESULTADOS))
    qs = OdooProducto.objects.filter(filtro, activo=True).order_by("name")
    total = qs.count()
    productos = [
        {
            "id": p.id,
            "nombre": p.name,
            "codigo": p.default_code or "",
            "precio_venta": float(p.list_price or 0),
        }
        for p in qs[:limite]
    ]
    resultado = {"total_encontrados": total, "mostrando": len(productos), "productos": productos}
    if total == 0:
        resultado["sugerencia"] = (
            "Sin resultados. El catálogo usa abreviaturas (PAST, FR, JGO, DEL, TRAS, CIL). "
            "Prueba con menos palabras o con su abreviatura."
        )
    return resultado


def buscar_producto(texto: str, limite: int = 10, solo_favoritos: bool = False) -> dict:
    """Búsqueda híbrida (palabras + significado) en los productos activos de Odoo."""
    from modules.ia import rag  # import diferido: carga numpy y el índice solo cuando se usa

    texto = str(texto).strip()
    if not texto:
        return {"error": "Indica qué producto buscar."}
    # Piso de resultados: productos casi iguales (BOLSA 1 KG / 5 KG / 10 KG) empatan en puntaje y su
    # orden es casi azar. Si el modelo pide 1-2 resultados, puede ver solo la de 5 kg y concluir
    # "no tenemos de 1 kg" (pasó el 19-nov). Mostrar algunos más cuesta poco y evita ese error.
    limite = max(MIN_RESULTADOS_BUSQUEDA, min(int(limite), MAX_RESULTADOS))

    r = rag.catalogo().buscar(texto, limite, solo_favoritos=bool(solo_favoritos))
    resultado = {
        "modo": r.modo,
        "mejor_similitud": round(r.mejor_similitud, 3),
        "productos": [
            {
                "id": c.id,
                "nombre": c.nombre,
                "codigo": c.codigo,
                "precio_venta": c.precio,
                "similitud": c.similitud,
                "palabras_coinciden": c.palabras_coinciden,
                "favorito": c.favorito,
            }
            for c in r.candidatos
        ],
    }
    if not r.candidatos:
        resultado["aviso"] = "Sin resultados. Reformula con otras palabras o con el nombre técnico."
    elif r.relevancia_baja:
        resultado["aviso"] = (
            "Relevancia baja: es probable que lo buscado no exista con ese nombre en el catálogo. "
            "Reformula con sinónimos o el nombre técnico (ej. 'colchoneta' -> 'espuma') y vuelve a buscar. "
            "Si sigue baja, informa que no se encontró. No presentes estos productos como si fueran lo pedido."
        )
    return resultado


def consultar_stock(ids: list[int]) -> dict:
    """Stock actual consultado en vivo a Odoo."""
    # Import diferido: así la búsqueda local funciona aunque no haya conexión a Odoo.
    from modules.servidor.odoo import OdooConnectionError, OdooService

    ids = [int(i) for i in ids][:MAX_RESULTADOS]
    if not ids:
        return {"error": "Indica al menos un id de producto (usa buscar_producto para obtenerlo)."}
    try:
        filas = OdooService.get_productos_por_ids(ids)
    except OdooConnectionError as exc:
        return {"error": f"No se pudo conectar con Odoo: {exc}"}

    por_id = {f["id"]: f for f in filas}
    return {
        "fuente": "Odoo en vivo",
        "productos": [
            {"id": i, "nombre": por_id[i]["name"], "stock": por_id[i]["qty_available"]}
            for i in ids if i in por_id
        ],
        "no_encontrados": [i for i in ids if i not in por_id],
        "nota": "Un stock negativo indica descuadre de inventario: reportarlo como 0 disponible y mencionarlo.",
    }


def ventas_producto(producto_id: int, meses: int = 6) -> dict:
    """Unidades vendidas por mes, desde la copia local de movimientos.

    El monto no se entrega: en la copia local casi siempre viene en 0 y el
    modelo lo reportaría como si no hubiera ventas.
    """
    meses = max(1, min(int(meses), 24))
    ultimo_mov = (
        MovimientoProductoMes.objects.order_by("-anio", "-mes").values_list("anio", "mes").first()
    )
    if not ultimo_mov:
        return {"error": "No hay datos de ventas en la copia local."}

    anio, mes = ultimo_mov
    periodo = []
    for _ in range(meses):
        periodo.append((anio, mes))
        mes -= 1
        if mes == 0:
            anio, mes = anio - 1, 12
    periodo.reverse()

    filas = {
        (m.anio, m.mes): m
        for m in MovimientoProductoMes.objects.filter(producto_id=int(producto_id)).filter(
            Q(*[Q(anio=a, mes=m) for a, m in periodo], _connector=Q.OR)
        )
    }
    detalle = []
    for a, m in periodo:
        f = filas.get((a, m))
        detalle.append({
            "mes": f"{a}-{m:02d}",
            "unidades": f.cantidad_vendida if f else 0,
        })
    return {
        "producto_id": int(producto_id),
        "fuente": "copia local (MovimientoProductoMes)",
        "datos_hasta": f"{ultimo_mov[0]}-{ultimo_mov[1]:02d}",
        "meses": detalle,
        "total_unidades": sum(d["unidades"] for d in detalle),
        "nota": "Solo unidades. Para montos multiplica por el precio actual solo si el usuario lo pide, aclarando que es una estimación.",
    }


# ── Compras (Odoo en vivo) ───────────────────────────────────────────────────
# Lección 4: el modelo NO escribe consultas. Elige parámetros (producto, proveedor,
# fechas, agrupación) y este código arma el filtro de Odoo. Solo search_read/read_group:
# leer es lo único que estas funciones saben hacer.

ESTADOS_CONFIRMADOS = ["purchase", "done"]   # órdenes de compra confirmadas (no borradores ni canceladas)
_AGRUPACIONES = {"producto": "product_id", "proveedor": "partner_id", "mes": "date_order:month"}


def _odoo(modelo: str, metodo: str, *args, **kwargs):
    """Llamada de solo lectura a Odoo usando la conexión existente del sistema."""
    from modules.servidor.odoo import db, models, password, uid

    return models.execute_kw(db, uid, password, modelo, metodo, list(args), kwargs)


def _codigo(nombre_odoo: str) -> str:
    """'[DOS-483305] MARTILLO …' -> 'DOS-483305' (Odoo antepone el código entre corchetes)."""
    import re

    m = re.match(r"\[([^\]]+)\]", nombre_odoo or "")
    return m.group(1) if m else ""


def _singular(palabra: str) -> str:
    """'martillos' -> 'martillo', 'alicates' -> 'alicate'. El catálogo nombra en singular."""
    return palabra[:-1] if len(palabra) > 4 and palabra.lower().endswith("s") else palabra


def _fecha_valida(texto: str | None) -> str | None:
    from datetime import date

    if not texto:
        return None
    date.fromisoformat(texto)          # lanza ValueError si no es AAAA-MM-DD
    return texto


def consultar_compras(
    producto: str | None = None,
    proveedor: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
    agrupar_por: str | None = None,
    limite: int = 10,
) -> dict:
    """Compras confirmadas en Odoo, filtradas y opcionalmente agrupadas."""
    from modules.servidor.odoo import OdooConnectionError

    try:
        desde, hasta = _fecha_valida(desde), _fecha_valida(hasta)
    except ValueError:
        return {"error": "Las fechas deben tener formato AAAA-MM-DD (ej. 2026-01-01)."}
    if agrupar_por and agrupar_por not in _AGRUPACIONES:
        return {"error": f"agrupar_por debe ser uno de: {', '.join(_AGRUPACIONES)}."}
    limite = max(1, min(int(limite), MAX_RESULTADOS))

    filtro = [("order_id.state", "in", ESTADOS_CONFIRMADOS)] + _filtro_producto(producto, "product_id")
    if proveedor:
        filtro.append(("partner_id.name", "ilike", proveedor))
    if desde:
        filtro.append(("date_order", ">=", f"{desde} 00:00:00"))
    if hasta:
        filtro.append(("date_order", "<=", f"{hasta} 23:59:59"))

    aplicados = {k: v for k, v in
                 {"producto": producto, "proveedor": proveedor, "desde": desde, "hasta": hasta}.items() if v}
    try:
        total = _odoo("purchase.order.line", "read_group", filtro, ["product_qty:sum", "price_subtotal:sum"], [])
        resumen = {
            "lineas_de_compra": total[0].get("__count", 0) if total else 0,
            "unidades": total[0].get("product_qty") or 0 if total else 0,
            "monto_neto": round(total[0].get("price_subtotal") or 0) if total else 0,
        }
        if agrupar_por:
            campo = _AGRUPACIONES[agrupar_por]
            grupos = _odoo(
                "purchase.order.line", "read_group", filtro, ["product_qty:sum", "price_subtotal:sum"], [campo],
                orderby="product_qty desc" if agrupar_por != "mes" else "date_order asc", limit=limite, lazy=False,
            )
            filas = [
                {
                    agrupar_por: (g[campo][1] if isinstance(g[campo], list) else g[campo]),
                    "unidades": g.get("product_qty") or 0,
                    "monto_neto": round(g.get("price_subtotal") or 0),
                    "lineas": g.get("__count", 0),
                }
                for g in grupos
            ]
        else:
            lineas = _odoo(
                "purchase.order.line", "search_read", filtro,
                fields=["date_order", "partner_id", "product_id", "product_qty", "price_unit", "order_id"],
                order="date_order desc", limit=limite,
            )
            filas = [
                {
                    "fecha": (l["date_order"] or "")[:10],
                    "proveedor": l["partner_id"][1] if l["partner_id"] else "",
                    "codigo": _codigo(l["product_id"][1]) if l["product_id"] else "",
                    "producto": l["product_id"][1] if l["product_id"] else "",
                    "cantidad": l["product_qty"],
                    "precio_unitario": round(l["price_unit"] or 0),
                    "orden": l["order_id"][1] if l["order_id"] else "",
                }
                for l in lineas
            ]
        # Totales por proveedor ya calculados: en la demo del 12-nov el modelo sumó a mano las
        # últimas compras (limitadas a 10 filas) y dio 9 unidades donde eran 10.
        por_proveedor = []
        if producto and agrupar_por != "proveedor" and resumen["lineas_de_compra"]:
            por_proveedor = [
                {"proveedor": g["partner_id"][1], "unidades": g.get("product_qty") or 0,
                 "monto_neto": round(g.get("price_subtotal") or 0), "lineas": g.get("__count", 0)}
                for g in _odoo("purchase.order.line", "read_group", filtro, ["product_qty:sum", "price_subtotal:sum"],
                               ["partner_id"], orderby="product_qty desc", limit=8, lazy=False)
                if g.get("partner_id")
            ]
    except OdooConnectionError as exc:
        return {"error": f"No se pudo conectar con Odoo: {exc}"}

    resultado = {
        "fuente": "Odoo en vivo (solo órdenes de compra confirmadas)",
        "filtros": aplicados,
        "resumen": resumen,
        ("grupos" if agrupar_por else "ultimas_compras"): filas,
    }
    if por_proveedor:
        resultado["totales_por_proveedor"] = por_proveedor
    if producto and not proveedor:
        try:
            otros = _otros_proveedores(producto, filtro)
        except OdooConnectionError:
            otros = []
        if otros:
            resultado["otros_proveedores_registrados"] = otros
            resultado["aviso_otros"] = (
                "Estos proveedores figuran en Odoo como proveedores de productos que coinciden, pero NO "
                "tienen compras confirmadas con estos filtros. Nómbralos (nombre del proveedor) en un párrafo "
                "aparte, aclarando que no hay compras confirmadas y si hay cotizaciones sin confirmar."
            )
    if resumen["lineas_de_compra"] == 0:
        resultado["aviso"] = "No hay compras con esos filtros. Prueba con otra palabra del producto o sin proveedor/fechas."
    return resultado


def _filtro_producto(producto: str | None, campo: str) -> list:
    """Cada palabra (en singular) debe estar en el nombre o en el código del producto."""
    filtro = []
    for palabra in str(producto or "").split():
        p = _singular(palabra)
        filtro += ["|", (f"{campo}.name", "ilike", p), (f"{campo}.default_code", "ilike", p)]
    return filtro


def _otros_proveedores(producto: str, filtro_compras: list) -> list[dict]:
    """Proveedores registrados para el producto (ficha "Compra" en Odoo) que no aparecen en las compras.

    Caso real (12-nov, Janina): "¿a quién le hemos comprado engrapadoras?". Las compras confirmadas
    eran de ECOSA y DOS ESTRELLAS, pero en Odoo UYUSTOOLS también figura como proveedor de
    engrapadoras (solo con una cotización en borrador). La respuesta era correcta pero incompleta
    para quien conoce el catálogo: ahora se informa aparte, sin mezclarlo con las compras.
    """
    con_compras = {
        g["partner_id"][0]
        for g in _odoo("purchase.order.line", "read_group", filtro_compras, ["product_qty:sum"], ["partner_id"], lazy=False)
        if g.get("partner_id")
    }
    registrados = _odoo(
        "product.supplierinfo", "search_read", _filtro_producto(producto, "product_tmpl_id"),
        fields=["partner_id", "product_tmpl_id", "price"], limit=50,
    )
    otros: dict[int, dict] = {}
    for s in registrados:
        if not s["partner_id"] or s["partner_id"][0] in con_compras:
            continue
        o = otros.setdefault(s["partner_id"][0], {"proveedor": s["partner_id"][1], "productos": []})
        if len(o["productos"]) < 5:
            o["productos"].append({"codigo": _codigo(s["product_tmpl_id"][1]), "producto": s["product_tmpl_id"][1],
                                   "precio_proveedor": round(s["price"] or 0)})
    for pid, o in otros.items():
        borradores = _odoo(
            "purchase.order.line", "search_read",
            [("partner_id", "=", pid), ("order_id.state", "in", ["draft", "sent", "to approve"])]
            + _filtro_producto(producto, "product_id"),
            fields=["date_order"], order="date_order desc", limit=20,
        )
        o["cotizaciones_sin_confirmar"] = len(borradores)
        if borradores:
            o["ultima_cotizacion"] = (borradores[0]["date_order"] or "")[:10]
    return list(otros.values())[:8]


def sugerencias_compra(proveedor: str | None = None, limite: int = 15) -> dict:
    """Qué comprar según el criterio que La Loba YA usa: el reporte "Bajo stock".

    Decisión de diseño: no se inventa un criterio nuevo ni se usa el reabastecimiento
    de Odoo (medido el 9-nov: 32 de sus 35 sugerencias eran stock negativo, no compras
    reales). Se reutiliza la misma función del reporte semanal, para que el asistente
    y el reporte nunca se contradigan. Regla: productos favoritos; CRITICO si el stock
    está bajo el mínimo, SOLICITAR si está hasta un 20 % sobre el mínimo; se sugiere
    pedir hasta el máximo.
    """
    from modules.servidor.reportes.bajo_stock import obtener_datos_bajo_stock

    limite = max(1, min(int(limite), MAX_RESULTADOS))
    por_proveedor = obtener_datos_bajo_stock()
    if proveedor:
        buscado = proveedor.lower()
        por_proveedor = {p: v for p, v in por_proveedor.items() if buscado in (p or "").lower()}

    ids = [f["id"] for filas in por_proveedor.values() for f in filas]
    codigos = dict(OdooProducto.objects.filter(id__in=ids).values_list("id", "default_code"))

    resumen, productos, con_negativo = [], [], 0
    for nombre, filas in por_proveedor.items():
        resumen.append({
            "proveedor": nombre,
            "productos": len(filas),
            "criticos": sum(1 for f in filas if f["riesgo"] == "CRITICO"),
            "solicitar": sum(1 for f in filas if f["riesgo"] == "SOLICITAR"),
            "stock_negativo": sum(1 for f in filas if (f["stock"] or 0) < 0),
            "monto_estimado": round(sum(f["subtotal"] or 0 for f in filas)),
        })
        for f in filas:
            negativo = (f["stock"] or 0) < 0
            con_negativo += negativo
            productos.append({
                "proveedor": nombre,
                "id": f["id"],
                "codigo": codigos.get(f["id"]) or "",
                "producto": f["producto"],
                "riesgo": f["riesgo"],
                "stock": f["stock"],
                "minimo": f["stock_min"],
                "maximo": f["stock_max"],
                "sugerido_pedir": f["cantidad_sugerida"],
                "precio_compra": round(f["precio_compra"] or 0),
                "stock_negativo": negativo,
            })
    resumen.sort(key=lambda r: (-r["criticos"], -r["monto_estimado"]))
    productos.sort(key=lambda p: (p["riesgo"] != "CRITICO", p["proveedor"]))

    resultado = {
        "fuente": "Reporte 'Bajo stock' del sistema (copia local de Odoo: favoritos, mínimos y máximos)",
        "criterio": "CRÍTICO = stock bajo el mínimo; SOLICITAR = hasta 20 % sobre el mínimo; se sugiere pedir hasta el máximo.",
        "total_productos": len(productos),
        "total_proveedores": len(resumen),
        "por_proveedor": resumen[:limite],
        "productos": productos[:limite],
    }
    if len(productos) > limite:
        resultado["nota"] = f"Se muestran {limite} de {len(productos)} productos (primero los críticos)."
    if not productos:
        resultado["aviso"] = "Ningún producto favorito está bajo su mínimo."
    if con_negativo:
        resultado["aviso_stock_negativo"] = (
            f"{con_negativo} productos tienen stock negativo (descuadre de inventario): la cantidad "
            "sugerida puede estar inflada. Indícalo al responder."
        )
    return resultado

# ── Favoritos ────────────────────────────────────────────────────────────────

_ESTADOS_FAVORITOS = ("todos", "sin_stock", "bajo_minimo")


def consultar_favoritos(estado: str = "todos", texto: str | None = None,
                        proveedor: str | None = None, limite: int = 15) -> dict:
    """Productos favoritos (los que La Loba sigue de cerca), con su stock, mínimo y proveedor.

    Usa la misma copia local que el reporte "Bajo stock", para que ambos coincidan.
    """
    from django.db import connection

    estado = (estado or "todos").strip().lower()
    if estado not in _ESTADOS_FAVORITOS:
        return {"error": f"estado debe ser uno de: {', '.join(_ESTADOS_FAVORITOS)}."}
    limite = max(1, min(int(limite), MAX_RESULTADOS))

    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT p.id, p.name, p.default_code, p.qty_available, p.list_price,
                   so.product_min_qty, so.product_max_qty, t.partner
            FROM servidor_odooproducto p
            LEFT JOIN servidor_odooruta so ON so.product = '[' || p.default_code || '] ' || p.name
            LEFT JOIN servidor_odootarifa t ON t.product_tmpl_id = p.id
            WHERE p.favorito = 1 AND p.activo = 1
            ORDER BY p.id, t.sequence
        """)
        filas = cursor.fetchall()

    favoritos, vistos = [], set()
    for pid, nombre, codigo, stock, precio, minimo, maximo, prov in filas:
        if pid in vistos:          # un producto puede tener varios proveedores: queda el principal
            continue
        vistos.add(pid)
        stock = stock or 0
        if stock <= 0:
            situacion = "SIN STOCK"
        elif minimo and stock < minimo:
            situacion = "BAJO MÍNIMO"
        else:
            situacion = "OK"
        favoritos.append({
            "id": pid, "codigo": codigo or "", "producto": nombre, "stock": stock,
            "minimo": minimo or 0, "maximo": maximo or 0, "proveedor": prov or "Sin proveedor",
            "precio_venta": round(precio or 0), "situacion": situacion,
        })

    resumen = {
        "favoritos": len(favoritos),
        "sin_stock": sum(1 for f in favoritos if f["situacion"] == "SIN STOCK"),
        "bajo_minimo": sum(1 for f in favoritos if f["situacion"] == "BAJO MÍNIMO"),
    }
    lista = favoritos
    if estado == "sin_stock":
        lista = [f for f in lista if f["situacion"] == "SIN STOCK"]
    elif estado == "bajo_minimo":
        lista = [f for f in lista if f["situacion"] == "BAJO MÍNIMO"]
    if texto:
        palabras = [_singular(w).upper() for w in str(texto).split()]
        lista = [f for f in lista if all(w in f"{f['producto']} {f['codigo']}".upper() for w in palabras)]
    if proveedor:
        lista = [f for f in lista if proveedor.lower() in f["proveedor"].lower()]
    orden = {"SIN STOCK": 0, "BAJO MÍNIMO": 1, "OK": 2}
    lista.sort(key=lambda f: (orden[f["situacion"]], f["stock"]))

    resultado = {
        "fuente": "Copia local de Odoo (la misma del reporte 'Bajo stock'). Para el stock al minuto usa consultar_stock.",
        "resumen_todos_los_favoritos": resumen,
        "filtro": {"estado": estado, "texto": texto, "proveedor": proveedor},
        "encontrados": len(lista),
        "productos": lista[:limite],
    }
    if len(lista) > limite:
        resultado["nota"] = f"Se muestran {limite} de {len(lista)} (primero sin stock, luego bajo mínimo)."
    negativos = sum(1 for f in lista if f["stock"] < 0)
    if negativos:
        resultado["aviso_stock_negativo"] = f"{negativos} tienen stock negativo (descuadre de inventario)."
    return resultado


# ── Lo que ve el modelo ──────────────────────────────────────────────────────

ESQUEMAS = [
    {
        "type": "function",
        "function": {
            "name": "buscar_producto",
            "description": (
                "Busca productos de la ferretería combinando búsqueda por significado y por palabras. "
                "Acepta lenguaje natural ('espuma delgada densidad 15', 'pastillas freno hilux') o códigos. "
                "Devuelve candidatos con id, nombre, código, precio de venta y similitud (0 a 1). "
                "Úsala primero para obtener el id de un producto. Los candidatos son posibilidades, no "
                "certezas: elige tú cuál corresponde comparando nombres y medidas. En el catálogo la "
                "densidad de las espumas se abrevia D (ej. 'ESPUMA 2 CM D 15'). Si llega un aviso de "
                "relevancia baja, reformula la búsqueda antes de responder. Cada resultado indica si el "
                "producto es favorito."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "texto": {"type": "string", "description": "Lo que se busca, en palabras simples o un código."},
                    "solo_favoritos": {"type": "boolean", "description": "true para buscar solo entre los productos favoritos.", "default": False},
                    "limite": {"type": "integer", "description": "Máximo de resultados (1-15).", "default": 10},
                },
                "required": ["texto"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_stock",
            "description": "Consulta en vivo en Odoo el stock actual de uno o más productos por su id.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ids": {"type": "array", "items": {"type": "integer"}, "description": "Ids de producto (máx. 15)."},
                },
                "required": ["ids"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ventas_producto",
            "description": (
                "Unidades vendidas por mes de un producto, para los últimos N meses con datos "
                "disponibles. Indica hasta qué mes hay datos. No incluye montos en pesos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "producto_id": {"type": "integer", "description": "Id del producto."},
                    "meses": {"type": "integer", "description": "Cantidad de meses hacia atrás (1-24).", "default": 6},
                },
                "required": ["producto_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_compras",
            "description": (
                "Compras confirmadas en Odoo (datos en vivo). Sirve para preguntas como: ¿a qué proveedor le "
                "compramos X la última vez?, ¿cuánto compramos de X este año?, ¿qué le compramos a tal "
                "proveedor? Sin agrupar devuelve las últimas compras (fecha, proveedor, producto, cantidad, "
                "precio). Con agrupar_por devuelve totales por producto, proveedor o mes. Siempre trae un "
                "resumen con unidades y monto neto totales. Usa la palabra del producto en singular, como en "
                "el catálogo (ej. 'martillo', 'alicate')."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "producto": {"type": "string", "description": "Palabras del nombre o código del producto (opcional)."},
                    "proveedor": {"type": "string", "description": "Parte del nombre del proveedor (opcional)."},
                    "desde": {"type": "string", "description": "Fecha inicial AAAA-MM-DD. SOLO si la pregunta menciona un período ('este año' = 1 de enero del año actual). Si no menciona período, NO lo envíes: se buscan todas las compras."},
                    "hasta": {"type": "string", "description": "Fecha final AAAA-MM-DD. SOLO si la pregunta menciona un período."},
                    "agrupar_por": {"type": "string", "enum": ["producto", "proveedor", "mes"], "description": "Opcional: totales agrupados."},
                    "limite": {"type": "integer", "description": "Máximo de filas (1-15).", "default": 10},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "consultar_favoritos",
            "description": (
                "Productos favoritos: los que La Loba sigue de cerca para no quedarse sin stock. "
                "Devuelve un resumen (cuántos favoritos hay, cuántos sin stock y cuántos bajo el mínimo) "
                "y la lista filtrada con código, stock, mínimo, proveedor y situación (SIN STOCK, BAJO "
                "MÍNIMO, OK). Úsala para preguntas como ¿qué favoritos están sin stock?, ¿cuáles están "
                "bajo el mínimo?, ¿qué favoritos tenemos de tal proveedor o de tal tipo de producto?"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "estado": {"type": "string", "enum": ["todos", "sin_stock", "bajo_minimo"], "default": "todos"},
                    "texto": {"type": "string", "description": "Palabras del nombre o código (opcional)."},
                    "proveedor": {"type": "string", "description": "Parte del nombre del proveedor (opcional)."},
                    "limite": {"type": "integer", "description": "Máximo de productos (1-15).", "default": 15},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "sugerencias_compra",
            "description": (
                "Qué conviene comprar, con el mismo criterio del reporte semanal 'Bajo stock' de La Loba: "
                "productos favoritos bajo su mínimo (CRÍTICO) o cerca de él (SOLICITAR), cantidad sugerida "
                "hasta el máximo, agrupados por proveedor con monto estimado. Úsala para ¿qué debería "
                "comprar?, ¿qué falta reponer?, ¿qué le pido a tal proveedor? No inventes otro criterio: "
                "presenta lo que entrega la herramienta, empezando por el resumen por proveedor y los críticos."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "proveedor": {"type": "string", "description": "Filtrar por proveedor (opcional)."},
                    "limite": {"type": "integer", "description": "Máximo de productos (1-15).", "default": 15},
                },
            },
        },
    },
]

_FUNCIONES = {
    "buscar_producto": buscar_producto,
    "consultar_stock": consultar_stock,
    "ventas_producto": ventas_producto,
    "consultar_compras": consultar_compras,
    "sugerencias_compra": sugerencias_compra,
    "consultar_favoritos": consultar_favoritos,
}


def ejecutar(nombre: str, argumentos_json: str) -> str:
    """Ejecuta la herramienta pedida por el modelo y devuelve el resultado como texto JSON.

    Nunca lanza excepciones: cualquier error vuelve al modelo como {"error": ...}
    para que pueda corregirse (otra búsqueda, otro id) en vez de romper el loop.
    """
    funcion = _FUNCIONES.get(nombre)
    if funcion is None:
        resultado = {"error": f"La herramienta '{nombre}' no existe."}
    else:
        try:
            argumentos = json.loads(argumentos_json or "{}")
            resultado = funcion(**argumentos)
        except json.JSONDecodeError:
            resultado = {"error": "Los argumentos no son JSON válido."}
        except TypeError as exc:
            resultado = {"error": f"Argumentos inválidos para {nombre}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - el error se devuelve al modelo
            resultado = {"error": f"Falló {nombre}: {exc}"}

    texto = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(texto) > MAX_CARACTERES:
        texto = texto[:MAX_CARACTERES] + ' ... [resultado recortado]'
    return texto
