"""
Scheduler semanal del reporte de bajo stock.

Lógica:
- Se envía el lunes de cada semana ISO (o cuando se abra el sincronizador
  ese mismo lunes o cualquier día posterior dentro de la misma semana).
- Usa Odoo ir.config_parameter como fuente de verdad compartida entre
  múltiples sincronizadores locales:
    key: gestor_la_loba.bajo_stock_last_sent
    value: "YYYY-Www"  (año + número de semana ISO, ej. "2026-W16")
- Para evitar doble envío concurrente: se escribe el lock ANTES de enviar.
"""
import threading
from datetime import date
from logger_config import get_logger
from utilities import carpeta_datos

logger = get_logger(__name__)

_ODOO_KEY    = "gestor_la_loba.bajo_stock_last_sent"
_CONFIG_PATH = None  # se resuelve en tiempo de ejecución


def _reporte_habilitado() -> bool:
    import configparser, os
    global _CONFIG_PATH
    if _CONFIG_PATH is None:
        _CONFIG_PATH = str(carpeta_datos.ruta("server_settings.cfg"))
    cfg = configparser.ConfigParser()
    carpeta_datos.leer_ini(cfg, _CONFIG_PATH)
    return cfg.getboolean("REPORTES", "reporte_bajo_stock_activo", fallback=False)


def _semana_actual() -> str:
    """Retorna la clave de semana ISO actual, ej. '2026-W16'."""
    iso = date.today().isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _debe_enviar() -> bool:
    """
    Devuelve True si hoy es lunes o posterior (dentro de la semana actual)
    y el reporte no fue enviado esta semana.
    """
    today = date.today()
    # weekday(): 0=lunes … 6=domingo
    if today.weekday() < 0:  # nunca False; lunes=0, siempre >= 0
        pass

    try:
        from modules.servidor.odoo import OdooService
        last_sent = OdooService.get_config_param(_ODOO_KEY) or ""
    except Exception as exc:
        logger.warning("No se pudo consultar Odoo para scheduler: %s", exc)
        return False

    return last_sent != _semana_actual()


def _marcar_enviado():
    try:
        from modules.servidor.odoo import OdooService
        OdooService.set_config_param(_ODOO_KEY, _semana_actual())
    except Exception as exc:
        logger.error("No se pudo marcar reporte como enviado en Odoo: %s", exc)


def ejecutar_reporte(forzar: bool = False, callback=None):
    """
    Genera y envía el reporte si corresponde (o si forzar=True).

    Args:
        forzar: Ignorar la verificación semanal (usado por el botón manual).
        callback: función opcional(resultado: dict) llamada al terminar.

    Returns cuando se llama con forzar=True retorna dict directamente;
    de lo contrario ejecuta en hilo daemon y retorna None.
    """
    def _run():
        try:
            if not forzar and not _reporte_habilitado():
                logger.info("Reporte semanal desactivado en configuración, omitiendo.")
                if callback:
                    callback({"state": "S", "msg": "Reporte desactivado en configuración del sistema."})
                return

            if not forzar and not _debe_enviar():
                resultado = {"state": "S", "msg": "Reporte ya enviado esta semana."}
                logger.info("Reporte semanal ya fue enviado, omitiendo.")
                if callback:
                    callback(resultado)
                return

            # Marcar ANTES de enviar para evitar doble envío concurrente
            if not forzar:
                _marcar_enviado()

            from modules.servidor.reportes.bajo_stock import obtener_datos_bajo_stock, generar_html
            from modules.servidor.reportes.email_sender import enviar_reporte_bajo_stock

            agrupado = obtener_datos_bajo_stock()
            html = generar_html(agrupado)
            resultado = enviar_reporte_bajo_stock(html)

            # Si falló el envío, revertir el lock para intentarlo de nuevo
            if resultado["state"] == "E" and not forzar:
                try:
                    from modules.servidor.odoo import OdooService
                    OdooService.set_config_param(_ODOO_KEY, "")
                except Exception:
                    pass

            if callback:
                callback(resultado)
        except Exception as exc:
            logger.error("Error inesperado en scheduler de reporte: %s", exc)
            if callback:
                callback({"state": "E", "msg": str(exc)})

    hilo = threading.Thread(target=_run, daemon=True)
    hilo.start()
