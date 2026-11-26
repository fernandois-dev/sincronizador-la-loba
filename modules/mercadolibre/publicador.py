"""
Arma la publicación de Mercado Libre de un ProductoML y la valida o publica.

Simular = subir las fotos a Mercado Libre (quedan sueltas, no se ven en ningún lado)
y llamar a POST /items/validate, que revisa la publicación completa SIN crearla.
"""
from __future__ import annotations

import io
import json
import os
import re
from datetime import datetime

from logger_config import get_logger
from modules.mercadolibre import catalogo
from modules.mercadolibre.catalogo import config_ml
from modules.mercadolibre.client import MercadoLibreClient, MercadoLibreError

logger = get_logger(__name__)

MAX_LADO = 1920                 # Mercado Libre reduce todo lo que pase de 1920 px
MAX_BYTES = 10 * 1024 * 1024    # y rechaza archivos de más de 10 MB
CARPETA_LOG = os.path.join("logs", "mercadolibre")


# ── fotos ──────────────────────────────────────────────────────────────────────
def fotos_de(ref: str, carpeta_id: str) -> list[dict]:
    """Archivos REF-1, REF-2… de la carpeta de Drive, ordenados por número."""
    from modules.servidor.google_sheet import drive_service

    if not (ref and carpeta_id):
        return []
    r = drive_service.files().list(
        q=f"'{carpeta_id}' in parents and trashed = false and name contains '{ref}'",
        fields="files(id, name, size, modifiedTime)", pageSize=100,
        supportsAllDrives=True, includeItemsFromAllDrives=True,
    ).execute()
    fotos = []
    for f in r.get("files", []):
        m = re.match(rf"^{re.escape(ref)}-(\d+)\.(jpe?g|png)$", f["name"].strip(), flags=re.I)
        if m:
            fotos.append({**f, "orden": int(m.group(1))})
    return sorted(fotos, key=lambda f: f["orden"])


def preparar_imagen(data: bytes) -> bytes:
    """Corrige la rotación del celular, pasa a RGB y reduce a 1920 px / 10 MB si hace falta."""
    from PIL import Image, ImageOps

    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode != "RGB":
        img = img.convert("RGB")
    if max(img.size) > MAX_LADO:
        img.thumbnail((MAX_LADO, MAX_LADO))
    calidad = 90
    while True:
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=calidad, optimize=True)
        if out.tell() <= MAX_BYTES or calidad <= 50:
            return out.getvalue()
        calidad -= 10


def miniaturas(ref: str, lado: int = 220) -> list[str]:
    """Fotos REF-1, REF-2… de Drive como JPEG pequeños en base64 (para la vista previa)."""
    import base64
    from PIL import Image, ImageOps
    from modules.servidor.google_sheet import drive_service

    salida = []
    for f in fotos_de(ref, config_ml()["carpeta_fotos_id"]):
        data = drive_service.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        img.thumbnail((lado, lado))
        out = io.BytesIO()
        img.save(out, format="JPEG", quality=80)
        salida.append(base64.b64encode(out.getvalue()).decode())
    return salida


def subir_fotos(ml: MercadoLibreClient, fotos: list[dict]) -> list[str]:
    from modules.servidor.google_sheet import drive_service

    ids = []
    for f in fotos:
        original = drive_service.files().get_media(fileId=f["id"], supportsAllDrives=True).execute()
        jpg = preparar_imagen(original)
        r = ml.post("/pictures/items/upload", files={"file": (f["name"].rsplit(".", 1)[0] + ".jpg", jpg, "image/jpeg")})
        ids.append(r["id"])
        logger.info("Foto %s subida a ML: %s (%d KB → %d KB)", f["name"], r["id"], len(original) // 1024, len(jpg) // 1024)
    return ids


# ── atributos ──────────────────────────────────────────────────────────────────
def _gtin_valido(codigo: str) -> bool:
    if not codigo or not codigo.isdigit() or len(codigo) not in (8, 12, 13, 14):
        return False
    digitos = [int(c) for c in codigo]
    suma = sum(d * (3 if i % 2 == 0 else 1) for i, d in enumerate(reversed(digitos[:-1])))
    return (10 - suma % 10) % 10 == digitos[-1]


def normalizar_nombre(texto: str) -> str:
    """'Material del relleno' / 'MATERIAL DEL RELLENO' / 'material_del_relleno' → 'MATERIAL DEL RELLENO'."""
    import unicodedata
    t = unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode()
    return " ".join(t.replace("_", " ").upper().split())


def atributos_desde_planilla(valores: dict, atributos_cat: list[dict]) -> tuple[list[dict], list[str]]:
    """
    Traduce las columnas "<DATO> ML" de la planilla (p. ej. FORMA ML = Rectangular, LARGO ML = 190)
    a atributos de Mercado Libre de la categoría. El nombre de la columna se compara con el
    nombre del dato en ML (sin tildes ni mayúsculas) o con su ID (CUSHION_SHAPE…).
    Devuelve (atributos, avisos). Un valor que no está en las opciones de ML se informa y no se envía.
    """
    por_nombre = {}
    for a in atributos_cat:
        por_nombre.setdefault(normalizar_nombre(a.get("name")), a)
        por_nombre.setdefault(normalizar_nombre(a["id"]), a)
    atributos, avisos = [], []
    for columna, valor in (valores or {}).items():
        valor = str(valor).strip()
        if not valor:
            continue
        a = por_nombre.get(normalizar_nombre(columna))
        if not a:
            avisos.append(f"La columna '{columna} ML' no es un dato de esta categoría: se ignora.")
            continue
        tipo, opciones = a.get("value_type"), a.get("values") or []
        if tipo == "number_unit":
            m = re.match(r"^\s*(\d+(?:[.,]\d+)?)\s*([^\d\s].*)?$", valor)
            if not m:
                avisos.append(f"{a['name']}: '{valor}' no es una medida válida (ej. 190 o 190 cm).")
                continue
            numero = float(m.group(1).replace(",", "."))
            unidades = [u["id"] for u in a.get("allowed_units") or []]
            unidad = (m.group(2) or "").strip() or (unidades[0] if unidades else "")
            atributos.append({"id": a["id"], "value_name": f"{numero:g} {unidad}".strip()})
        elif tipo == "number":
            try:
                atributos.append({"id": a["id"], "value_name": f"{float(valor.replace(',', '.')):g}"})
            except ValueError:
                avisos.append(f"{a['name']}: '{valor}' no es un número.")
        elif opciones:
            buscado = normalizar_nombre({"SI": "Sí"}.get(normalizar_nombre(valor), valor))
            opcion = next((o for o in opciones if normalizar_nombre(o.get("name")) == buscado), None)
            if opcion:
                atributos.append({"id": a["id"], "value_id": opcion["id"]})
            elif tipo == "string":  # admite texto libre además de la lista
                atributos.append({"id": a["id"], "value_name": valor})
            else:
                avisos.append(f"{a['name']}: '{valor}' no es una opción de Mercado Libre "
                              f"({', '.join(o['name'] for o in opciones[:8])}…).")
        else:
            atributos.append({"id": a["id"], "value_name": valor})
    return atributos, avisos


def atributos_categoria(categoria_id: str, ml: MercadoLibreClient | None = None) -> list[dict]:
    """Datos que pide la categoría en Mercado Libre (/categories/{id}/attributes)."""
    return (ml or MercadoLibreClient()).get(f"/categories/{categoria_id}/attributes", auth=False) or []


def _requerido(a: dict) -> bool:
    tags = a.get("tags") or {}
    return bool(tags.get("required") or tags.get("catalog_required")) and not tags.get("read_only")


def armar_item(p, picture_ids: list[str], atributos_cat: list[dict], cfg: dict,
               user_products: bool = True) -> tuple[dict, list[str], list[str]]:
    """
    Publicación de ML para el producto p (ProductoML). Devuelve (item, faltantes):
    faltantes = atributos obligatorios de la categoría que no sabemos completar.

    Cuentas en el modelo "User Products" (tag user_product_seller): no se envía
    `title`; se envía `family_name` (nombre genérico del producto) y Mercado Libre
    arma el título con ese nombre más los atributos. TITULO ML de la planilla se
    usa como family_name.
    """
    por_id = {a["id"]: a for a in atributos_cat}
    atributos = [{"id": "BRAND", "value_name": p.marca or "Genérica"},
                 {"id": "SELLER_SKU", "value_name": p.ref_interna}]
    if _gtin_valido(p.barcode):
        atributos.append({"id": "GTIN", "value_name": p.barcode})
    elif "EMPTY_GTIN_REASON" in por_id:
        valores = por_id["EMPTY_GTIN_REASON"].get("values") or []
        motivo = next((v for v in valores if "no tiene" in v.get("name", "").lower()), valores[0] if valores else None)
        if motivo:
            atributos.append({"id": "EMPTY_GTIN_REASON", "value_id": motivo["id"]})
    if "MODEL" in por_id:
        atributos.append({"id": "MODEL", "value_name": p.ref_interna})
    if p.peso_gr and "SELLER_PACKAGE_WEIGHT" in por_id:
        atributos.append({"id": "SELLER_PACKAGE_WEIGHT", "value_name": f"{p.peso_gr} g"})
    medidas = (getattr(p, "medidas_paquete", "") or "").split("x")
    if len(medidas) == 3:
        for attr_id, valor in zip(("SELLER_PACKAGE_LENGTH", "SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_HEIGHT"), medidas):
            if attr_id in por_id:
                atributos.append({"id": attr_id, "value_name": f"{valor} cm"})

    # datos de la categoría desde las columnas "<DATO> ML" de la planilla (la planilla manda, salvo el SKU)
    import json
    try:
        valores = json.loads(getattr(p, "atributos_ml", "") or "{}")
    except ValueError:
        valores = {}
    de_planilla, avisos = atributos_desde_planilla(valores, atributos_cat)
    ids_planilla = {x["id"] for x in de_planilla if x["id"] != "SELLER_SKU"}
    atributos = [a for a in atributos if a["id"] not in ids_planilla] + [x for x in de_planilla if x["id"] != "SELLER_SKU"]

    puestos = {a["id"] for a in atributos}
    faltantes = [a.get("name", a["id"]) for a in atributos_cat
                 if _requerido(a) and a["id"] not in puestos and a["id"] not in ("GTIN", "EMPTY_GTIN_REASON")]

    cantidad = max((p.stock or 0) - cfg["stock_reserva"], 0)
    item = {
        ("family_name" if user_products else "title"): p.titulo,
        "category_id": p.categoria_id,
        "price": p.precio_ml,
        "currency_id": "CLP",
        "available_quantity": cantidad,
        "buying_mode": "buy_it_now",
        "condition": "new",
        "listing_type_id": cfg["tipo_publicacion"],
        "pictures": [{"id": i} for i in picture_ids],
        "attributes": atributos,
        "shipping": {"mode": "me2", "local_pick_up": False, "free_shipping": False},
    }
    return item, faltantes, avisos


# ── simulación ─────────────────────────────────────────────────────────────────
# Traducción de las advertencias de Mercado Libre más comunes.
ADVERTENCIAS = {
    "item.shipping.mandatory_free_shipping":
        "Envío gratis obligatorio (el precio supera el mínimo de Chile): el costo del envío lo pagas tú.",
    "shipping.lost_me1_by_user": None,  # aviso interno de ML sobre el modo de envío antiguo: se ignora
}


# Advertencias de ML que en la práctica impiden vender bien: se tratan como error.
# Sin Mercado Envíos el precio incluiría un envío que no se ofrece al comprador.
ADVERTENCIAS_BLOQUEANTES = {
    "shipping.lost_me2_by_catalog":
        "Mercado Libre no permite Mercado Envíos en esta categoría para la cuenta: elige otra categoría.",
    "shipping.lost_me2_by_intersected_logistics":
        "Mercado Libre no permite Mercado Envíos para esta publicación (categoría o logística): elige otra categoría.",
}


def _causas(err: MercadoLibreError) -> tuple[list[str], list[str]]:
    """(errores, advertencias) de una respuesta de error de Mercado Libre."""
    d = err.detalle if isinstance(err.detalle, dict) else {}
    errores, advertencias = [], []
    causas = [c for c in d.get("cause", []) or [] if isinstance(c, dict)]
    for c in causas:
        codigo = c.get("code", "")
        if codigo in ADVERTENCIAS_BLOQUEANTES or codigo.startswith("shipping.lost_me2"):
            errores.append(ADVERTENCIAS_BLOQUEANTES.get(codigo, c.get("message") or codigo))
            continue
        texto = ADVERTENCIAS.get(codigo, c.get("message") or codigo)
        if c.get("type") == "warning":
            if texto:
                advertencias.append(texto)
        else:
            errores.append(texto or c.get("message", ""))
    if not causas:  # ML no dijo por qué: el mensaje general es el error
        errores.append(d.get("message") or str(err))
    return errores, advertencias


_ATTR_PAQUETE = ("SELLER_PACKAGE_LENGTH", "SELLER_PACKAGE_WIDTH", "SELLER_PACKAGE_HEIGHT")


def _numero(valor) -> float | None:
    m = re.search(r"\d+(?:[.,]\d+)?", str(valor or ""))
    return float(m.group().replace(",", ".")) if m else None


def paquete_de(atributos: list[dict]) -> tuple[str, int | None]:
    """('LxAxH' cm, peso g) a partir de los atributos SELLER_PACKAGE_* de un item ('' / None si faltan)."""
    por_id = {a.get("id"): (a.get("value_name") or "") for a in atributos or []}
    medidas = [_numero(por_id.get(x)) for x in _ATTR_PAQUETE]
    texto = "x".join(str(int(round(m))) for m in medidas) if all(medidas) else ""
    peso_txt = por_id.get("SELLER_PACKAGE_WEIGHT", "")
    peso = _numero(peso_txt)
    if peso is not None and "kg" in peso_txt.lower():
        peso *= 1000
    return texto, (int(round(peso)) if peso is not None else None)


def _mismo_paquete(a: str, b: str) -> bool:
    """Compara medidas sin importar el orden (ML las reordena)."""
    return sorted(a.split("x")) == sorted(b.split("x")) if a and b else a == b


def _kg(gramos) -> str:
    return f"{gramos / 1000:.1f}".replace(".", ",") + " kg"


def _plata(n) -> str:
    return "$" + f"{int(n):,}".replace(",", ".")


def info_envio(ml: MercadoLibreClient, p, medidas: str, peso: int | None, precio: int) -> dict:
    """
    Paquete que se envía y lo que Mercado Libre le cobrará a La Loba por cada envío:
    {"medidas", "peso_g", "peso_cobrado_g", "volumetrico", "costo", "tarifa", "descuento", "lineas"}.
    "lineas" es el resumen legible para la ventana de simulación.
    """
    info = {"medidas": medidas, "peso_g": peso, "costo": None, "lineas": []}
    if not (medidas and peso):
        info["lineas"].append("Faltan MEDIDAS PAQUETE o PESO GR: no se puede calcular el costo de envío.")
        return info
    vol = catalogo.peso_facturable(medidas, peso)
    det = catalogo.envio_vendedor(ml, medidas, peso, precio, config_ml()["tipo_publicacion"])
    info.update(det, volumetrico=bool(vol and vol[1]))
    cobrado = det.get("peso_cobrado_g") or (vol[0] * 1000 if vol else peso)
    info["lineas"].append(f"Paquete: {medidas.replace('x', ' × ')} cm · {_kg(peso)}")
    info["lineas"].append(f"Mercado Libre lo cobra como {_kg(cobrado)}"
                          + (" (peso volumétrico: el paquete abulta más de lo que pesa)" if info["volumetrico"] else ""))
    tarifa = f" (tarifa {_plata(det['tarifa'])} con {int(round(det['descuento'] * 100))} % de descuento)" \
        if det.get("descuento") else ""
    info["lineas"].append(f"Costo de envío para La Loba: {_plata(det['costo'])} por venta{tarifa}")
    return info


def simular(p, ml: MercadoLibreClient | None = None) -> dict:
    """Arma la publicación de p y la valida en Mercado Libre sin crearla."""
    ml = ml or MercadoLibreClient()
    cfg = config_ml()
    res = {"ref": p.ref_interna, "titulo": p.titulo, "ok": False, "errores": [], "avisos": [], "item": None,
           "envio": None}
    try:
        _revisar_envio(ml, p, res)
        fotos = fotos_de(p.ref_interna, cfg["carpeta_fotos_id"])
        if not fotos:
            res["errores"].append("No hay fotos en la carpeta de Drive (REF-1.jpg…).")
            return res
        if not p.categoria_id:
            res["errores"].append("Sin categoría.")
            return res
        atributos_cat = ml.get(f"/categories/{p.categoria_id}/attributes", auth=False)
        user_products = "user_product_seller" in (ml.usuario_actual().get("tags") or [])
        ids = subir_fotos(ml, fotos)
        item, faltantes, avisos_attr = armar_item(p, ids, atributos_cat, cfg, user_products)
        res["item"] = item
        res["avisos"].extend(avisos_attr)
        if faltantes:
            res["avisos"].append("Atributos obligatorios sin completar: " + ", ".join(faltantes))
        if item["available_quantity"] <= 0:
            res["avisos"].append("Sin stock disponible: se publicaría pausada.")
            item = {**item, "available_quantity": 1}  # validar igual el resto de la publicación
        if p.categoria_propuesta:
            res["avisos"].append(f"La categoría {p.categoria_id} es una propuesta, revisa que sea la correcta.")
        try:
            ml.post("/items/validate", json=item)
            res["ok"] = True
        except MercadoLibreError as e:
            errores, advertencias = _causas(e)
            res["avisos"].extend(advertencias)
            res["errores"].extend(errores)
            res["ok"] = e.status == 400 and not errores  # solo advertencias: se puede publicar
    except MercadoLibreError as e:
        errores, advertencias = _causas(e)
        res["errores"].extend(errores + advertencias)
    except Exception as e:  # Drive, imagen, red…
        logger.error("Error simulando publicación de %s", p.ref_interna, exc_info=True)
        res["errores"].append(str(e))
    finally:
        _guardar_log(res)
    return res


def _revisar_envio(ml: MercadoLibreClient, p, res: dict) -> None:
    """Agrega a res["envio"] el paquete y su costo; avisa si el precio ML no alcanza a cubrirlo."""
    try:
        info = info_envio(ml, p, getattr(p, "medidas_paquete", "") or "", p.peso_gr, p.precio_ml or 0)
    except (MercadoLibreError, KeyError) as e:
        logger.warning("No se pudo consultar el costo de envío de %s: %s", p.ref_interna, e)
        res["envio"] = {"lineas": [f"No se pudo consultar el costo de envío: {e}"], "costo": None}
        return
    res["envio"] = info
    costo = info.get("costo")
    if costo is None or not p.precio_ml:
        return
    recibe = p.precio_ml - (p.comision or 0) - costo
    info["lineas"].append(f"Recibiría La Loba: {_plata(recibe)} (precio en el local {_plata(p.precio_local or 0)})")
    if costo > (p.envio or 0) and recibe < (p.precio_local or 0):
        res["avisos"].append(
            f"El precio ML se calculó con {_plata(p.envio or 0)} de envío, pero Mercado Libre cobraría "
            f"{_plata(costo)}: La Loba recibiría menos que en el local. Actualiza la lista para recalcular el precio.")


def _guardar_log(res: dict) -> None:
    try:
        os.makedirs(CARPETA_LOG, exist_ok=True)
        ruta = os.path.join(CARPETA_LOG, f"simulacion_{res['ref'] or 'sin_ref'}.json")
        with open(ruta, "w", encoding="utf-8") as fh:
            json.dump({**res, "fecha": datetime.now().isoformat(timespec="seconds")}, fh, ensure_ascii=False, indent=2)
    except OSError:
        logger.warning("No se pudo guardar el log de simulación", exc_info=True)


# ── vínculo con publicaciones existentes (por SKU = REF INTERNA) ──────────────
ESTADOS_ML = {"active": "Publicado", "paused": "Pausado", "closed": "Cerrado",
              "under_review": "En revisión", "inactive": "Inactivo"}


def moderada(item: dict) -> bool:
    """Publicación bajada por Mercado Libre (infracción): no cuenta como publicada."""
    return "forbidden" in (item.get("sub_status") or []) or "deleted" in (item.get("sub_status") or [])


def buscar_por_sku(ml: MercadoLibreClient, ref: str) -> list[dict]:
    """Publicaciones de la cuenta con SELLER_SKU = ref (id, status, permalink, price, available_quantity, title)."""
    if not ref:
        return []
    uid = ml.usuario_actual()["id"]
    ids = ml.get(f"/users/{uid}/items/search", params={"seller_sku": ref}).get("results", [])
    if not ids:
        return []
    return ml.items(ids[:20], "id,status,sub_status,permalink,price,available_quantity,title")


def publicacion_vigente(ml: MercadoLibreClient, ref: str) -> dict | None:
    """La publicación no cerrada ni moderada de ese SKU (activa primero), o None."""
    vivas = [i for i in buscar_por_sku(ml, ref) if i.get("status") != "closed" and not moderada(i)]
    vivas.sort(key=lambda i: i.get("status") != "active")
    return vivas[0] if vivas else None


# ── publicar ───────────────────────────────────────────────────────────────────
def descripcion_final(p) -> str:
    """DESCRIPCION ML de la planilla (o la aprobada); si no hay, un texto base con los datos conocidos."""
    texto = (getattr(p, "descripcion", "") or "").strip()
    if texto:
        return texto
    return (f"{p.titulo}\n\n"
            "Producto nuevo.\n"
            f"Código: {p.ref_interna}\n\n"
            "Despacho por Mercado Envíos. Boleta incluida en el paquete.")


def publicar(p, ml: MercadoLibreClient | None = None) -> dict:
    """
    Crea la publicación REAL en Mercado Libre: fotos, item (validado antes) y descripción.
    No publica si ya existe una publicación no cerrada con el mismo SKU, si no hay stock
    disponible o si la validación de ML devuelve errores.
    """
    ml = ml or MercadoLibreClient()
    cfg = config_ml()
    res = {"ref": p.ref_interna, "titulo": p.titulo, "ok": False, "errores": [], "avisos": [],
           "item_id": None, "permalink": None, "status": None, "titulo_ml": None, "item": None}
    try:
        existente = publicacion_vigente(ml, p.ref_interna)
        if existente:
            res["errores"].append(f"Ya existe una publicación con este SKU: {existente['id']} "
                                  f"({ESTADOS_ML.get(existente.get('status'), existente.get('status'))}).")
            res["item_id"], res["permalink"] = existente["id"], existente.get("permalink")
            return res
        if not p.categoria_id:
            res["errores"].append("Sin categoría.")
        if not p.precio_ml:
            res["errores"].append("Sin precio ML.")
        if max((p.stock or 0) - cfg["stock_reserva"], 0) <= 0:
            res["errores"].append("Sin stock disponible para publicar.")
        fotos = fotos_de(p.ref_interna, cfg["carpeta_fotos_id"])
        if not fotos:
            res["errores"].append("No hay fotos en la carpeta de Drive (REF-1.jpg…).")
        if res["errores"]:
            return res

        atributos_cat = ml.get(f"/categories/{p.categoria_id}/attributes", auth=False)
        user_products = "user_product_seller" in (ml.usuario_actual().get("tags") or [])
        ids = subir_fotos(ml, fotos)
        item, faltantes, avisos_attr = armar_item(p, ids, atributos_cat, cfg, user_products)
        res["item"] = item
        res["avisos"].extend(avisos_attr)
        if faltantes:
            res["avisos"].append("Atributos obligatorios sin completar: " + ", ".join(faltantes))

        # 1) validar: si ML devuelve errores (no solo advertencias), no se publica
        try:
            ml.post("/items/validate", json=item)
        except MercadoLibreError as e:
            errores, advertencias = _causas(e)
            res["avisos"].extend(advertencias)
            if errores or e.status != 400:
                res["errores"].extend(errores or [str(e)])
                return res

        # 2) crear la publicación
        creado = ml.post("/items", json=item)
        res.update(ok=True, item_id=creado.get("id"), permalink=creado.get("permalink"),
                   status=creado.get("status"), titulo_ml=creado.get("title"))
        logger.info("Publicado en ML: %s → %s %s", p.ref_interna, res["item_id"], res["permalink"])
        _comparar_paquete(ml, p, item, creado, res)

        # 3) descripción (si falla, la publicación ya existe: se avisa para reintentar)
        try:
            ml.post(f"/items/{res['item_id']}/description", json={"plain_text": descripcion_final(p)})
        except MercadoLibreError as e:
            res["avisos"].append(f"La publicación se creó, pero no se pudo cargar la descripción: {e}")
    except MercadoLibreError as e:
        errores, advertencias = _causas(e)
        res["errores"].extend(errores + advertencias)
    except Exception as e:
        logger.error("Error publicando %s", p.ref_interna, exc_info=True)
        res["errores"].append(str(e))
    finally:
        _guardar_log({**res, "ref": f"{p.ref_interna}_publicacion"})
    return res


def _comparar_paquete(ml: MercadoLibreClient, p, enviado: dict, creado: dict, res: dict) -> None:
    """Avisa si Mercado Libre dejó otras medidas o peso del paquete que los enviados (y el nuevo costo)."""
    try:
        medidas_env, peso_env = paquete_de(enviado.get("attributes"))
        atributos = creado.get("attributes") or (ml.get(f"/items/{creado.get('id')}") or {}).get("attributes")
        medidas_ml, peso_ml = paquete_de(atributos)
        if not (medidas_env and medidas_ml):
            return
        if _mismo_paquete(medidas_env, medidas_ml) and abs((peso_ml or 0) - (peso_env or 0)) <= 50:
            return
        aviso = (f"Mercado Libre cambió el paquete: se enviaron {medidas_env.replace('x', ' × ')} cm y "
                 f"{_kg(peso_env or 0)}, y quedó {medidas_ml.replace('x', ' × ')} cm y {_kg(peso_ml or 0)}.")
        if peso_ml:
            det = catalogo.envio_vendedor(ml, medidas_ml, peso_ml, p.precio_ml, config_ml()["tipo_publicacion"])
            aviso += f" Con eso el envío cuesta {_plata(det['costo'])} por venta (el precio usó {_plata(p.envio or 0)})."
        res["avisos"].append(aviso)
        logger.warning("ML cambió el paquete de %s: %s → %s", p.ref_interna, medidas_env, medidas_ml)
    except Exception:
        logger.warning("No se pudo comparar el paquete publicado de %s", p.ref_interna, exc_info=True)


# ── actualizar descripción ─────────────────────────────────────────────────────
def actualizar_descripcion(item_id: str, texto: str, ml: MercadoLibreClient | None = None) -> dict:
    """
    Reemplaza la descripción de una publicación existente. Devuelve {"ok", "cambio", "error"}:
    cambio=False si la de Mercado Libre ya era igual (no se envía nada).
    """
    ml = ml or MercadoLibreClient()
    texto = (texto or "").strip()
    if not texto:
        return {"ok": False, "cambio": False, "error": "La descripción está vacía."}
    try:
        try:
            actual = (ml.get(f"/items/{item_id}/description") or {}).get("plain_text") or ""
        except MercadoLibreError as e:
            if e.status != 404:
                raise
            actual = None  # la publicación no tiene descripción todavía
        if actual is not None and actual.strip() == texto:
            return {"ok": True, "cambio": False, "error": None}
        if actual is None:
            ml.post(f"/items/{item_id}/description", json={"plain_text": texto})
        else:
            ml.put(f"/items/{item_id}/description", params={"api_version": 2}, json={"plain_text": texto})
        logger.info("Descripción actualizada en ML: %s", item_id)
        return {"ok": True, "cambio": True, "error": None}
    except MercadoLibreError as e:
        errores, advertencias = _causas(e)
        d = e.detalle if isinstance(e.detalle, dict) else {}
        return {"ok": False, "cambio": False,
                "error": "; ".join(errores + advertencias) or d.get("message") or str(e)}


# ── pausar / reactivar ─────────────────────────────────────────────────────────
def cambiar_estado(item_id: str, estado: str, ml: MercadoLibreClient | None = None) -> dict:
    """
    estado: "paused" (pausar) o "active" (reactivar). Devuelve {"ok", "estado", "error"}.
    Reactivar sin stock no funciona: Mercado Libre la deja pausada.
    """
    assert estado in ("paused", "active")
    ml = ml or MercadoLibreClient()
    try:
        r = ml.put(f"/items/{item_id}", json={"status": estado})
        logger.info("Publicación %s → %s", item_id, r.get("status"))
        return {"ok": r.get("status") == estado, "estado": r.get("status"), "error": None}
    except MercadoLibreError as e:
        errores, advertencias = _causas(e)
        d = e.detalle if isinstance(e.detalle, dict) else {}
        return {"ok": False, "estado": None, "error": "; ".join(errores + advertencias) or d.get("message") or str(e)}
