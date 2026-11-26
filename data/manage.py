"""
Comandos de Django para la base local (desde la carpeta del proyecto):

    uv run python data/manage.py migrate          aplica las migraciones pendientes
    uv run python data/manage.py showmigrations   muestra cuáles están aplicadas

Usa la misma configuración que la app (apps/servidor/settings.py) y la misma
base: data/database.db, o la carpeta de datos del usuario en el programa
instalado (utilities/carpeta_datos.py).
"""
import os
import sys

if __name__ == "__main__":
    # Al ejecutar "python data/manage.py", Python solo ve la carpeta data/:
    # se agrega la raíz del proyecto para encontrar apps/, modules/, utilities/…
    raiz = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, raiz)
    os.chdir(raiz)
    os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")

    from utilities import carpeta_datos
    carpeta_datos.preparar()

    import apps.servidor.settings  # noqa: F401  (settings.configure de la app)
    import django
    django.setup()

    # Los modelos arrastran dos avisos antiguos de Django (Comparativa, DetalleCompra) que
    # detienen los comandos; la app no los revisa al abrir, aquí tampoco.
    argv = list(sys.argv)
    if len(argv) > 1 and "--skip-checks" not in argv and argv[1] in ("migrate", "showmigrations", "makemigrations"):
        argv.append("--skip-checks")

    from django.core.management import execute_from_command_line
    execute_from_command_line(argv)
