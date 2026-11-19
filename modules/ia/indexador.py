"""
Índice de embeddings del catálogo con actualización INCREMENTAL (RAG · pieza b).

Idea central: cada vector se guarda junto al TEXTO con que se generó. Al actualizar,
se compara el texto actual de cada producto con el guardado:
  - igual              -> se reutiliza el vector (no cuesta nada)
  - distinto o nuevo   -> se vuelve a convertir
  - producto inactivo  -> se saca del índice
Un día normal con 5 productos nuevos cuesta 1 llamada, no 9.700.

Además es REANUDABLE: guarda el avance después de cada lote. Si el proveedor corta
(límite diario, red caída, cierras la ventana), la próxima ejecución sigue donde quedó.
"""
import ast
import os
import threading
import time
from pathlib import Path

import numpy as np
from openai import RateLimitError

from modules.ia.config import cargar_config
from modules.ia.embeddings import cliente_embeddings, huella, parametros
from logger_config import get_logger
from modules.servidor.models import OdooProducto

logger = get_logger(__name__)

ARCHIVO = Path("data/ia/indice_productos.npz")

# (textos por llamada, segundos mínimos entre llamadas) según el proveedor.
# Gemini gratis: máx. 100 textos por llamada y 100 textos por minuto (cada texto cuenta).
RITMO = {"gemini": (90, 61), "nvidia": (256, 0), "siliconflow": (32, 0)}   # SiliconFlow: máx. 32 por llamada
RITMO_POR_DEFECTO = (100, 0)
MAX_ESPERAS = 3   # 429 seguidos tras esperar: probablemente es el límite DIARIO -> se guarda y se para


def categoria_legible(categ_id: str | None) -> str:
    """En la base viene como texto "[57, 'All / Frenos / Pastillas']" -> 'Frenos / Pastillas'."""
    try:
        _, nombre = ast.literal_eval(categ_id or "")
        return nombre.removeprefix("All / ").removeprefix("All")
    except (ValueError, SyntaxError, TypeError):
        return ""


def texto_a_embeber(nombre: str, categ_id: str | None) -> str:
    """DECISIÓN DE DISEÑO: qué representa a cada producto.

    - Nombre: lo principal.
    - Categoría: aporta significado que el nombre no tiene (ej. 'ORING 391 PULGADA'
      queda junto a 'Frenos / Oring / Pulgadas').
    - Código interno (FH-1009-GTX): NO se incluye. No tiene significado; para buscar
      por código ya está la búsqueda por palabras.
    - Descripción de Mercado Libre: NO se incluye (es larga, la escribe la IA y cambia).
    """
    categoria = categoria_legible(categ_id)
    return f"{nombre} | Categoría: {categoria}" if categoria else (nombre or "")


def _leer(h: str) -> dict[int, tuple[str, np.ndarray]]:
    """{id: (texto, vector)} del índice guardado, o {} si no existe o es de otro modelo."""
    if not ARCHIVO.exists():
        return {}
    with np.load(ARCHIVO) as ind:   # "with": en Windows, un archivo abierto no se puede reemplazar
        if str(ind["modelo"]) != h:
            return {}
        return {int(i): (str(t), v) for i, t, v in zip(ind["ids"], ind["textos"], ind["vectores"])}


def _guardar(datos: dict[int, tuple[str, np.ndarray]], h: str):
    """Escribe a un archivo temporal y lo reemplaza: si se corta a la mitad, el índice no queda roto."""
    ids = sorted(datos)
    ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
    tmp = ARCHIVO.with_name("indice_productos.tmp.npz")
    np.savez(
        tmp,
        vectores=np.array([datos[i][1] for i in ids], dtype=np.float32),
        ids=np.array(ids, dtype=np.int64),
        textos=np.array([datos[i][0] for i in ids]),
        modelo=np.array(h),
    )
    tmp.replace(ARCHIVO)


def actualizar(todo: bool = False, avisar=print) -> dict:
    """Pone el índice al día con el catálogo local. todo=True lo rehace desde cero."""
    cfg = cargar_config()
    if not (cfg.emb_base_url and cfg.emb_api_key):
        raise RuntimeError("Faltan IA_EMB_PROVEEDOR / IA_EMB_API_KEY en el .env")
    h = huella(cfg)
    datos = {} if todo else _leer(h)

    actuales = {
        i: texto_a_embeber(n, c)
        for i, n, c in OdooProducto.objects.filter(activo=True).values_list("id", "name", "categ_id")
    }
    # Seguro: si la copia local está a medio recargar (se borra y se vuelve a llenar), parecería
    # que desaparecieron miles de productos. Mejor no tocar el índice y reintentar después.
    if datos and not todo and len(actuales) < 0.8 * len(datos):
        raise RuntimeError(f"El catálogo local tiene {len(actuales)} productos y el índice {len(datos)}: "
                           "parece estar recargándose. No se actualiza el índice esta vez.")
    quitados = [i for i in datos if i not in actuales]
    for i in quitados:
        del datos[i]
    nuevos = [i for i in actuales if i not in datos]
    cambiados = [i for i, t in actuales.items() if i in datos and datos[i][0] != t]
    pendientes = nuevos + cambiados
    resumen = {"modelo": h, "nuevos": len(nuevos), "cambiados": len(cambiados),
               "quitados": len(quitados), "convertidos": 0, "completo": False}

    avisar(f"Índice {h}: {len(datos) - len(cambiados)} al día · {len(nuevos)} nuevos · "
           f"{len(cambiados)} cambiados · {len(quitados)} quitados")
    if not pendientes:
        if quitados:
            _guardar(datos, h)
        resumen["completo"] = True
        return resumen

    lote, pausa = RITMO.get(cfg.emb_proveedor, RITMO_POR_DEFECTO)
    # Con plan pagado no hace falta la pausa: IA_EMB_POR_MINUTO=0 la quita (o fija otro tope).
    por_minuto = os.getenv("IA_EMB_POR_MINUTO", "").strip()
    if por_minuto:
        n = int(por_minuto)
        lote, pausa = (lote, 0) if n == 0 else (min(lote, n), 61)
    if pausa:
        minutos = -(-len(pendientes) // lote) * pausa / 60
        avisar(f"Ritmo del plan gratis: {lote} por minuto · unos {minutos:.0f} min")
    cliente = cliente_embeddings(cfg, timeout=60, max_retries=0)
    hechos, esperas, ultima, guardado = 0, 0, 0.0, time.monotonic()
    t0 = time.perf_counter()
    while hechos < len(pendientes):
        grupo = pendientes[hechos:hechos + lote]
        falta = pausa - (time.monotonic() - ultima)
        if falta > 0:
            time.sleep(falta)
        ultima = time.monotonic()
        try:
            r = cliente.embeddings.create(input=[actuales[i] for i in grupo], **parametros(cfg, "passage"))
        except RateLimitError:
            esperas += 1
            if esperas > MAX_ESPERAS:
                _guardar(datos, h)
                avisar("El proveedor sigue rechazando (¿límite diario?). Avance guardado: "
                       "vuelve a ejecutar más tarde y seguirá donde quedó.")
                return resumen
            avisar("Límite por minuto alcanzado: espero 65 s…")
            time.sleep(65)
            continue
        esperas = 0
        m = np.array([d.embedding for d in r.data], dtype=np.float32)
        # Largo 1: así la similitud coseno es una simple multiplicación de matrices al buscar.
        m /= np.linalg.norm(m, axis=1, keepdims=True)
        for i, v in zip(grupo, m):
            datos[i] = (actuales[i], v)
        hechos += len(grupo)
        resumen["convertidos"] = hechos
        # Guardar el índice entero (~20 MB) tras cada lote chico era lo más lento: se guarda cada 20 s.
        if time.monotonic() - guardado > 20 or hechos >= len(pendientes):
            _guardar(datos, h)
            guardado = time.monotonic()
            avisar(f"   {hechos:>5}/{len(pendientes)}  ({time.perf_counter() - t0:5.0f}s)")

    resumen["completo"] = True
    return resumen

# ── Actualización automática ────────────────────────────────────────────────
# Se llama al recargar los productos de Odoo, al crear un producto y al abrir la app.
# Corre en un hilo aparte (la app no espera) y nunca dos a la vez: si llega otro aviso
# mientras trabaja, se repite una vez al terminar para tomar también esos cambios.
_trabajando = threading.Lock()
_repetir = False


def actualizar_en_segundo_plano(motivo: str = ""):
    global _repetir
    if not _trabajando.acquire(blocking=False):
        _repetir = True
        return
    threading.Thread(target=_trabajar, args=(motivo,), daemon=True, name="indice-ia").start()


def _trabajar(motivo: str):
    global _repetir
    from django.db import close_old_connections

    from modules.ia import rag

    try:
        while True:
            _repetir = False
            try:
                r = actualizar(avisar=logger.info)
                logger.info("Índice IA (%s): %s nuevos, %s cambiados, %s quitados%s", motivo or "aviso",
                            r["nuevos"], r["cambiados"], r["quitados"], "" if r["completo"] else " (incompleto)")
            except Exception:  # noqa: BLE001 - sin red, sin saldo, sin configurar: el Sincronizador sigue igual
                logger.warning("No se pudo actualizar el índice IA (%s)", motivo, exc_info=True)
            # Siempre: la búsqueda por PALABRAS también se arma con los productos locales.
            rag.recargar()
            if not _repetir:
                break
    finally:
        close_old_connections()
        _trabajando.release()
