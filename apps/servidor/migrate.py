
import django
from django.core.management import call_command
from . import settings  # Importa la configuración
from django.conf import settings
import os


django.setup()

# Generar y aplicar migraciones
call_command("makemigrations", "servidor")
call_command("migrate")