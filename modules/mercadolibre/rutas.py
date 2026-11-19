"""
Rutas y configuración compartidas por el Gestor y el Sincronizador ML (.exe).

La carpeta raíz es la del proyecto, o la del .exe cuando corre empaquetado
(el .exe define GESTOR_ROOT antes de importar nada). Ahí viven .env,
credentials.json, data/ y logs/.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path


def raiz() -> Path:
    return Path(os.getenv("GESTOR_ROOT") or Path(__file__).resolve().parents[2])


def ruta_config() -> Path:
    """server_settings.cfg junto al .exe, o el del proyecto (apps/servidor/)."""
    junto = raiz() / "server_settings.cfg"
    proyecto = raiz() / "apps" / "servidor" / "server_settings.cfg"
    return proyecto if proyecto.exists() and not junto.exists() else junto


def leer_config() -> configparser.ConfigParser:
    parser = configparser.ConfigParser()
    parser.optionxform = str
    parser.read(ruta_config(), encoding="utf-8")
    return parser
