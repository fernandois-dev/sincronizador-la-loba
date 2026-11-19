"""
Capa del proveedor del modelo.

El resto del código habla con ClienteLLM y nunca con el SDK directo. Si mañana
se cambia de proveedor (o se agrega uno que no hable el formato OpenAI), solo
se toca este archivo.

Respaldo automático (fallback): se configuran un proveedor principal y uno de
respaldo. Si el principal falla por algo que NO es culpa de la solicitud
(límite de uso, caída, red, key sin créditos), se reintenta al instante con el
respaldo en vez de esperar. Si la solicitud está mal armada (error 400), el
respaldo fallaría igual, así que el error se propaga.
"""
import time
from dataclasses import dataclass

from openai import APIError, BadRequestError, OpenAI

from logger_config import get_logger
from modules.ia.config import ConfigIA

logger = get_logger(__name__)


@dataclass
class Uso:
    """Consumo acumulado: base de la observabilidad (fase 4)."""
    llamadas: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    segundos_modelo: float = 0.0
    proveedores: str = ""       # quién respondió, ej. "cerebras" o "cerebras+groq"

    def sumar(self, otro: "Uso"):
        self.llamadas += otro.llamadas
        self.tokens_entrada += otro.tokens_entrada
        self.tokens_salida += otro.tokens_salida
        self.segundos_modelo += otro.segundos_modelo
        usados = [p for p in self.proveedores.split("+") if p]
        for p in otro.proveedores.split("+"):
            if p and p not in usados:
                usados.append(p)
        self.proveedores = "+".join(usados)


@dataclass
class _Destino:
    nombre: str
    cliente: OpenAI
    modelo: str


class ClienteLLM:
    def __init__(self, cfg: ConfigIA):
        self.cfg = cfg
        hay_respaldo = bool(cfg.resp_proveedor and cfg.resp_api_key and cfg.resp_modelo)
        # Con respaldo, el principal no reintenta (pasar al respaldo es más rápido que esperar).
        self._destinos = [
            _Destino(cfg.proveedor,
                     OpenAI(base_url=cfg.base_url, api_key=cfg.api_key, timeout=60,
                            max_retries=0 if hay_respaldo else 1),
                     cfg.modelo)
        ]
        if hay_respaldo:
            # IA_RESPALDO_MODELO acepta varios modelos separados por coma. En Groq cada modelo
            # tiene su propio límite por minuto: más modelos = más capacidad gratis.
            modelos = [m.strip() for m in cfg.resp_modelo.split(",") if m.strip()]
            cliente = OpenAI(base_url=cfg.resp_base_url, api_key=cfg.resp_api_key, timeout=60, max_retries=0)
            for n, modelo in enumerate(modelos):
                ultimo = n == len(modelos) - 1
                self._destinos.append(_Destino(
                    f"{cfg.resp_proveedor}/{modelo.split('/')[-1]}",
                    cliente.with_options(max_retries=1) if ultimo else cliente,
                    modelo,
                ))
        if len(self._destinos) > 1:
            self._destinos[0].nombre = f"{cfg.proveedor}/{cfg.modelo.split('/')[-1]}"

    def completar(self, mensajes: list[dict], herramientas: list[dict] | None = None):
        """Una llamada al modelo (con respaldo). Devuelve (mensaje, uso de esta llamada)."""
        ultimo_error = None
        for i, destino in enumerate(self._destinos):
            kwargs = {"model": destino.modelo, "messages": mensajes, "temperature": self.cfg.temperatura}
            if herramientas:
                kwargs["tools"] = herramientas
                kwargs["tool_choice"] = "auto"
            t0 = time.perf_counter()
            try:
                r = destino.cliente.chat.completions.create(**kwargs)
            except BadRequestError:
                raise                       # la solicitud está mal: otro proveedor fallaría igual
            except APIError as exc:
                ultimo_error = exc
                if i + 1 < len(self._destinos):
                    logger.warning("Proveedor %s falló (%s); uso el respaldo %s.",
                                   destino.nombre, type(exc).__name__, self._destinos[i + 1].nombre)
                    continue
                raise
            uso = Uso(llamadas=1, segundos_modelo=time.perf_counter() - t0, proveedores=destino.nombre)
            if r.usage:
                uso.tokens_entrada = r.usage.prompt_tokens or 0
                uso.tokens_salida = r.usage.completion_tokens or 0
            return r.choices[0].message, uso
        raise ultimo_error  # no debería llegar aquí
