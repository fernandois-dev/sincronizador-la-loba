"""
Prueba el asistente IA desde la consola.

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\ia_preguntar.py                      # conversación
    .venv\\Scripts\\python scripts\\ia_preguntar.py "stock espuma 15 cm"  # una pregunta

Requiere en .env: IA_PROVEEDOR, IA_API_KEY, IA_MODELO (ver .env.example).
Comandos en modo conversación: 'nueva' reinicia la conversación, 'salir' termina.
"""
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)                      # la base y server_settings.cfg usan rutas relativas
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import django  # noqa: E402

import apps.servidor.settings  # noqa: E402,F401  (configura Django)

django.setup()

from openai import APIError, AuthenticationError, BadRequestError, NotFoundError  # noqa: E402

from modules.ia.agente import Agente, PasoHerramienta  # noqa: E402
from modules.ia.config import ConfigIAError  # noqa: E402


def mostrar_paso(paso: PasoHerramienta):
    args = ", ".join(f"{k}={v!r}" for k, v in paso.argumentos.items())
    resumen = paso.resultado if len(paso.resultado) <= 160 else paso.resultado[:160] + "…"
    print(f"   -> {paso.nombre}({args})  [{paso.segundos:.1f}s]")
    print(f"      {resumen}")


def responder(agente: Agente, pregunta: str):
    try:
        r = agente.preguntar(pregunta, al_usar_herramienta=mostrar_paso)
    except AuthenticationError:
        print("\n[error] La API key fue rechazada. Revisa IA_API_KEY en .env.")
        return
    except NotFoundError:
        print(f"\n[error] El proveedor no reconoce el modelo '{agente.cfg.modelo}'. Revisa IA_MODELO.")
        return
    except BadRequestError as exc:
        print(f"\n[error] El proveedor rechazó la solicitud: {exc}")
        print("        Si menciona 'tools' o 'function', este modelo no soporta herramientas: prueba otro.")
        return
    except APIError as exc:
        print(f"\n[error] Error del proveedor: {exc}")
        return

    print(f"\n{r.texto}\n")
    u = r.uso
    print(
        f"   [{len(r.pasos)} herramientas · {u.llamadas} llamadas al modelo · "
        f"{u.tokens_entrada:,} tokens entrada / {u.tokens_salida:,} salida · {r.segundos_total:.1f}s]".replace(",", ".")
    )
    if r.llego_al_limite:
        print("   [se alcanzó el límite de pasos]")


def main():
    try:
        agente = Agente()
    except ConfigIAError as exc:
        sys.exit(f"[config] {exc}")

    print(f"Asistente La Loba · {agente.cfg.proveedor} · {agente.cfg.modelo}")
    if len(sys.argv) > 1:
        responder(agente, " ".join(sys.argv[1:]))
        return

    print("Escribe tu pregunta ('nueva' para reiniciar, 'salir' para terminar).\n")
    while True:
        try:
            pregunta = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not pregunta:
            continue
        if pregunta.lower() in {"salir", "exit", "q"}:
            break
        if pregunta.lower() == "nueva":
            agente.reiniciar()
            print("(conversación reiniciada)\n")
            continue
        responder(agente, pregunta)


if __name__ == "__main__":
    main()
