"""
Paso 4: el primer pedido de herramienta (una sola llamada, sin loop).

Se le manda al modelo la pregunta + las fichas de las herramientas (ESQUEMAS)
y se muestra su respuesta CRUDA: texto, o un pedido de herramienta.
Nada se ejecuta: solo miramos qué decide el modelo.

Uso:
    .venv\\Scripts\\python scripts\\ia_paso4.py
    .venv\\Scripts\\python scripts\\ia_paso4.py --sin-pista       # borra "Úsala primero para obtener el id"
    .venv\\Scripts\\python scripts\\ia_paso4.py --veces 5 [--sin-pista]   # repite para ver si siempre decide igual
    .venv\\Scripts\\python scripts\\ia_paso4.py "otra pregunta"
"""
import copy
import json
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import django  # noqa: E402

import apps.servidor.settings  # noqa: E402,F401

django.setup()

from openai import OpenAI  # noqa: E402

from modules.ia.config import cargar_config  # noqa: E402
from modules.ia.herramientas import ESQUEMAS  # noqa: E402

args = sys.argv[1:]
sin_pista = "--sin-pista" in args
veces = 1
if "--veces" in args:
    i = args.index("--veces")
    veces = int(args[i + 1])
    del args[i:i + 2]
args = [a for a in args if a != "--sin-pista"]
pregunta = " ".join(args) or "¿Cuánto stock hay de espuma 2 cm densidad 15?"

esquemas = copy.deepcopy(ESQUEMAS)
if sin_pista:
    for e in esquemas:
        f = e["function"]
        f["description"] = f["description"].replace(" Úsala primero para obtener el id de un producto.", "")

cfg = cargar_config()
cliente = OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=60, max_retries=1)
mensajes = [
    {"role": "system", "content": "Eres el asistente interno de la ferretería La Loba. Responde en español."},
    {"role": "user", "content": pregunta},
]

print(f"Modelo:   {cfg.modelo}")
print(f"Pregunta: {pregunta}")
print(f"Fichas:   {[e['function']['name'] for e in esquemas]}  {'(SIN la pista del id)' if sin_pista else '(con la pista del id)'}\n")

resumen = {}
for n in range(1, veces + 1):
    t0 = time.perf_counter()
    r = cliente.chat.completions.create(
        model=cfg.modelo, messages=mensajes, tools=esquemas, tool_choice="auto", temperature=cfg.temperatura,
    )
    msg = r.choices[0].message
    seg = time.perf_counter() - t0
    print(f"--- intento {n} · {seg:.1f}s · finish_reason={r.choices[0].finish_reason!r} ---")
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"PIDE HERRAMIENTA: {tc.function.name}({tc.function.arguments})   id de la llamada: {tc.id}")
            clave = f"herramienta: {tc.function.name}"
            resumen[clave] = resumen.get(clave, 0) + 1
    else:
        print(f"RESPONDE TEXTO (sin herramienta): {(msg.content or '').strip()[:300]}")
        resumen["texto sin herramienta"] = resumen.get("texto sin herramienta", 0) + 1
    if veces == 1:
        print("\nRespuesta cruda completa del proveedor:")
        crudo = msg.model_dump(exclude_none=True)
        for k in ("reasoning", "reasoning_content"):
            if k in crudo:
                crudo[k] = crudo[k][:200] + "…"
        print(json.dumps(crudo, ensure_ascii=False, indent=2))
    print()

if veces > 1:
    print("Resumen:", json.dumps(resumen, ensure_ascii=False))
