"""
Configura el asistente IA: escribe las líneas IA_* en el archivo .env y prueba la conexión.

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\ia_configurar.py          # configurar
    .venv\\Scripts\\python scripts\\ia_configurar.py prueba   # probar la configuración actual

Pasos que sigue:
 1. Eliges el proveedor (NVIDIA por defecto: es el que usa también la búsqueda por significado).
 2. Se abre el navegador en la página para crear la API key; la pegas aquí (no se muestra).
 3. Eliges el modelo (Enter = el sugerido).
 4. El script prueba el chat (y las embeddings en NVIDIA) ANTES de guardar.
 5. Si todo responde, actualiza solo las líneas IA_* del .env; el resto queda igual.
"""
import getpass
import os
import sys
import time
import webbrowser
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
for _flujo in (sys.stdout, sys.stderr):
    if hasattr(_flujo, "reconfigure"):
        _flujo.reconfigure(encoding="utf-8")

from dotenv import dotenv_values, set_key  # noqa: E402
from openai import OpenAI, APIError, APITimeoutError  # noqa: E402

from modules.ia.config import PROVEEDORES, ConfigIAError, cargar_config  # noqa: E402

ENV_PATH = RAIZ / ".env"

# Dónde se saca la key y qué modelo sugerir por proveedor.
GUIA = {
    "nvidia": {
        "url_key": "https://build.nvidia.com/settings/api-keys",
        "modelo": "deepseek-ai/deepseek-v3.2",
        "embeddings": "nvidia/nemotron-3-embed-1b",
        "nota": "Gratis con cuenta NVIDIA. La key empieza con nvapi-",
    },
    "groq": {
        "url_key": "https://console.groq.com/keys",
        "modelo": "llama-3.3-70b-versatile",
        "nota": "Muy rápido. Sin embeddings: la búsqueda por significado no funcionará.",
    },
    "gemini": {
        "url_key": "https://aistudio.google.com/apikey",
        "modelo": "gemini-2.5-flash",
        "nota": "Gratis con cuenta Google. Sin embeddings compatibles con el índice actual.",
    },
    "openrouter": {
        "url_key": "https://openrouter.ai/keys",
        "modelo": "deepseek/deepseek-chat",
        "nota": "Muchos modelos con una sola key (algunos de pago).",
    },
    "ollama": {
        "url_key": None,
        "modelo": "qwen2.5:7b",
        "nota": "Corre en este PC (requiere Ollama instalado). No necesita key.",
    },
}


def preguntar(texto, por_defecto=""):
    sufijo = f" [{por_defecto}]" if por_defecto else ""
    return input(f"{texto}{sufijo}: ").strip() or por_defecto


def elegir_proveedor(actual):
    print("\n1) Proveedor de IA:")
    nombres = list(PROVEEDORES)
    for i, nombre in enumerate(nombres, 1):
        print(f"   {i}. {nombre:<11} {GUIA[nombre]['nota']}")
    por_defecto = actual if actual in nombres else "nvidia"
    r = preguntar("   Número o nombre", por_defecto)
    if r.isdigit() and 1 <= int(r) <= len(nombres):
        return nombres[int(r) - 1]
    if r.lower() in nombres:
        return r.lower()
    sys.exit(f"Proveedor '{r}' no reconocido.")


def pedir_key(proveedor, actual_key):
    guia = GUIA[proveedor]
    if not guia["url_key"]:
        return ""
    print(f"\n2) API key de {proveedor}. Se abrirá: {guia['url_key']}")
    print("   Crea una key, cópiala y pégala aquí (no se verá al pegar).")
    webbrowser.open(guia["url_key"])
    aviso = " (Enter = mantener la actual)" if actual_key else ""
    key = getpass.getpass(f"   API key{aviso}: ").strip() or actual_key
    if not key:
        sys.exit("Sin API key no se puede continuar.")
    return key


def probar_chat(base_url, key, modelo):
    cliente = OpenAI(base_url=base_url, api_key=key or "ollama", timeout=60, max_retries=0)
    t0 = time.perf_counter()
    r = cliente.chat.completions.create(
        model=modelo,
        messages=[{"role": "user", "content": "Responde solo: OK"}],
        max_tokens=300,  # los modelos que "razonan" gastan tokens antes de responder
    )
    texto = (r.choices[0].message.content or "").strip()
    print(f"   ✔ Chat responde en {time.perf_counter() - t0:.1f}s: {texto[:60]!r}")


def probar_embeddings(base_url, key, modelo):
    cliente = OpenAI(base_url=base_url, api_key=key, timeout=60, max_retries=0)
    r = cliente.embeddings.create(
        model=modelo, input=["pastillas de freno"], extra_body={"input_type": "query", "truncate": "END"}
    )
    print(f"   ✔ Embeddings responden (vector de {len(r.data[0].embedding)} dimensiones)")


def configurar():
    actual = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    proveedor = elegir_proveedor((actual.get("IA_PROVEEDOR") or "").lower())
    guia = GUIA[proveedor]
    mismo = (actual.get("IA_PROVEEDOR") or "").lower() == proveedor

    key = pedir_key(proveedor, actual.get("IA_API_KEY", "") if mismo else "")
    modelo = preguntar("\n3) Modelo", actual.get("IA_MODELO") if mismo and actual.get("IA_MODELO") else guia["modelo"])
    embeddings = guia.get("embeddings")
    if embeddings:
        embeddings = preguntar("   Modelo de embeddings (búsqueda por significado)",
                               actual.get("IA_MODELO_EMBEDDINGS") or embeddings)

    base_url = PROVEEDORES[proveedor]
    print("\n4) Probando la conexión antes de guardar...")
    try:
        probar_chat(base_url, key, modelo)
        if embeddings:
            probar_embeddings(base_url, key, embeddings)
    except APITimeoutError:
        sys.exit("   ✖ El proveedor no respondió en 60 s. Prueba otro modelo. No se guardó nada.")
    except APIError as e:
        sys.exit(f"   ✖ Error del proveedor: {e}\n   Revisa la key y el nombre del modelo. No se guardó nada.")

    ENV_PATH.touch(exist_ok=True)
    valores = {"IA_PROVEEDOR": proveedor, "IA_API_KEY": key, "IA_MODELO": modelo}
    if embeddings:
        valores["IA_MODELO_EMBEDDINGS"] = embeddings
    for clave, valor in valores.items():
        set_key(str(ENV_PATH), clave, valor, quote_mode="never")
    print(f"\n✔ Guardado en {ENV_PATH} ({', '.join(valores)}). El resto del archivo no se tocó.")
    if not embeddings:
        print("⚠ Este proveedor no tiene embeddings compatibles: la búsqueda por significado (RAG) no funcionará.")
    else:
        print("  Si es la primera vez, genera el índice de búsqueda con:\n"
              "    .venv\\Scripts\\python scripts\\ia_rag2_indexar.py")
    print()


def prueba():
    try:
        cfg = cargar_config()
    except ConfigIAError as e:
        sys.exit(f"✖ {e}\n  Ejecuta este script sin 'prueba' para configurarlo.")
    print(f"Proveedor: {cfg.proveedor}   Modelo: {cfg.modelo}")
    try:
        probar_chat(cfg.base_url, cfg.api_key, cfg.modelo)
        embeddings = os.getenv("IA_MODELO_EMBEDDINGS")
        if cfg.proveedor == "nvidia" and embeddings:
            probar_embeddings(cfg.base_url, cfg.api_key, embeddings)
    except (APIError, APITimeoutError) as e:
        sys.exit(f"   ✖ {e}")
    print("Todo listo.\n")


if __name__ == "__main__":
    try:
        prueba() if len(sys.argv) > 1 and sys.argv[1] == "prueba" else configurar()
    except (KeyboardInterrupt, EOFError):
        sys.exit("\nCancelado. No se guardó nada.")
