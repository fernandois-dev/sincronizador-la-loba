# vendor/

Módulos de la biblioteca estándar de Python que el Python incluido por
`flet build` (serious_python) no trae. `main.py` agrega esta carpeta a
`sys.path` solo si el módulo falta, así que desde el código fuente se sigue
usando el de la instalación de Python.

- `wsgiref/`: copia de CPython 3.13 (licencia PSF). Lo importa
  `google_auth_oauthlib` (dependencia de gspread) al cargarse.
