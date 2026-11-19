"""
RAG · paso 1 (lección 3): ¿qué es un embedding?

Convierte textos en vectores (listas de números) y mide qué tan parecidos son.
No usa el agente ni la base de datos: solo textos de ejemplo.

Uso:
    .venv\\Scripts\\python scripts\\ia_rag1.py
    .venv\\Scripts\\python scripts\\ia_rag1.py "tu propia búsqueda"

Modelo de embeddings: IA_MODELO_EMBEDDINGS en .env
(por defecto nvidia/nemotron-3-embed-1b, con la misma API key de NVIDIA).
"""
import math
import os
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from openai import OpenAI  # noqa: E402

from modules.ia.config import cargar_config  # noqa: E402

cfg = cargar_config()
MODELO = cfg.emb_modelo
cliente = OpenAI(base_url=cfg.emb_base_url, api_key=cfg.emb_api_key, timeout=30, max_retries=1)

# Nombres reales de tu catálogo (los "documentos").
PRODUCTOS = [
    "ESPUMA 2 CM D 15",
    "ESPUMA 1 CM D 15",
    "ESPUMA 20 CM D 15",
    "ESPUMA 2 CM D 24",
    "ACOPLE CON PUNTA AJUSTABLE PARA INFLAR 20 CM Q1596",
    "PASTILLA DE FRENO DELANTERA TOYOTA HILUX 08/14",
    "GRASA ANTICHIRRIDO FRENOS 10G",
]
# Cómo pregunta una persona (las "consultas").
BUSQUEDAS = sys.argv[1:] or [
    "espuma 2 cm densidad 15",
    "pastilla freno hilux",
    "algo para que no chille el freno",
]


def embeber(textos: list[str], tipo: str) -> list[list[float]]:
    """tipo='passage' para lo que se guarda, 'query' para lo que se busca.

    Este modelo es "asimétrico": codifica distinto una pregunta corta que un
    documento, y rinde mejor si se le dice cuál es cuál.
    """
    r = cliente.embeddings.create(
        model=MODELO, input=textos, extra_body={"input_type": tipo, "truncate": "END"}
    )
    return [d.embedding for d in r.data]


def similitud_coseno(a: list[float], b: list[float]) -> float:
    """1 = mismo significado, 0 = nada que ver. Mide el ángulo entre los dos vectores."""
    producto = sum(x * y for x, y in zip(a, b))
    return producto / (math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b)))


print(f"Modelo de embeddings: {MODELO}\n")
t0 = time.perf_counter()
vec_productos = embeber(PRODUCTOS, "passage")
vec_busquedas = embeber(BUSQUEDAS, "query")
print(f"{len(PRODUCTOS) + len(BUSQUEDAS)} textos convertidos en {time.perf_counter() - t0:.1f}s\n")

v = vec_productos[0]
print(f"1) Así se ve un embedding: '{PRODUCTOS[0]}' =")
print(f"   [{', '.join(f'{x:.3f}' for x in v[:8])}, …]  ({len(v)} números en total)\n")
print("   Ningún número significa algo por sí solo; lo que importa es la DISTANCIA entre vectores.\n")

print("2) Similitud de cada búsqueda con cada producto (de más a menos parecido):\n")
for busqueda, vb in zip(BUSQUEDAS, vec_busquedas):
    print(f"   «{busqueda}»")
    ranking = sorted(
        ((similitud_coseno(vb, vp), nombre) for vp, nombre in zip(vec_productos, PRODUCTOS)),
        reverse=True,
    )
    for i, (sim, nombre) in enumerate(ranking):
        barra = "█" * max(0, round(sim * 40))
        marca = "  ← top 1" if i == 0 else ""
        print(f"     {sim:5.3f} {barra:<24} {nombre}{marca}")
    print()
