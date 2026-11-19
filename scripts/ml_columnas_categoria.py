"""
Agrega a una pestaña de la Tabla Base las columnas estándar de Mercado Libre de su categoría.

El set estándar por categoría está en apps/servidor/server_settings.cfg, sección
[MERCADOLIBRE_COLUMNAS] (p. ej. MLC1642 = Forma=Rectangular, Largo, Ancho, …).

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\ml_columnas_categoria.py "ESPUMA BASE 2026"            # usa la categoría de la pestaña
    .venv\\Scripts\\python scripts\\ml_columnas_categoria.py "ESPUMA BASE 2026" MLC1642    # categoría explícita

Solo agrega columnas que falten (a la derecha), con listas desplegables y notas, y escribe el
valor por defecto en celdas vacías de las filas de esa categoría. No modifica nada más.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from modules.mercadolibre.catalogo import preparar_columnas  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    r = preparar_columnas(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
    if r.get("error"):
        sys.exit(f"✖ {r['error']}")
    print(f"Categoría: {r['categoria']}")
    print("✔ Columnas agregadas:", ", ".join(r["agregadas"]) or "ninguna")
    if r["existentes"]:
        print("  Ya existían:", ", ".join(r["existentes"]))
    if r.get("desconocidas"):
        print("⚠ No son datos de la categoría en Mercado Libre:", ", ".join(r["desconocidas"]))
