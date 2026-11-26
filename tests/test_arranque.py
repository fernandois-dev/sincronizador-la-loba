"""
Arranque rápido: que nada lento quede antes de mostrar la ventana.
"""
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]


def test_importar_la_app_no_carga_librerias_pesadas(tmp_path):
    """openai (IA) y googleapiclient (Drive) se cargan al usarse, no al abrir la app."""
    (tmp_path / "data").mkdir()
    codigo = ("import sys, main; "
              "print([m for m in ('openai', 'googleapiclient.discovery') if m in sys.modules])")
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True, timeout=120,
                       env={**os.environ, "GESTOR_ROOT": str(tmp_path), "DJANGO_ALLOW_ASYNC_UNSAFE": "true"})
    assert r.returncode == 0, r.stderr[-2000:]
    assert r.stdout.strip().splitlines()[-1] == "[]", r.stdout


def test_planillas_se_abren_una_vez_aunque_se_pidan_mientras_se_precalientan(monkeypatch):
    from modules.servidor import google_sheet as gs

    aperturas = []

    def abrir_lento(nombre):
        aperturas.append(nombre)
        time.sleep(0.3)
        gs._wb_cache[nombre] = f"libro-{nombre}"
        return gs._wb_cache[nombre]

    monkeypatch.setattr(gs, "_wb_cache", {})
    monkeypatch.setattr(gs, "_abrir_workbook", abrir_lento)
    # tests/apoyo.py bloquea Google en las pruebas de pantallas: aquí se usa la función real
    monkeypatch.setattr(gs, "_get_workbook", getattr(gs, "_get_workbook_real", gs._get_workbook))

    hilo = threading.Thread(target=gs._precalentar)
    inicio = time.perf_counter()
    hilo.start()
    time.sleep(0.05)
    # la app pide la primera planilla mientras el precalentamiento la está abriendo: espera, no la reabre
    assert gs._get_workbook("workbook") == "libro-workbook"
    assert time.perf_counter() - inicio < 1.0
    hilo.join()
    assert sorted(aperturas) == sorted(gs._SHEETS)          # cada una una sola vez


def test_migraciones_solo_al_cambiar_de_version(monkeypatch, tmp_path):
    import main
    from django.core import management

    llamadas = []
    monkeypatch.setattr(management, "call_command", lambda *a, **k: llamadas.append(a))
    monkeypatch.setattr(main.carpeta_datos, "es_codigo_fuente", lambda: False)
    monkeypatch.setattr(main.carpeta_datos, "carpeta", lambda: tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "database.db").write_bytes(b"")
    monkeypatch.setattr(main, "APP_VERSION", "1.2.0")

    main._migrar_base()                     # primera vez con esta versión: migra
    main._migrar_base()                     # misma versión: no
    assert len(llamadas) == 1
    monkeypatch.setattr(main, "APP_VERSION", "1.3.0")
    main._migrar_base()                     # versión nueva: migra
    assert len(llamadas) == 2
    (tmp_path / "data" / "database.db").unlink()
    main._migrar_base()                     # sin base: migra aunque la versión sea la misma
    assert len(llamadas) == 3
