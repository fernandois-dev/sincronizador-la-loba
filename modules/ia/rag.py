"""
Búsqueda híbrida de productos (RAG · paso 4).

Combina dos búsquedas que se complementan:
  - por PALABRAS: palabras completas del nombre y el código (buena con medidas,
    códigos y abreviaturas exactas: "2 CM", "D 15", "FH-1009-GTX").
  - por SIGNIFICADO: embeddings del índice de data/ia/indice_productos.npz
    (buena con sinónimos y escrituras distintas: "densidad"≈"D", "HILUX"≈"HI-LUX").

Las dos listas se mezclan con Reciprocal Rank Fusion (RRF), que usa solo la
POSICIÓN de cada producto en cada lista, porque sus puntajes no son comparables.
"""
import math
import os
import re
import threading
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from modules.ia.config import cargar_config
from modules.ia.embeddings import cliente_embeddings, huella, parametros, preparar_consulta, umbral_relevancia
from modules.servidor.models import OdooProducto

ARCHIVO_INDICE = Path("data/ia/indice_productos.npz")
K_CANDIDATOS = 50          # cuántos candidatos aporta cada búsqueda antes de mezclar
RRF_K = 60                 # constante estándar de RRF: suaviza la diferencia entre posiciones
# El umbral de "probablemente no existe" depende del modelo: ver embeddings.umbral_relevancia().

_PALABRA = re.compile(r"[A-Z0-9Ñ]+")


# Palabras que no aportan a la búsqueda. Ojo: "DEL" NO va aquí: en el catálogo significa "delantero".
_VACIAS = {"DE", "LA", "EL", "LOS", "LAS", "PARA", "POR", "CON", "Y", "O", "UN", "UNA", "EN", "AL", "QUE"}


# Sinónimos del dominio (el glosario aplicado a la búsqueda): la forma larga que usa una persona
# y la abreviatura del catálogo pasan a ser la misma palabra, en la pregunta y en el catálogo.
_SINONIMOS = {
    "DENSIDAD": "D", "DELANTERO": "DEL", "DELANTERA": "DEL", "TRASERO": "TRAS", "TRASERA": "TRAS",
    "PULGADA": "PULG", "JUEGO": "JGO", "CENTIMETRO": "CM", "MILIMETRO": "MM",
    "TOYOTA": "TOY", "CHEVROLET": "CHEV", "CHEVR": "CHEV", "MITSUBISHI": "MITSUB", "PASTILLA": "PAST",
}


def _raiz(palabra: str) -> str:
    """Singular simple, para que 'FRENOS' calce con 'FRENO' y 'MOTORES' con 'MOTOR'.

    Se aplica igual a la pregunta y al catálogo, así que basta con que sea consistente.
    """
    if len(palabra) > 3 and palabra.isalpha():
        if palabra.endswith("ES") and palabra[-3] in "RLNDZJ":
            palabra = palabra[:-2]
        elif palabra.endswith("S"):
            palabra = palabra[:-1]
    return _SINONIMOS.get(palabra, palabra)


def _palabras_en_orden(texto: str) -> list[str]:
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.upper()) if not unicodedata.combining(c)
    )
    return [_raiz(p) for p in _PALABRA.findall(sin_tildes) if p not in _VACIAS]


def _palabras(texto: str) -> set[str]:
    """'Pastillas de freno HI-LUX 4x4' -> {'PASTILLA','FRENO','HI','LUX','4X4'} (sin tildes, en singular)."""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFKD", texto.upper()) if not unicodedata.combining(c)
    )
    return {_raiz(p) for p in _PALABRA.findall(sin_tildes) if p not in _VACIAS}


def _parece_codigo(texto: str) -> bool:
    """'PF-21160' o 'GOMRIQ-00-2012' parecen código; 'frenos mahindra 2012' no."""
    return bool(re.search(r"[A-Z0-9]+-[A-Z0-9]", texto.upper())) or len(texto.split()) == 1


@dataclass
class Candidato:
    id: int
    nombre: str
    codigo: str
    precio: float
    similitud: float           # coseno con la pregunta (0-1), de la búsqueda por significado
    palabras_coinciden: int    # cuántas palabras de la pregunta aparecen completas
    puntaje_rrf: float
    favorito: bool = False


@dataclass
class ResultadoBusqueda:
    candidatos: list[Candidato]
    mejor_similitud: float
    modo: str                  # "híbrida" o "solo palabras" (si no hay índice o falla NVIDIA)
    relevancia_baja: bool      # nada se parece en significado NI contiene todas las palabras


class _Catalogo:
    """Se carga una vez y queda en memoria: productos activos + índice de vectores."""

    def __init__(self):
        filas = OdooProducto.objects.filter(activo=True).values_list(
            "id", "name", "default_code", "list_price", "barcode", "favorito"
        )
        self.productos = {i: (n or "", c or "", float(p or 0)) for i, n, c, p, _, _ in filas}
        self.favoritos = {i for i, *_, fav in filas if fav}
        # Código interno y código de barras -> id, para coincidencias exactas.
        self.por_codigo = {}
        for i, _, c, _, b, _ in filas:
            for codigo in (c, b):
                if codigo:
                    self.por_codigo.setdefault(codigo.strip().upper(), i)
        # Nombre y código por separado: los números de un código ("…-2012/B") no deben calzar
        # con un año pedido ("mahindra 2012"). El código solo cuenta si lo buscado parece código.
        self.palabras = {i: _palabras(n) for i, (n, c, _) in self.productos.items()}
        self.palabras_codigo = {i: _palabras(c) for i, (n, c, _) in self.productos.items()}
        # IDF: una palabra rara ("MAHINDRA", en 9 productos) pesa más que una común ("2012",
        # "FRENO"). Es el mismo principio de los buscadores clásicos (TF-IDF, BM25).
        apariciones: dict[str, int] = {}
        for palabras in self.palabras.values():
            for p in palabras:
                apariciones[p] = apariciones.get(p, 0) + 1
        total = len(self.palabras) or 1
        self.idf = {p: math.log(total / n) for p, n in apariciones.items()}

        self.vectores = self.ids_indice = None
        self.modelo = None
        self.umbral = 0.45
        cfg = cargar_config()
        # Sin proveedor de embeddings configurado, la búsqueda queda en "solo palabras".
        if ARCHIVO_INDICE.exists() and cfg.emb_base_url and cfg.emb_api_key:
            # "with": libera el archivo, para que el indexador pueda reemplazarlo con la app abierta.
            with np.load(ARCHIVO_INDICE) as indice:
                # Un índice hecho con otro modelo (u otro largo) no se compara con la pregunta:
                # serían "idiomas" distintos. Se ignora hasta reindexar.
                if str(indice["modelo"]) == huella(cfg):
                    self.vectores = indice["vectores"]
                    self.ids_indice = indice["ids"]
                    self.modelo = huella(cfg)
                    self.cfg = cfg
                    self.umbral = umbral_relevancia(cfg)
                    self.cliente = cliente_embeddings(cfg)

    # ── Búsqueda por palabras ───────────────────────────────────────────────
    def por_palabras(self, texto: str, k: int) -> list[tuple[int, int]]:
        """[(id, palabras que coinciden)]; primero los que coinciden en palabras más raras (IDF)."""
        buscadas = _palabras(texto)
        con_codigo = _parece_codigo(texto)
        puntajes = []
        for pid, palabras in self.palabras.items():
            if con_codigo:
                palabras = palabras | self.palabras_codigo[pid]
            comunes = buscadas & palabras
            if comunes:
                peso = sum(self.idf.get(p, 1.0) for p in comunes)
                puntajes.append((peso, len(comunes), -len(self.productos[pid][0]), pid))  # empate: nombre más corto
        puntajes.sort(reverse=True)
        return [(pid, n) for _, n, _, pid in puntajes[:k]]

    # ── Búsqueda por significado ────────────────────────────────────────────
    def similitudes(self, texto: str) -> np.ndarray:
        """Coseno de la pregunta contra todo el índice (un número por producto indexado)."""
        r = self.cliente.embeddings.create(input=[preparar_consulta(self.cfg, texto)], **parametros(self.cfg, "query"))
        q = np.array(r.data[0].embedding, dtype=np.float32)
        q /= np.linalg.norm(q)
        return self.vectores @ q

    def _relevancia_baja_por_palabras(self, texto: str, candidatos: list, exacto) -> bool:
        """Señal de "probablemente no existe" cuando no hay embeddings (modo solo palabras).

        - Si el mejor resultado no contiene una palabra que SÍ existe en el catálogo
          ("frenos mahindra 2012": hay Mahindra, pero ninguna 2012) -> aviso.
        - Las palabras que no existen en ningún producto ("densidad") se ignoran, salvo que sean
          la mayoría o la primera de la pregunta ("colchoneta delgada") -> aviso.
        """
        if exacto is not None or _parece_codigo(texto):
            return False
        buscadas = _palabras_en_orden(texto)
        if not buscadas or not candidatos:
            return True
        desconocidas = [p for p in buscadas if p not in self.idf]
        if buscadas[0] in desconocidas or 2 * len(desconocidas) >= len(buscadas):
            return True
        conocidas = set(buscadas) - set(desconocidas)
        return bool(conocidas - self.palabras[candidatos[0].id])

    # ── Híbrida ─────────────────────────────────────────────────────────────
    def buscar(self, texto: str, limite: int, solo_favoritos: bool = False) -> ResultadoBusqueda:
        lista_palabras = self.por_palabras(texto, K_CANDIDATOS)
        coinciden = dict(lista_palabras)

        similitud_de: dict[int, float] = {}
        lista_significado: list[int] = []
        modo = "solo palabras"
        if self.vectores is not None:
            try:
                sims = self.similitudes(texto)
                similitud_de = {int(i): float(s) for i, s in zip(self.ids_indice, sims)}
                orden = np.argsort(sims)[::-1]
                lista_significado = [
                    int(self.ids_indice[j]) for j in orden[: K_CANDIDATOS * 2]
                    if int(self.ids_indice[j]) in self.productos   # descarta productos ya inactivos
                ][:K_CANDIDATOS]
                modo = "híbrida"
            except Exception:  # noqa: BLE001 - sin red o NVIDIA caído: seguimos solo con palabras
                pass

        # Reciprocal Rank Fusion: suma 1/(60 + posición) por cada lista en que aparece.
        rrf: dict[int, float] = {}
        for posicion, pid in enumerate(lista_significado, 1):
            rrf[pid] = rrf.get(pid, 0) + 1 / (RRF_K + posicion)
        for posicion, (pid, _) in enumerate(lista_palabras, 1):
            rrf[pid] = rrf.get(pid, 0) + 1 / (RRF_K + posicion)

        mejores = sorted(rrf, key=rrf.get, reverse=True)
        # Un código interno o de barras exacto va siempre primero: RRF lo castiga si
        # solo aparece en la lista por palabras (los códigos no tienen "significado").
        exacto = self.por_codigo.get(texto.strip().upper())
        if exacto is not None:
            rrf.setdefault(exacto, 0.0)
            mejores = [exacto] + [p for p in mejores if p != exacto]
        if solo_favoritos:
            mejores = [p for p in mejores if p in self.favoritos]
        mejores = mejores[:limite]
        candidatos = [
            Candidato(
                id=pid,
                nombre=self.productos[pid][0],
                codigo=self.productos[pid][1],
                precio=self.productos[pid][2],
                similitud=round(similitud_de.get(pid, 0.0), 3),
                palabras_coinciden=coinciden.get(pid, 0),
                puntaje_rrf=round(rrf[pid], 4),
                favorito=pid in self.favoritos,
            )
            for pid in mejores
        ]
        mejor = max((c.similitud for c in candidatos), default=0.0)
        # Relevancia baja = dos señales a la vez. Solo la similitud no basta: una búsqueda
        # de una palabra ("espuma") saca similitud baja aunque el resultado sea perfecto.
        total_palabras = len(_palabras(texto))
        alguno_completo = exacto is not None or any(
            c.palabras_coinciden == total_palabras for c in candidatos
        )
        if modo == "híbrida":
            baja = mejor < self.umbral and not alguno_completo
        else:
            baja = self._relevancia_baja_por_palabras(texto, candidatos, exacto)
        return ResultadoBusqueda(candidatos, mejor, modo, baja)


_catalogo: _Catalogo | None = None
_lock = threading.Lock()


def catalogo() -> _Catalogo:
    """El catálogo se carga la primera vez que se usa (unos 0,5 s) y luego se reutiliza."""
    global _catalogo
    with _lock:
        if _catalogo is None:
            _catalogo = _Catalogo()
        return _catalogo


def recargar():
    """Para después de reindexar o sincronizar productos (paso 5)."""
    global _catalogo
    with _lock:
        _catalogo = None
