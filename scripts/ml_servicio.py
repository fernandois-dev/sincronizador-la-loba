"""
Servicio Mercado Libre ↔ Odoo.

    python scripts/ml_servicio.py               # en bucle, cada 5 minutos (para el Linux)
    python scripts/ml_servicio.py --una-vez     # una pasada y termina
    python scripts/ml_servicio.py --simular     # una pasada sin escribir en Odoo
    python scripts/ml_servicio.py --simular --dias 10   # mirar los últimos 10 días

Ventas de ML → órdenes de venta confirmadas en Odoo (ver modules/mercadolibre/ventas.py).
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)  # la app lee apps/servidor/server_settings.cfg relativo a la carpeta del proyecto
sys.path.insert(0, str(ROOT))

from modules.mercadolibre.ventas import servicio, sincronizar_ventas  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--una-vez", action="store_true", help="una pasada y termina")
    ap.add_argument("--simular", action="store_true", help="no escribe en Odoo (implica --una-vez)")
    ap.add_argument("--dias", type=float, help="revisar las órdenes de los últimos N días")
    ap.add_argument("--cada", type=int, default=300, help="segundos entre pasadas (por defecto 300)")
    a = ap.parse_args()

    if a.una_vez or a.simular or a.dias:
        desde = datetime.now(timezone.utc) - timedelta(days=a.dias) if a.dias else None
        eventos = sincronizar_ventas(desde=desde, simular=a.simular)
        print("\n".join(e["texto"] for e in eventos) if eventos else "Sin ventas nuevas.")
    else:
        servicio(a.cada)


if __name__ == "__main__":
    main()
