"""
Diagnóstico y actualización de campos de producto en Odoo vía JSON-RPC.

Uso:
    python odoo_test_descripcion.py leer
    python odoo_test_descripcion.py name "Nuevo nombre del producto"
    python odoo_test_descripcion.py description_sale "Texto para presupuestos"
    python odoo_test_descripcion.py description_purchase "Texto para compras"
    python odoo_test_descripcion.py description "Nota interna"

Cada subcomando escribe un único campo y muestra el valor antes/después.
"""

import json
import sys
import urllib.request

# Credenciales desde apps/servidor/server_settings.cfg, sección [ODOO] (fuera de git).
import configparser  # noqa: E402
from pathlib import Path  # noqa: E402

_cfg = configparser.ConfigParser()
_cfg.read(Path(__file__).resolve().parents[1] / "apps" / "servidor" / "server_settings.cfg")
URL = _cfg.get("ODOO", "url", fallback="").rstrip("/")
DB = _cfg.get("ODOO", "db", fallback="")
USERNAME = _cfg.get("ODOO", "username", fallback="")
PASSWORD = _cfg.get("ODOO", "password", fallback="")
if not all((URL, DB, USERNAME, PASSWORD)):
    sys.exit("Falta configurar la sección [ODOO] en apps/servidor/server_settings.cfg.")
PRODUCT_ID = 12692

DESC_FIELDS = [
    "name",
    "description",
    "description_sale",
    "description_purchase",
    "website_description",
    "website_meta_description",
    "is_published",
]


def jsonrpc(endpoint: str, params: dict):
    payload = {
        "jsonrpc": "2.0",
        "method": "call",
        "params": params,
        "id": 1,
    }
    req = urllib.request.Request(
        f"{URL}{endpoint}",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if "error" in data:
        raise RuntimeError(json.dumps(data["error"], indent=2, ensure_ascii=False))
    return data["result"]


def authenticate():
    uid = jsonrpc(
        "/jsonrpc",
        {
            "service": "common",
            "method": "authenticate",
            "args": [DB, USERNAME, PASSWORD, {}],
        },
    )
    if not uid:
        raise RuntimeError("Autenticación fallida")
    return uid


def call(uid: int, model: str, method: str, args: list, kwargs: dict | None = None):
    return jsonrpc(
        "/jsonrpc",
        {
            "service": "object",
            "method": "execute_kw",
            "args": [DB, uid, PASSWORD, model, method, args, kwargs or {}],
        },
    )


def leer_por_idioma(uid: int, campos: list[str]):
    """Lee el mismo registro en varios idiomas para detectar traducciones divergentes."""
    for lang in ("es_ES", "es_CL", "en_US"):
        try:
            data = call(
                uid, "product.template", "read",
                [[PRODUCT_ID], campos],
                {"context": {"lang": lang}},
            )
            if data:
                print(f"\n[lang={lang}] {data[0]}")
        except Exception as e:
            print(f"\n[lang={lang}] error: {e}")


def campos_disponibles(uid: int) -> list[str]:
    info = call(uid, "product.template", "fields_get", [], {"attributes": ["type"]})
    existentes = [f for f in DESC_FIELDS if f in info]
    faltantes = [f for f in DESC_FIELDS if f not in info]
    print(f"[fields_get] disponibles: {existentes}")
    if faltantes:
        print(f"[fields_get] NO existen en esta instancia: {faltantes}")
    return existentes


def leer(uid: int, campos: list[str]) -> dict:
    data = call(uid, "product.template", "read", [[PRODUCT_ID], campos])
    if not data:
        raise RuntimeError(f"Producto {PRODUCT_ID} no encontrado")
    rec = data[0]
    print(f"\n[leer] producto {PRODUCT_ID}:")
    for k, v in rec.items():
        preview = (str(v)[:120] + "…") if v and len(str(v)) > 120 else v
        print(f"  {k}: {preview!r}")
    return rec


LANG = "es_ES"  # idioma que usa la UI de Odoo


def escribir_campo(uid: int, campo: str, valor: str):
    print(f"\n[escribir] lang={LANG} {campo} = {valor!r}")
    ok = call(
        uid, "product.template", "write",
        [[PRODUCT_ID], {campo: valor}],
        {"context": {"lang": LANG}},
    )
    print(f"[escribir] write -> {ok}")


CAMPOS_ESCRIBIBLES = {"name", "description", "description_sale", "description_purchase"}


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    accion = sys.argv[1]
    uid = authenticate()
    print(f"[auth] uid={uid}")
    campos = campos_disponibles(uid)

    if accion == "leer":
        leer(uid, campos)
        leer_por_idioma(uid, ["name", "description_sale"])
        return

    if accion not in CAMPOS_ESCRIBIBLES:
        print(f"Acción no reconocida: {accion}")
        print(__doc__)
        sys.exit(1)

    if accion not in campos:
        print(f"[error] el campo '{accion}' no existe en esta instancia")
        sys.exit(2)

    if len(sys.argv) < 3:
        print(f"[error] falta el valor. Uso: python {sys.argv[0]} {accion} \"texto\"")
        sys.exit(1)

    valor = sys.argv[2]
    antes = leer(uid, [accion])
    escribir_campo(uid, accion, valor)
    despues = leer(uid, [accion])

    print("\n[diff]")
    if antes.get(accion) != despues.get(accion):
        print(f"  ✓ {accion}: {antes.get(accion)!r} → {despues.get(accion)!r}")
    else:
        print(f"  · {accion} sin cambios")


if __name__ == "__main__":
    main()
