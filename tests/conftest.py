import logging

import pytest

from tests.apoyo import preparar_entorno

_copia = preparar_entorno()


class _CapturaErrores(logging.Handler):
    def __init__(self):
        super().__init__(level=logging.ERROR)
        self.registros: list[logging.LogRecord] = []

    def emit(self, record):
        self.registros.append(record)


@pytest.fixture
def errores_log():
    """Errores registrados por la app durante la prueba (logger y hilos)."""
    captura = _CapturaErrores()
    logging.getLogger().addHandler(captura)
    yield captura.registros
    logging.getLogger().removeHandler(captura)
