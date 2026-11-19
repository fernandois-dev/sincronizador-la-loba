"""
Sincronizador ML — programa de bandeja para Windows.

Corre siempre (parte al iniciar sesión): cada 5 minutos pasa las ventas de
Mercado Libre a Odoo y el stock de Odoo a Mercado Libre. Indicador junto al reloj:
  azul = sin novedades · verde = movimientos de ML sin ver · rojo = errores · gris = pausado
Doble clic: abre el panel (http://localhost:8765) con movimientos, sincronizaciones y log.

Necesita en su carpeta: .env (ML_*), credentials.json y server_settings.cfg ([ODOO], [MERCADOLIBRE]).
Desde el proyecto: python -m apps.sincronizador_ml.main
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ── carpeta de trabajo: la del .exe, o la del proyecto ─────────────────────────
BASE = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[2]
os.environ.setdefault("GESTOR_ROOT", str(BASE))
os.chdir(BASE)
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if sys.stdout is None:  # .exe sin consola
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import webbrowser  # noqa: E402

from PIL import Image, ImageDraw  # noqa: E402
import pystray  # noqa: E402

from apps.sincronizador_ml.motor import Motor  # noqa: E402
from apps.sincronizador_ml.panel import PUERTO, iniciar_en_segundo_plano, servidor  # noqa: E402

URL = f"http://localhost:{PUERTO}"
COLORES = {"azul": (45, 127, 249), "verde": (31, 157, 85), "rojo": (229, 72, 77), "gris": (138, 143, 152)}
TEXTOS = {"azul": "sin novedades", "verde": "movimientos nuevos de Mercado Libre",
          "rojo": "hay errores", "gris": "pausado"}


def icono(color: str) -> Image.Image:
    lado = 64
    img = Image.new("RGBA", (lado, lado), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, lado - 4, lado - 4), fill=COLORES[color] + (255,), outline=(255, 255, 255, 255), width=5)
    return img


def main():
    try:
        motor = Motor()
        srv = servidor(motor)
    except OSError:
        webbrowser.open(URL)  # ya hay una copia corriendo: abrir su panel
        return

    tray = pystray.Icon("SincronizadorML", icono("azul"), "Sincronizador ML")
    color_actual = {"v": None}

    def refrescar():
        c = motor.color()
        if c != color_actual["v"]:
            tray.icon = icono(c)
            color_actual["v"] = c
        tray.title = f"Sincronizador ML: {TEXTOS[c]}\n{motor.resumen}"[:127]
        tray.update_menu()

    def avisar_venta(texto):
        try:
            tray.notify(texto, "Mercado Libre")
        except Exception:
            pass

    motor._al_cambiar = refrescar
    motor._al_vender = avisar_venta

    tray.menu = pystray.Menu(
        pystray.MenuItem("Abrir panel", lambda: webbrowser.open(URL), default=True),
        pystray.MenuItem("Sincronizar ahora", lambda: motor.sincronizar_ahora()),
        pystray.MenuItem("Marcar como visto", lambda: motor.marcar_visto()),
        pystray.MenuItem("Pausar", lambda: motor.alternar_pausa(), checked=lambda _: motor.pausado),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Salir", lambda: (srv.shutdown(), tray.stop())),
    )

    def al_iniciar(icon):
        icon.visible = True
        iniciar_en_segundo_plano(srv)
        motor.iniciar()

    tray.run(setup=al_iniciar)


if __name__ == "__main__":
    main()
