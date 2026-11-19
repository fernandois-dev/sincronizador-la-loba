"""
Embeddings: el único lugar que sabe cómo hablarle a cada proveedor.

Todos usan el formato de OpenAI, pero cada uno acepta parámetros extra distintos:
  - NVIDIA pide input_type ("query" para la pregunta, "passage" para el catálogo) y truncate.
  - Gemini rechaza esos campos (error 400) y acepta `dimensions` para pedir vectores más cortos.

Vectores de modelos (o largos) distintos NO se pueden comparar entre sí: por eso el índice
guarda su "huella" y se descarta si no coincide con la configuración actual.
"""
from openai import OpenAI

from modules.ia.config import ConfigIA


def cliente_embeddings(cfg: ConfigIA, timeout: int = 30, max_retries: int = 1) -> OpenAI:
    return OpenAI(base_url=cfg.emb_base_url, api_key=cfg.emb_api_key, timeout=timeout, max_retries=max_retries)


def parametros(cfg: ConfigIA, tipo: str) -> dict:
    """Argumentos para embeddings.create(). tipo: "query" (pregunta) o "passage" (producto)."""
    p: dict = {"model": cfg.emb_modelo}
    if cfg.emb_dimensiones:
        p["dimensions"] = cfg.emb_dimensiones
    if cfg.emb_proveedor == "nvidia":
        p["extra_body"] = {"input_type": tipo, "truncate": "END"}
    return p


# Qwen3-Embedding rinde mejor si la PREGUNTA (no el catálogo) lleva una instrucción de la tarea.
# Medido el 12-nov: sin ella, "engrapadora" o "bicicleta" traían productos basura con nombres tipo
# código ("ce'2994'k"); con ella, los correctos, y lo inexistente ("refrigerador") puntúa más bajo.
_INSTRUCCION_QWEN = (
    "Instruct: Given a product search query from a hardware store employee in Spanish, "
    "retrieve the catalog products that match it\nQuery: "
)

# Umbral de "probablemente no existe" (similitud de la mejor coincidencia), medido por modelo.
_UMBRALES = {"qwen3-embedding": 0.52}   # 12-nov: correctos 0,55-0,73; inexistentes 0,47-0,49
UMBRAL_POR_DEFECTO = 0.45               # medido con NVIDIA nemotron (3-nov)


def preparar_consulta(cfg: ConfigIA, texto: str) -> str:
    return _INSTRUCCION_QWEN + texto if "qwen3-embedding" in cfg.emb_modelo.lower() else texto


def umbral_relevancia(cfg: ConfigIA) -> float:
    modelo = cfg.emb_modelo.lower()
    return next((u for clave, u in _UMBRALES.items() if clave in modelo), UMBRAL_POR_DEFECTO)


def huella(cfg: ConfigIA) -> str:
    """Identifica el 'espacio' de los vectores: modelo + largo. Ej.: 'gemini-embedding-2|768'."""
    return f"{cfg.emb_modelo}|{cfg.emb_dimensiones or 'nativo'}"
