"""
Paso 1 (lección 1): hablar con el modelo, sin herramientas.

Uso:
    .venv\\Scripts\\python scripts\\ia_paso1.py
    .venv\\Scripts\\python scripts\\ia_paso1.py "tu pregunta"

Muestra cada etapa con su tiempo para ver dónde se demora:
conexión -> primer token (el modelo empezó a responder) -> respuesta completa.
"""
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from openai import OpenAI, APIError, APITimeoutError  # noqa: E402

from modules.ia.config import cargar_config  # noqa: E402

cfg = cargar_config()
pregunta = " ".join(sys.argv[1:]) or "En una frase: ¿qué es una pastilla de freno?"

# Esto es TODO lo que se le envía al modelo: el modelo no sabe nada más.
mensajes = [
    {"role": "system", "content": "Eres el asistente de la ferretería La Loba. Responde breve, en español."},
    {"role": "user", "content": pregunta},
]

print(f"Proveedor: {cfg.proveedor}   URL: {cfg.base_url}")
print(f"Modelo:    {cfg.modelo}")
print(f"Pregunta:  {pregunta}\n")

# Sin reintentos y con espera corta: si algo falla, queremos verlo de inmediato.
cliente = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=60, max_retries=0)

t0 = time.perf_counter()
print("[0.0s] enviando…", flush=True)
try:
    stream = cliente.chat.completions.create(
        model=cfg.modelo,
        messages=mensajes,
        temperature=cfg.temperatura,
        stream=True,                                  # la respuesta llega en trozos
        stream_options={"include_usage": True},       # al final llega el conteo de tokens
    )
except APITimeoutError:
    sys.exit(f"[{time.perf_counter()-t0:.1f}s] El proveedor no respondió en 60 s (modelo en cola o saturado). Prueba otro modelo.")
except APIError as exc:
    sys.exit(f"[{time.perf_counter()-t0:.1f}s] Error del proveedor: {exc}")

primero = None
pensando = False
uso = None
try:
    for trozo in stream:
        if trozo.usage:
            uso = trozo.usage
        if not trozo.choices:
            continue
        delta = trozo.choices[0].delta
        # Modelos que "piensan" antes de responder. Cada proveedor usa un nombre distinto.
        razonamiento = getattr(delta, "reasoning_content", None) or getattr(delta, "reasoning", None)
        texto = delta.content
        if (razonamiento or texto) and primero is None:
            primero = time.perf_counter() - t0
            print(f"[{primero:.1f}s] primer token recibido\n", flush=True)
        if razonamiento:
            if not pensando:
                print("--- razonamiento interno del modelo ---", flush=True)
                pensando = True
            print(razonamiento, end="", flush=True)
        if texto:
            if pensando:
                print("\n--- respuesta ---", flush=True)
                pensando = False
            print(texto, end="", flush=True)
except APITimeoutError:
    sys.exit(f"\n[{time.perf_counter()-t0:.1f}s] Se cortó esperando más texto.")

total = time.perf_counter() - t0
print(f"\n\n[{total:.1f}s] respuesta completa")
if uso:
    print(f"Tokens: {uso.prompt_tokens} de entrada (lo que enviaste) · {uso.completion_tokens} de salida (lo que generó)")
    detalle = getattr(uso, "completion_tokens_details", None)
    if detalle and getattr(detalle, "reasoning_tokens", None):
        print(f"        de esos, {detalle.reasoning_tokens} fueron de razonamiento interno (también se cobran)")
else:
    print("Este proveedor no informó el conteo de tokens.")
