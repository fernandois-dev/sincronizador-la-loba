"""
Envío de correo HTML vía Gmail SMTP con App Password.
Credenciales leídas desde .env
"""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
from logger_config import get_logger

logger = get_logger(__name__)

# Ruta explícita: sin ella dotenv busca desde la ubicación del código, que en el
# programa compilado no existe (AssertionError al abrir). Ver utilities/carpeta_datos.py.
from modules.mercadolibre.rutas import raiz as _raiz
load_dotenv(_raiz() / ".env")

_SMTP_HOST = "smtp.gmail.com"
_SMTP_PORT = 587


def _get_credentials() -> tuple[str, str, list[str]]:
    user       = os.getenv("GMAIL_USER", "")
    password   = os.getenv("GMAIL_APP_PASSWORD", "")
    recipients_raw = os.getenv("REPORT_RECIPIENTS", user)
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]
    return user, password, recipients


def enviar_reporte_bajo_stock(html_body: str) -> dict:
    """
    Envía el HTML como correo a los destinatarios configurados en .env.

    Returns:
        {"state": "S"|"E", "msg": str}
    """
    user, password, recipients = _get_credentials()

    if not user or not password:
        return {"state": "E", "msg": "Faltan credenciales Gmail en .env (GMAIL_USER / GMAIL_APP_PASSWORD)"}
    if not recipients:
        return {"state": "E", "msg": "No hay destinatarios configurados en REPORT_RECIPIENTS"}

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "⭐ Reporte Semanal — Bajo Stock Productos Favoritos"
        msg["From"]    = f"Gestor La Loba <{user}>"
        msg["To"]      = ", ".join(recipients)
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP(_SMTP_HOST, _SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user, password)
            server.sendmail(user, recipients, msg.as_string())

        logger.info("Reporte bajo stock enviado a: %s", recipients)
        return {"state": "S", "msg": f"Correo enviado a {', '.join(recipients)}"}

    except smtplib.SMTPAuthenticationError:
        msg_err = ("Error de autenticación Gmail. Verifica que GMAIL_APP_PASSWORD sea un "
                   "App Password de 16 caracteres (sin espacios), generado en "
                   "myaccount.google.com → Seguridad → Contraseñas de aplicación.")
        logger.error(msg_err)
        return {"state": "E", "msg": msg_err}
    except Exception as exc:
        logger.error("Error enviando correo: %s", exc)
        return {"state": "E", "msg": str(exc)}
