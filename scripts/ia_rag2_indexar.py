"""
RAG · paso 2 (lección 3) + pieza b: indexar el catálogo, de forma incremental.

Convierte en embedding SOLO los productos nuevos o cuyo nombre/categoría cambió, quita
los inactivos y reutiliza el resto. La lógica está en modules/ia/indexador.py.

Uso:
    .venv\\Scripts\\python scripts\\ia_rag2_indexar.py          # poner al día (incremental)
    .venv\\Scripts\\python scripts\\ia_rag2_indexar.py --todo   # rehacer desde cero

Si se corta (límite diario del plan gratis, red), vuelve a ejecutarlo: sigue donde quedó.
"""
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

from modules.ia.indexador import ARCHIVO, actualizar  # noqa: E402


def main():
    r = actualizar(todo="--todo" in sys.argv, avisar=lambda m: print(m, flush=True))
    estado = "al día" if r["completo"] else "INCOMPLETO (vuelve a ejecutar más tarde)"
    print(f"\nÍndice {estado} · {r['convertidos']} convertidos · {r['quitados']} quitados")
    if ARCHIVO.exists():
        print(f"{ARCHIVO}  ({ARCHIVO.stat().st_size / 1_048_576:.1f} MB)")


if __name__ == "__main__":
    main()
