"""
RAG · paso 3 (lección 3): buscar en el índice.

Para cada búsqueda:
  1) convierte la pregunta en vector (1 llamada a NVIDIA),
  2) la compara con los 9.696 vectores guardados (una multiplicación de matrices),
  3) muestra el top-k por significado, junto a lo que trae la búsqueda por palabras actual.

Uso:
    .venv\\Scripts\\python scripts\\ia_rag3_buscar.py
    .venv\\Scripts\\python scripts\\ia_rag3_buscar.py "colchoneta delgada" "algo para que no chille el freno"
    .venv\\Scripts\\python scripts\\ia_rag3_buscar.py --k 15 "espuma 2 cm densidad 15"
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

import django  # noqa: E402

import apps.servidor.settings  # noqa: E402,F401

django.setup()

import numpy as np  # noqa: E402
from openai import OpenAI  # noqa: E402

from modules.ia.config import cargar_config  # noqa: E402
from modules.ia.herramientas import buscar_producto_v1 as buscar_producto  # noqa: E402  (búsqueda antigua, para comparar)

ARCHIVO = Path("data/ia/indice_productos.npz")

args = sys.argv[1:]
k = 10
if "--k" in args:
    i = args.index("--k")
    k = int(args[i + 1])
    del args[i:i + 2]
busquedas = args or [
    "espuma 2 cm densidad 15",
    "colchoneta delgada",
    "algo para que no chille el freno",
    "pastilla freno hilux",
]

# 1) Cargar el índice (se hace una vez; en el Sincronizador quedará en memoria).
t0 = time.perf_counter()
indice = np.load(ARCHIVO)
vectores, ids, nombres = indice["vectores"], indice["ids"], indice["nombres"]
modelo = str(indice["modelo"])
print(f"Índice: {len(ids)} productos · modelo {modelo} · cargado en {time.perf_counter() - t0:.2f}s\n")

cfg = cargar_config()
cliente = OpenAI(base_url=cfg.emb_base_url, api_key=cfg.emb_api_key, timeout=30, max_retries=2)

for busqueda in busquedas:
    # 2) La pregunta se convierte con el MISMO modelo, pero como "query".
    t1 = time.perf_counter()
    r = cliente.embeddings.create(
        model=modelo, input=[busqueda], extra_body={"input_type": "query", "truncate": "END"}
    )
    q = np.array(r.data[0].embedding, dtype=np.float32)
    q /= np.linalg.norm(q)
    t_embed = time.perf_counter() - t1

    # 3) Similitud coseno contra TODOS los productos de una vez.
    #    Como todos los vectores tienen largo 1, coseno = producto punto = vectores @ q.
    t2 = time.perf_counter()
    similitudes = vectores @ q                     # 9.696 números, uno por producto
    top = np.argsort(similitudes)[::-1][:k]        # posiciones de los k más parecidos
    t_busqueda = time.perf_counter() - t2

    print(f"«{busqueda}»   (convertir pregunta {t_embed:.2f}s · comparar con {len(ids)} productos {t_busqueda * 1000:.0f} ms)")
    print("   POR SIGNIFICADO (embeddings)")
    for pos, j in enumerate(top, 1):
        print(f"   {pos:>2}. {similitudes[j]:.3f}  {nombres[j]}  [id {ids[j]}]")

    por_palabras = buscar_producto(busqueda, limite=5)
    print(f"   POR PALABRAS (buscar_producto actual): {por_palabras['total_encontrados']} encontrados")
    for p in por_palabras["productos"]:
        print(f"       · {p['nombre']}  [id {p['id']}]")
    print()
