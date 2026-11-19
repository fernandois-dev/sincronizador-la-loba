"""
Conecta el Gestor La Loba con la cuenta de Mercado Libre (se hace UNA vez).

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\ml_conectar.py          # conectar
    .venv\\Scripts\\python scripts\\ml_conectar.py prueba   # probar conexión existente

Pasos que sigue:
 1. Abre el navegador en la página de autorización de Mercado Libre.
 2. Inicias sesión con la cuenta VENDEDORA y aceptas.
 3. ML te manda a la URI de redirect con ?code=TG-... en la barra de direcciones.
 4. Copias esa dirección completa y la pegas aquí.
 5. El script guarda los tokens en data/ml_tokens.json y prueba la conexión.
"""
import os
import secrets
import sys
import urllib.parse
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mercadolibre.client import (  # noqa: E402
    MercadoLibreClient, MercadoLibreError, canjear_codigo, config,
    generar_pkce, url_autorizacion, TOKENS_PATH,
)

PRODUCTOS_PRUEBA = ["pastillas de freno toyota yaris", "disco de freno auto", "llave francesa 10 pulgadas"]


def conectar():
    cfg = config()
    state = secrets.token_urlsafe(16)
    verifier, challenge = generar_pkce() if cfg["usar_pkce"] else (None, None)
    url = url_autorizacion(state, challenge)

    print("\n1) Se abrirá el navegador. Inicia sesión con la cuenta VENDEDORA de La Loba y autoriza.")
    print("   Si no se abre, copia esta dirección en el navegador:\n")
    print("   " + url + "\n")
    webbrowser.open(url)

    pegado = input("2) Pega aquí la dirección completa a la que te llevó (contiene ?code=TG-...):\n> ").strip()
    params = urllib.parse.parse_qs(urllib.parse.urlparse(pegado).query)
    code = (params.get("code") or [pegado if pegado.startswith("TG-") else ""])[0]
    if not code:
        sys.exit("No encontré el code en lo que pegaste. Vuelve a intentarlo.")
    if params.get("state") and params["state"][0] != state:
        sys.exit("El 'state' no coincide: la respuesta no corresponde a esta solicitud. Vuelve a intentarlo.")

    tokens = canjear_codigo(code, verifier)
    print(f"\n✔ Tokens guardados en {TOKENS_PATH}" + (" y en Drive" if os.getenv("ML_TOKENS_DRIVE_FOLDER") else ""))
    if not tokens.get("refresh_token"):
        print("⚠ ATENCIÓN: Mercado Libre no entregó refresh_token (falta 'acceso offline' en la app).\n"
              "  La conexión dejará de funcionar en 6 horas. Activa el acceso offline en\n"
              "  developers.mercadolibre.cl y vuelve a ejecutar este script.")
    probar()


def probar():
    ml = MercadoLibreClient()
    yo = ml.usuario_actual()
    print("\n── Cuenta conectada ─────────────────────────")
    print(f"  Usuario : {yo.get('nickname')} (id {yo.get('id')})")
    print(f"  Sitio   : {yo.get('site_id')}")
    print(f"  Tipo    : {yo.get('user_type')}")
    rep = yo.get("seller_reputation") or {}
    print(f"  Reputación: {rep.get('level_id') or 'sin reputación aún'}")
    estado = yo.get("status") or {}
    if estado.get("list", {}).get("allow") is False:
        print("  ⚠ La cuenta aún NO puede publicar:", estado["list"].get("codes"))
    else:
        print("  Puede publicar: sí")

    print("\n── Prueba de categorías ─────────────────────")
    for texto in PRODUCTOS_PRUEBA:
        try:
            sug = ml.predecir_categoria(texto, limite=1)
            if sug:
                s = sug[0]
                print(f"  '{texto}' → {s.get('category_name')} ({s.get('category_id')})")
            else:
                print(f"  '{texto}' → sin sugerencia")
        except MercadoLibreError as e:
            print(f"  '{texto}' → error: {e}")
    print("\nTodo listo. Puedes ejecutar 'prueba' cuando quieras para verificar la conexión.\n")


if __name__ == "__main__":
    try:
        probar() if len(sys.argv) > 1 and sys.argv[1] == "prueba" else conectar()
    except MercadoLibreError as e:
        sys.exit(f"\n✖ {e}")
