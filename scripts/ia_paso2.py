"""
Paso 2 (lección 2): una herramienta, SIN inteligencia artificial.

Una "herramienta" es solo una función de Python. Aquí la llamas tú,
exactamente como después la va a llamar el agente cuando el modelo la pida.

Uso:
    .venv\\Scripts\\python scripts\\ia_paso2.py "espuma 15 cm"
    .venv\\Scripts\\python scripts\\ia_paso2.py "PAST HILUX"
"""
import json
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import django  # noqa: E402

import apps.servidor.settings  # noqa: E402,F401

django.setup()

from modules.ia.herramientas import buscar_producto, ejecutar  # noqa: E402

texto = " ".join(sys.argv[1:]) or "espuma 15 cm"

print("1) Llamada directa, como cualquier función de Python:\n")
print(f"   buscar_producto(texto={texto!r}, limite=5)\n")
resultado = buscar_producto(texto=texto, limite=5)
print(json.dumps(resultado, ensure_ascii=False, indent=2))

print("\n2) La misma herramienta, como la llamará el agente:")
print("   el modelo NO ejecuta nada: solo manda un nombre y un texto JSON con los argumentos.\n")
nombre = "buscar_producto"
argumentos_json = json.dumps({"texto": texto, "limite": 5}, ensure_ascii=False)
print(f"   nombre    = {nombre!r}")
print(f"   argumentos= {argumentos_json}\n")
texto_para_el_modelo = ejecutar(nombre, argumentos_json)
print("   Lo que se le devuelve al modelo (un texto, no un objeto de Python):")
print("   " + texto_para_el_modelo[:400] + ("…" if len(texto_para_el_modelo) > 400 else ""))

print("\n3) ¿Y si el modelo se equivoca de nombre de argumento?")
print("   " + ejecutar("buscar_producto", '{"textoo": "espuma"}'))
print("   El error vuelve al modelo como texto, para que se corrija. El programa no se cae.")
