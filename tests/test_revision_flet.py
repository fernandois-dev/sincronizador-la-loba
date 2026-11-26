"""
Revisión del código contra la API de Flet instalada, sin abrir la app.

Encuentra nombres que ya no existen (ft.colors, ft.padding.all, ElevatedButton),
argumentos inválidos o posicionales que ahora son solo por nombre, y patrones de
Flet 0.28 que en 1.x fallan.
"""
import ast
import inspect
import re
import warnings

import flet as ft

from tests.apoyo import RAIZ

CARPETAS = ["main.py", "components", "pages", "modules", "router", "apps", "utilities"]

# Hilos que no tocan la pantalla (o código sin uso en el menú).
HILOS_PERMITIDOS = {
    "main.py",
    "modules/servidor/reportes/scheduler.py",
    "modules/ia/indexador.py",          # índice de productos en segundo plano, sin pantalla
    "modules/servidor/google_sheet.py",  # abre las planillas en segundo plano al iniciar, sin pantalla
    "apps/sincronizador_ml/panel.py",   # servidor HTTP del panel web (otro programa)
    "apps/sincronizador_ml/motor.py",   # bucle del sincronizador ML (otro programa)
}

PATRONES_PROHIBIDOS = [
    (r"\bpage\.open\(", "page.open() no existe: usar abrir_dialogo"),
    (r"\bpage\.close\(", "page.close() no existe: usar cerrar_dialogo"),
    (r"\bpage\.go\(", "page.go() no existe: usar page.custom_go"),
    (r"page\.dialog\s*=", "page.dialog no existe"),
    (r"\.update_async\(", "los métodos _async no existen"),
    (r"\bstyle=ft\.TextThemeStyle", "usar theme_style=ft.TextThemeStyle"),
    (r"ft\.Icon\(\s*[\"']", "íconos como texto: usar ft.Icons"),
    (r"\.show_snack_bar\(|page\.snack_bar\b", "no existe en 1.x: usar abrir_dialogo"),
    (r"ft\.FilePicker\(on_result=", "FilePicker es async en 1.x: usar guardar_archivo"),
    (r"threading\.Thread\(|\.run_thread\(", "la pantalla se actualiza desde el loop: usar tarea_async / asyncio.to_thread"),
    (r"super\(\w+, self\.__class__\)\.\w+\.f(set|get)\(", "usar campo_flet()"),
]


def _archivos():
    for nombre in CARPETAS:
        ruta = RAIZ / nombre
        if ruta.is_file():
            yield ruta
        else:
            yield from (p for p in ruta.rglob("*.py") if "__pycache__" not in p.parts)


def _cadena_ft(nodo):
    partes = []
    while isinstance(nodo, ast.Attribute):
        partes.append(nodo.attr)
        nodo = nodo.value
    if isinstance(nodo, ast.Name) and nodo.id == "ft":
        return list(reversed(partes))
    return None


def _resolver(partes):
    obj = ft
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for p in partes:
            if not hasattr(obj, p):
                return None, p
            obj = getattr(obj, p)
    return obj, None


def _firma(obj):
    try:
        params = inspect.signature(obj).parameters
    except (TypeError, ValueError):
        return None
    if any(p.kind == p.VAR_KEYWORD for p in params.values()):
        return None
    posicionales = None if any(p.kind == p.VAR_POSITIONAL for p in params.values()) else sum(
        1 for p in params.values()
        if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD) and p.name != "self")
    return set(params), posicionales


def _revisar(ruta):
    rel = ruta.relative_to(RAIZ)
    if rel.as_posix() == "utilities/flet_compat.py":
        return []  # implementa las adaptaciones: menciona a propósito la API antigua
    src = ruta.read_text(encoding="utf-8")
    problemas = []
    for i, linea in enumerate(src.splitlines(), 1):
        if linea.lstrip().startswith("#"):
            continue
        for patron, motivo in PATRONES_PROHIBIDOS:
            if "threading" in patron and rel.as_posix() in HILOS_PERMITIDOS:
                continue
            if re.search(patron, linea):
                problemas.append(f"{rel}:{i}: {motivo}")
    arbol = ast.parse(src)
    internos = set()
    for nodo in ast.walk(arbol):
        if isinstance(nodo, ast.Attribute) and id(nodo) not in internos:
            partes = _cadena_ft(nodo)
            if partes:
                v = nodo.value
                while isinstance(v, ast.Attribute):
                    internos.add(id(v))
                    v = v.value
                _, falta = _resolver(partes)
                if falta:
                    problemas.append(f"{rel}:{nodo.lineno}: ft.{'.'.join(partes)} no existe")
        if isinstance(nodo, ast.Call):
            partes = _cadena_ft(nodo.func)
            obj, _ = _resolver(partes) if partes else (None, None)
            firma = _firma(obj) if callable(obj) else None
            if not firma:
                continue
            nombres, posicionales = firma
            args = [a for a in nodo.args if not isinstance(a, ast.Starred)]
            if posicionales is not None and len(args) > posicionales:
                problemas.append(f"{rel}:{nodo.lineno}: ft.{'.'.join(partes)}() recibe {len(args)} "
                                 f"argumentos posicionales, acepta {posicionales}")
            for kw in nodo.keywords:
                if kw.arg and kw.arg not in nombres:
                    problemas.append(f"{rel}:{nodo.lineno}: ft.{'.'.join(partes)}() no tiene el argumento '{kw.arg}'")
    return problemas


def test_codigo_compatible_con_flet_instalado():
    problemas = [p for ruta in _archivos() for p in _revisar(ruta)]
    assert problemas == [], "\n".join(problemas)
