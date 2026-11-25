"""
Cliente de la API de Mercado Libre Chile (sitio MLC).

Credenciales (en .env, que NO se sube a git):
    ML_CLIENT_ID      = Client ID de la app en developers.mercadolibre.cl
    ML_CLIENT_SECRET  = Client Secret de la misma app
    ML_REDIRECT_URI   = URI de redirect, idéntica a la configurada en la app
    ML_USAR_PKCE      = 1 si en la app está activado "PKCE" (opcional)

    ML_TOKENS_DRIVE_FOLDER = id de la carpeta de Drive con ml_tokens.json (opcional,
                             para compartir la conexión entre computadores)

Los tokens se guardan en data/ml_tokens.json (también fuera de git).
El access_token dura 6 horas; se renueva solo con el refresh_token.
Mercado Libre solo acepta el ÚLTIMO refresh_token emitido, por eso cada
renovación se guarda de inmediato.

Conexión compartida: con ML_TOKENS_DRIVE_FOLDER, la versión que vale es la del
archivo ml_tokens.json de esa carpeta (lo lee la cuenta de servicio de
credentials.json). Antes de renovar se vuelve a leer, así el notebook, el PC de
la casa y el servidor usan siempre el último refresh_token. El archivo local
queda como copia de respaldo. La cuenta de servicio no puede crear archivos en
un Drive personal: ml_tokens.json se crea una vez a mano (vacío: {}).

Primera conexión:  python scripts/ml_conectar.py
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
from pathlib import Path

import requests
from dotenv import load_dotenv

from logger_config import get_logger
from modules.mercadolibre.rutas import raiz

logger = get_logger(__name__)

ROOT = raiz()  # carpeta del proyecto, o la del .exe del Sincronizador ML
load_dotenv(ROOT / ".env")

API_URL = "https://api.mercadolibre.com"
AUTH_URL = "https://auth.mercadolibre.cl/authorization"
SITE_ID = "MLC"
TOKENS_PATH = ROOT / "data" / "ml_tokens.json"
_TIMEOUT = 20
_MARGEN_EXPIRACION = 300  # renovar 5 min antes de que venza
TOKENS_DRIVE_NOMBRE = "ml_tokens.json"


class MercadoLibreError(Exception):
    """Error devuelto por la API de Mercado Libre o de configuración."""

    def __init__(self, mensaje, status=None, detalle=None):
        super().__init__(mensaje)
        self.status = status
        self.detalle = detalle  # cuerpo de la respuesta de ML (dict) si lo hubo


# ── Configuración ──────────────────────────────────────────────────────────────
def config() -> dict:
    cfg = {
        "client_id": os.getenv("ML_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("ML_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("ML_REDIRECT_URI", "").strip(),
        "usar_pkce": os.getenv("ML_USAR_PKCE", "0").strip() in ("1", "true", "si", "sí"),
    }
    faltan = [k for k in ("client_id", "client_secret", "redirect_uri") if not cfg[k]]
    if faltan:
        raise MercadoLibreError(
            "Faltan en .env: " + ", ".join("ML_" + k.upper() for k in faltan)
        )
    return cfg


# ── Autorización (solo la primera vez) ────────────────────────────────────────
def generar_pkce() -> tuple[str, str]:
    """Devuelve (code_verifier, code_challenge S256)."""
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    return verifier, challenge


def url_autorizacion(state: str, code_challenge: str | None = None) -> str:
    cfg = config()
    params = {
        "response_type": "code",
        "client_id": cfg["client_id"],
        "redirect_uri": cfg["redirect_uri"],
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def canjear_codigo(code: str, code_verifier: str | None = None) -> dict:
    """Cambia el code de autorización por access_token + refresh_token y los guarda."""
    cfg = config()
    data = {
        "grant_type": "authorization_code",
        "client_id": cfg["client_id"],
        "client_secret": cfg["client_secret"],
        "code": code,
        "redirect_uri": cfg["redirect_uri"],
    }
    if code_verifier:
        data["code_verifier"] = code_verifier
    tokens = _post_token(data)
    _guardar_tokens(tokens)
    return tokens


# ── Tokens en disco ────────────────────────────────────────────────────────────
def _post_token(data: dict) -> dict:
    resp = requests.post(
        f"{API_URL}/oauth/token",
        data=data,
        headers={"Accept": "application/json"},
        timeout=_TIMEOUT,
    )
    if resp.status_code != 200:
        raise MercadoLibreError(f"Error al obtener token ({resp.status_code}): {resp.text}")
    return resp.json()


def _vencido(tokens: dict) -> bool:
    return tokens.get("expires_at", 0) - _MARGEN_EXPIRACION < time.time()


# -- copia compartida en Drive --
_drive = None
_drive_archivo_id = None


def _carpeta_drive() -> str:
    return os.getenv("ML_TOKENS_DRIVE_FOLDER", "").strip()


_DRIVE_API = "https://www.googleapis.com/drive/v3/files"
_DRIVE_SUBIDA = "https://www.googleapis.com/upload/drive/v3/files"


def _drive_service():
    """Sesión HTTP autenticada con la cuenta de servicio (google-auth + requests, sin googleapiclient)."""
    global _drive
    if _drive is None:
        from google.auth.transport.requests import AuthorizedSession
        from google.oauth2.service_account import Credentials

        creds = Credentials.from_service_account_file(
            str(ROOT / "credentials.json"), scopes=["https://www.googleapis.com/auth/drive"]
        )
        _drive = AuthorizedSession(creds)
    return _drive


def _drive_ok(resp):
    if resp.status_code >= 400:
        raise RuntimeError(f"Drive respondió {resp.status_code}: {resp.text[:300]}")
    return resp


def _archivo_drive() -> str:
    global _drive_archivo_id
    if not _drive_archivo_id:
        carpeta = _carpeta_drive()
        r = _drive_ok(_drive_service().get(_DRIVE_API, params={
            "q": f"'{carpeta}' in parents and name = '{TOKENS_DRIVE_NOMBRE}' and trashed = false",
            "fields": "files(id)", "supportsAllDrives": "true", "includeItemsFromAllDrives": "true",
        }, timeout=_TIMEOUT)).json()
        archivos = r.get("files", [])
        if not archivos:
            raise MercadoLibreError(
                f"No está {TOKENS_DRIVE_NOMBRE} en la carpeta de Drive de la conexión ({carpeta}). "
                "Créalo con tu cuenta, con el contenido {} (la cuenta de servicio no puede crear archivos)."
            )
        _drive_archivo_id = archivos[0]["id"]
    return _drive_archivo_id


def _leer_drive() -> dict:
    resp = _drive_ok(_drive_service().get(f"{_DRIVE_API}/{_archivo_drive()}",
                                          params={"alt": "media", "supportsAllDrives": "true"}, timeout=_TIMEOUT))
    return json.loads(resp.content) if resp.content.strip() else {}


def _escribir_drive(tokens: dict) -> None:
    _drive_ok(_drive_service().patch(
        f"{_DRIVE_SUBIDA}/{_archivo_drive()}", params={"uploadType": "media", "supportsAllDrives": "true"},
        data=json.dumps(tokens, indent=2).encode("utf-8"), headers={"Content-Type": "application/json"},
        timeout=_TIMEOUT))


# -- copia local --
def _leer_local() -> dict | None:
    if not TOKENS_PATH.exists():
        return None
    return json.loads(TOKENS_PATH.read_text(encoding="utf-8"))


def _escribir_local(tokens: dict) -> None:
    TOKENS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = TOKENS_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(tokens, indent=2), encoding="utf-8")
    tmp.replace(TOKENS_PATH)  # escritura atómica: nunca queda un archivo a medias


def _guardar_tokens(tokens: dict) -> dict:
    tokens = dict(tokens)
    tokens["expires_at"] = int(time.time()) + int(tokens.get("expires_in", 21600))
    _escribir_local(tokens)
    if _carpeta_drive():
        try:
            _escribir_drive(tokens)
        except Exception:
            # el próximo _cargar_tokens vuelve a intentarlo (la copia local es más nueva)
            logger.error("No se pudo guardar la conexión de Mercado Libre en Drive.", exc_info=True)
    return tokens


def _cargar_tokens() -> dict:
    """Última versión de los tokens: la de Drive si está configurada; si no, la local."""
    local = _leer_local()
    sin_conexion = MercadoLibreError(
        "No hay conexión con Mercado Libre. Ejecuta: python scripts/ml_conectar.py"
    )
    if not _carpeta_drive():
        if not local:
            raise sin_conexion
        return local
    try:
        remoto = _leer_drive()
    except MercadoLibreError:
        raise
    except Exception:
        logger.warning("No se pudo leer la conexión de Mercado Libre en Drive; se usa la copia local.",
                       exc_info=True)
        if not local:
            raise sin_conexion
        return local
    if local and local.get("refresh_token") and local.get("expires_at", 0) > remoto.get("expires_at", 0):
        # la copia local es más nueva (primera vez, o Drive falló al renovar): subirla
        logger.info("Subiendo a Drive la conexión de Mercado Libre de este computador.")
        try:
            _escribir_drive(local)
        except Exception:
            logger.error("No se pudo subir la conexión de Mercado Libre a Drive.", exc_info=True)
        return local
    if not remoto.get("access_token"):
        raise sin_conexion
    if remoto != local:
        _escribir_local(remoto)
    return remoto


def esta_conectado() -> bool:
    return TOKENS_PATH.exists() or bool(_carpeta_drive())


# ── Cliente ────────────────────────────────────────────────────────────────────
class MercadoLibreClient:
    _lock = threading.Lock()
    _tokens: dict | None = None  # en memoria, compartido por las instancias del proceso

    def __init__(self):
        self.session = requests.Session()
        self.session.headers["Accept"] = "application/json"

    # -- tokens --
    def _access_token(self, forzar_refresh: bool = False, rechazado: str | None = None) -> str:
        """
        Usa el token en memoria mientras esté vigente. Si venció (o ML lo rechazó), relee la
        última versión (Drive) y solo renueva si nadie más lo hizo antes.
        """
        cls = type(self)
        with cls._lock:
            tokens = cls._tokens
            if tokens and not forzar_refresh and not _vencido(tokens):
                return tokens["access_token"]
            tokens = _cargar_tokens()
            otro_lo_renovo = rechazado and tokens.get("access_token") != rechazado and not _vencido(tokens)
            if _vencido(tokens) or (forzar_refresh and not otro_lo_renovo):
                tokens = self._refrescar(tokens)
            cls._tokens = tokens
            return tokens["access_token"]

    def _refrescar(self, tokens: dict) -> dict:
        if not tokens.get("refresh_token"):
            raise MercadoLibreError(
                "La conexión con Mercado Libre venció y no se puede renovar sola: la autorización "
                "no incluyó 'acceso offline' (refresh_token). Activa el acceso offline en la app de "
                "developers.mercadolibre.cl y vuelve a ejecutar: python scripts/ml_conectar.py"
            )
        cfg = config()
        logger.info("Renovando access_token de Mercado Libre.")
        try:
            nuevos = _post_token({
                "grant_type": "refresh_token",
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "refresh_token": tokens["refresh_token"],
            })
        except MercadoLibreError:
            # ¿otro computador lo renovó justo ahora? entonces su token nuevo ya está en Drive
            if _carpeta_drive():
                actuales = _cargar_tokens()
                if actuales.get("refresh_token") != tokens["refresh_token"] and not _vencido(actuales):
                    return actuales
            raise
        return _guardar_tokens(nuevos)

    # -- llamadas --
    def request(self, method: str, path: str, auth: bool = True, **kwargs):
        url = path if path.startswith("http") else f"{API_URL}{path}"
        kwargs.setdefault("timeout", _TIMEOUT)
        token = None
        for intento in (1, 2):
            headers = kwargs.pop("headers", {}) or {}
            if auth:
                token = self._access_token(forzar_refresh=intento == 2, rechazado=token)
                headers["Authorization"] = f"Bearer {token}"
            resp = self.session.request(method, url, headers=headers, **kwargs)
            if resp.status_code == 401 and auth and intento == 1:
                continue  # token rechazado: renovar una vez y reintentar
            break
        if resp.status_code >= 400:
            try:
                detalle = resp.json()
            except ValueError:
                detalle = resp.text
            logger.error("ML %s %s -> %s: %s", method, path, resp.status_code, detalle)
            raise MercadoLibreError(f"{resp.status_code}: {detalle}", status=resp.status_code, detalle=detalle)
        return resp.json() if resp.content else None

    def get(self, path, **kw):
        return self.request("GET", path, **kw)

    def post(self, path, **kw):
        return self.request("POST", path, **kw)

    def put(self, path, **kw):
        return self.request("PUT", path, **kw)

    # -- consultas útiles --
    def usuario_actual(self) -> dict:
        return self.get("/users/me")

    def items(self, ids: list[str], attributes: str = "") -> list[dict]:
        """Datos de varias publicaciones, de a una con /items/{id}.

        ML retiró la consulta múltiple /items?ids=... (403 ResourceDeprecated).
        Las que ya no existen (404) se omiten.
        """
        params = {"attributes": attributes} if attributes else {}
        res = []
        for item_id in ids:
            try:
                res.append(self.get(f"/items/{item_id}", params=params))
            except MercadoLibreError as e:
                if e.status == 404:
                    continue
                if e.status != 429 and (e.status or 0) < 500:
                    raise
                time.sleep(3)  # ML a veces rechaza una consulta por un momento: se reintenta una vez
                res.append(self.get(f"/items/{item_id}", params=params))
        return res

    def predecir_categoria(self, texto: str, limite: int = 3) -> list[dict]:
        """Sugiere categorías de ML a partir del nombre del producto."""
        return self.get(
            f"/sites/{SITE_ID}/domain_discovery/search",
            params={"q": texto, "limit": limite},
        )

    def atributos_categoria(self, category_id: str) -> list[dict]:
        return self.get(f"/categories/{category_id}/attributes")

    def atributos_obligatorios(self, category_id: str) -> list[dict]:
        return [
            a for a in self.atributos_categoria(category_id)
            if (a.get("tags") or {}).get("required") or (a.get("tags") or {}).get("catalog_required")
        ]
