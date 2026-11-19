"""
logger_config.py — Configuración central de logging para Gestor La Loba.

Uso en cualquier módulo:
    from logger_config import get_logger
    logger = get_logger(__name__)
"""
import logging
import os
import logging.handlers
from pathlib import Path

# ── Directorio y archivo de log ────────────────────────────────────────────────
LOG_DIR = Path(os.getenv("GESTOR_ROOT") or Path(__file__).parent) / "logs"  # GESTOR_ROOT: .exe del Sincronizador ML
LOG_DIR.mkdir(exist_ok=True)           # Crea /logs si no existe
LOG_FILE = LOG_DIR / "app.log"

# ── Formato detallado ──────────────────────────────────────────────────────────
_FMT = "%(asctime)s | %(levelname)-8s | %(name)s:%(lineno)d | %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ── Logger raíz de la aplicación ───────────────────────────────────────────────
_APP_LOGGER = "gestor_loba"


def _build_logger() -> logging.Logger:
    logger = logging.getLogger(_APP_LOGGER)

    # Evitar duplicar handlers si el módulo se reimporta
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)       # Captura todo; los handlers filtran

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # FileHandler — rotación diaria, 30 días de historial
    file_handler = logging.handlers.TimedRotatingFileHandler(
        LOG_FILE,
        when="midnight",
        backupCount=30,
        encoding="utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)

    # StreamHandler — solo INFO+ en consola para no saturar la terminal
    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(logging.INFO)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger


# Inicializar al importar
_build_logger()


def get_logger(name: str) -> logging.Logger:
    """
    Retorna un logger hijo del logger raíz de la app.

    Args:
        name: Usa siempre __name__ para obtener el nombre del módulo.

    Returns:
        logging.Logger listo para usar.

    Ejemplo:
        logger = get_logger(__name__)
        logger.info("Aplicación iniciada")
        logger.debug("Intentando conexión a %s", url)
        logger.error("Falló XML-RPC", exc_info=True)
    """
    return logging.getLogger(f"{_APP_LOGGER}.{name}")
