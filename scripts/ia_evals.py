"""
Evals del asistente (lección 8): pruebas automáticas con preguntas de respuesta conocida.

Uso (desde la carpeta del proyecto):
    .venv\\Scripts\\python scripts\\ia_evals.py                 # todos los casos, 1 vez
    .venv\\Scripts\\python scripts\\ia_evals.py --veces 3       # cada caso 3 veces (el LLM no siempre responde igual)
    .venv\\Scripts\\python scripts\\ia_evals.py grasa martillo  # solo los casos cuyo id contenga esas palabras

Los casos están en evals/casos.json. El resultado detallado queda en data/ia/evals/.
Córrelo cada vez que cambies el prompt, una herramienta o el modelo: así sabes si algo empeoró.
"""
import json
import os
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
os.chdir(RAIZ)
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

import django  # noqa: E402

import apps.servidor.settings  # noqa: E402,F401

django.setup()

from modules.ia.agente import Agente  # noqa: E402

CASOS = Path("evals/casos.json")
SALIDA = Path("data/ia/evals")


def _valor(datos, campo: str):
    """'ultimas_compras.0.proveedor' -> datos['ultimas_compras'][0]['proveedor']."""
    for parte in campo.split("."):
        datos = datos[int(parte)] if isinstance(datos, list) else datos[parte]
    return datos


def _normalizar(texto: str) -> str:
    """Sin tildes ni mayúsculas: 'FERRETERÍA' y 'Ferreteria' cuentan como lo mismo."""
    return "".join(c for c in unicodedata.normalize("NFKD", str(texto)) if not unicodedata.combining(c)).lower()


def _variantes(valor) -> list[str]:
    """Formas en que un dato puede aparecer escrito: 1234 -> '1234', '1.234'; 23.5 -> '23.5', '23,5'."""
    if isinstance(valor, (int, float)):
        if float(valor).is_integer():
            n = int(valor)
            return list({str(n), f"{n:,}".replace(",", ".")})
        return [f"{valor:g}", f"{valor:g}".replace(".", ",")]
    texto = str(valor).strip()
    return [texto[:20]]          # nombres largos: basta con el comienzo (ej. el proveedor)


def evaluar(caso: dict, respuesta) -> list[str]:
    """Devuelve la lista de fallas (vacía = el caso pasó)."""
    fallas = []
    texto = respuesta.texto or ""
    usadas = [p.nombre for p in respuesta.pasos]
    resultados = {}
    for p in respuesta.pasos:
        try:
            resultados[p.nombre] = json.loads(p.resultado)
        except json.JSONDecodeError:
            pass

    for h in caso.get("herramientas", []):
        if h not in usadas:
            fallas.append(f"no usó {h} (usó {usadas or 'ninguna'})")
    if caso.get("alguna_herramienta") and not set(caso["alguna_herramienta"]) & set(usadas):
        fallas.append(f"no usó ninguna de {caso['alguna_herramienta']}")
    if caso.get("empieza_con") and not re.match(caso["empieza_con"], texto.strip(), re.I):
        fallas.append(f"no empieza con /{caso['empieza_con']}/: «{texto.strip()[:50]}…»")
    for patron in caso.get("contiene", []):
        if not re.search(patron, texto, re.I):
            fallas.append(f"no contiene /{patron}/")
    for patron in caso.get("no_contiene", []):
        if re.search(patron, texto, re.I):
            fallas.append(f"contiene lo prohibido /{patron}/")
    for d in caso.get("dato_de_herramienta", []):
        if d["herramienta"] not in resultados:
            fallas.append(f"sin resultado de {d['herramienta']} para comparar")
            continue
        try:
            valor = _valor(resultados[d["herramienta"]], d["campo"])
        except (KeyError, IndexError, ValueError, TypeError):
            fallas.append(f"{d['herramienta']} no trajo {d['campo']}")
            continue
        if not any(_normalizar(v) in _normalizar(texto) for v in _variantes(valor)):
            fallas.append(f"el texto no menciona el dato real {d['campo']} = {valor!r}")
    return fallas


def main():
    args = sys.argv[1:]
    veces = 1
    if "--veces" in args:
        i = args.index("--veces")
        veces = int(args[i + 1])
        del args[i:i + 2]
    casos = json.loads(CASOS.read_text(encoding="utf-8"))["casos"]
    if args:
        casos = [c for c in casos if any(a.lower() in c["id"].lower() for a in args)]

    agente = Agente()
    print(f"Evals · {len(casos)} casos × {veces} vez/veces · {agente.cfg.proveedor} {agente.cfg.modelo}\n")
    detalle, pasaron, total, t_inicio = [], 0, 0, time.perf_counter()
    for caso in casos:
        ok_caso = 0
        for intento in range(veces):
            agente.reiniciar()                       # cada intento parte sin historial
            try:
                r = agente.preguntar(caso["pregunta"])
                fallas = evaluar(caso, r)
                extra = {"herramientas": [p.nombre for p in r.pasos], "tokens_entrada": r.uso.tokens_entrada,
                         "segundos": round(r.segundos_total, 1), "via": r.uso.proveedores, "texto": r.texto}
            except Exception as exc:  # noqa: BLE001 - un error cuenta como falla, no detiene los evals
                fallas, extra = [f"error {type(exc).__name__}: {exc}"], {}
            total += 1
            ok = not fallas
            pasaron += ok
            ok_caso += ok
            detalle.append({"id": caso["id"], "intento": intento + 1, "ok": ok, "fallas": fallas, **extra})
            marca = "✅" if ok else "❌"
            print(f"{marca} {caso['id']:24} {extra.get('segundos', '-'):>5}s  {extra.get('via', '')}")
            for f in fallas:
                print(f"      · {f}")
        if veces > 1:
            print(f"   → {caso['id']}: {ok_caso}/{veces}")

    print(f"\nResultado: {pasaron}/{total} ({100 * pasaron / max(total, 1):.0f} %) · "
          f"{time.perf_counter() - t_inicio:.0f}s en total")
    SALIDA.mkdir(parents=True, exist_ok=True)
    archivo = SALIDA / f"evals_{datetime.now():%Y%m%d_%H%M}.json"
    archivo.write_text(json.dumps({"modelo": agente.cfg.modelo, "pasaron": pasaron, "total": total,
                                   "detalle": detalle}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Detalle en {archivo}")


if __name__ == "__main__":
    main()
