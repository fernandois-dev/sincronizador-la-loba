"""
Configuración del asistente IA.

Se lee desde el archivo .env de la raíz del proyecto (ignorado por git):

    IA_PROVEEDOR=nvidia
    IA_API_KEY=nvapi-...
    IA_MODELO=deepseek-ai/deepseek-v3.2

Todos los proveedores de la lista hablan el mismo formato (el de OpenAI), así
que cambiar de proveedor es cambiar estas tres líneas, sin tocar código.
"""
import os
from dataclasses import dataclass

from dotenv import load_dotenv

# Ruta explícita: sin ella dotenv busca desde la ubicación del código, que en el
# programa compilado no existe (AssertionError al abrir). Ver utilities/carpeta_datos.py.
from modules.mercadolibre.rutas import raiz as _raiz
load_dotenv(_raiz() / ".env")

# Proveedores con API compatible con OpenAI: solo cambia la URL base.
PROVEEDORES = {
    "nvidia": "https://integrate.api.nvidia.com/v1",
    "groq": "https://api.groq.com/openai/v1",
    "cerebras": "https://api.cerebras.ai/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "siliconflow": "https://api.siliconflow.com/v1",   # embeddings Qwen3 (sitio internacional)
    "openrouter": "https://openrouter.ai/api/v1",
    "ollama": "http://localhost:11434/v1",
}


class ConfigIAError(Exception):
    """Falta o está mal un valor de configuración del asistente."""


@dataclass(frozen=True)
class ConfigIA:
    proveedor: str
    base_url: str
    api_key: str
    modelo: str
    max_pasos: int = 6          # vueltas máximas del loop por pregunta
    temperatura: float = 0.2    # baja: queremos respuestas consistentes, no creativas
    # Embeddings (búsqueda por significado): pueden ir en OTRO proveedor que el chat.
    # Ej.: chat en Groq y embeddings en NVIDIA. Si faltan, la búsqueda usa solo palabras.
    emb_proveedor: str = ""
    emb_base_url: str = ""
    emb_api_key: str = ""
    emb_modelo: str = ""
    emb_dimensiones: int = 0    # 0 = el largo nativo del modelo; Gemini acepta ej. 768 (índice 4x más chico)
    # Respaldo: si el proveedor principal falla o llega a su límite, se usa este al instante.
    resp_proveedor: str = ""
    resp_base_url: str = ""
    resp_api_key: str = ""
    resp_modelo: str = ""


def cargar_config() -> ConfigIA:
    proveedor = os.getenv("IA_PROVEEDOR", "nvidia").strip().lower()
    base_url = os.getenv("IA_BASE_URL", "").strip() or PROVEEDORES.get(proveedor)
    if not base_url:
        raise ConfigIAError(
            f"Proveedor desconocido '{proveedor}'. Usa uno de {', '.join(PROVEEDORES)} "
            "o define IA_BASE_URL en .env."
        )

    api_key = os.getenv("IA_API_KEY", "").strip()
    if not api_key:
        if proveedor != "ollama":
            raise ConfigIAError("Falta IA_API_KEY en el archivo .env.")
        api_key = "ollama"  # Ollama no valida la key, pero el cliente exige una

    modelo = os.getenv("IA_MODELO", "").strip()
    if not modelo:
        raise ConfigIAError("Falta IA_MODELO en el archivo .env (ej. deepseek-ai/deepseek-v3.2).")

    resp_proveedor = os.getenv("IA_RESPALDO_PROVEEDOR", "").strip().lower()
    if resp_proveedor and resp_proveedor not in PROVEEDORES:
        raise ConfigIAError(f"IA_RESPALDO_PROVEEDOR desconocido '{resp_proveedor}'. Usa uno de {', '.join(PROVEEDORES)}.")

    # Por defecto, los embeddings usan el mismo proveedor y key que el chat.
    emb_proveedor = os.getenv("IA_EMB_PROVEEDOR", "").strip().lower() or proveedor
    emb_base_url = os.getenv("IA_EMB_BASE_URL", "").strip() or PROVEEDORES.get(emb_proveedor, "")
    emb_api_key = os.getenv("IA_EMB_API_KEY", "").strip() or (api_key if emb_proveedor == proveedor else "")

    return ConfigIA(
        proveedor=proveedor,
        base_url=base_url,
        api_key=api_key,
        modelo=modelo,
        emb_proveedor=emb_proveedor,
        emb_base_url=emb_base_url,
        emb_api_key=emb_api_key,
        emb_modelo=os.getenv("IA_MODELO_EMBEDDINGS", "").strip() or "nvidia/nemotron-3-embed-1b",
        emb_dimensiones=int(os.getenv("IA_EMB_DIMENSIONES", "0") or 0),
        resp_proveedor=resp_proveedor,
        resp_base_url=PROVEEDORES.get(resp_proveedor, "") if resp_proveedor else "",
        # Si el respaldo es del mismo proveedor (ej. otro modelo de Groq), reutiliza la misma key.
        resp_api_key=os.getenv("IA_RESPALDO_API_KEY", "").strip() or (api_key if resp_proveedor == proveedor else ""),
        resp_modelo=os.getenv("IA_RESPALDO_MODELO", "").strip(),
        max_pasos=int(os.getenv("IA_MAX_PASOS", "6")),
        temperatura=float(os.getenv("IA_TEMPERATURA", "0.2")),
    )
