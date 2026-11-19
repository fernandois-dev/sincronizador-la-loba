# Sincronizador La Loba

App de escritorio (Python + [Flet](https://flet.dev)) que mantiene sincronizados la Tabla Base de productos en Google Sheets, Odoo y Mercado Libre: precios, códigos de barra, stock, compras a proveedores, publicaciones en Mercado Libre, impresión de etiquetas y un asistente con IA. Hecha para la Ferretería La Loba; funciona en Windows y Linux.

## Instalar

1. Descarga la [última versión](https://github.com/fernandois-dev/sincronizador-la-loba/releases/latest):
   - **Windows:** `GestorLaLoba-windows.zip`. Descomprímelo en una carpeta tuya (por ejemplo `Documentos\GestorLaLoba`) y abre `gestor-la-loba.exe`.
     También puedes usar `install-windows.ps1`, que lo instala y crea accesos directos.
   - **Linux:** `GestorLaLoba-linux.tar.gz`, y luego `bash install-linux.sh GestorLaLoba-linux.tar.gz` (agrega el ícono al menú).
2. La primera vez, la app pide los archivos de configuración. Elígelos y se copian a la carpeta de datos:

| Archivo | Para qué | Obligatorio |
|---|---|---|
| `credentials.json` | Cuenta de servicio de Google con acceso a las planillas | Sí |
| `server_settings.cfg` | Odoo, IDs de las planillas, datos de la empresa, impresora, Mercado Libre. Plantilla: [`server_settings.example.cfg`](apps/servidor/server_settings.example.cfg) | Sí |
| `.env` | Claves del asistente IA, Mercado Libre y Gmail. Plantilla: [`.env.example`](.env.example) | No |

Carpeta de datos (configuración, base local y `logs/`), que no se toca al actualizar:
- Windows: `%APPDATA%\GestorLaLoba`
- Linux: `~/.config/gestor-la-loba`

## Actualizaciones

Al abrir, la app revisa si hay una versión nueva en Releases. Si la hay, muestra las novedades y un botón **Actualizar ahora**: descarga el paquete, se cierra, reemplaza el programa y vuelve a abrirse. También se puede buscar a mano haciendo clic en la versión (esquina superior derecha).

La base local se actualiza sola al abrir la versión nueva.

## Publicar una versión

En GitHub: **Actions → Build Release → Run workflow**, escribe la versión (por ejemplo `1.3.0`) y presiona *Run workflow*. También sirve un tag:

```bash
git tag v1.3.0
git push origin v1.3.0
```

GitHub Actions ([`build.yml`](.github/workflows/build.yml)) compila Windows y Linux con `flet build` y crea el Release. Tarda unos 15 minutos y, desde ahí, todas las apps instaladas ofrecen la actualización. Para probar la compilación sin publicar, usa *Run workflow* con la versión vacía.

El paquete nunca lleva credenciales ni datos: el workflow los borra antes de compilar y revisa el resultado.

## Desarrollo

```bash
uv sync
uv run main.py
uv run pytest
```

Desde el código fuente (con carpeta `.git`), la carpeta de datos es la del proyecto: `credentials.json` y `.env` en la raíz y `server_settings.cfg` en `apps/servidor/`. Se puede cambiar con la variable `GESTOR_ROOT`. El actualizador no actúa desde el código fuente (`GESTOR_ACTUALIZADOR=1` lo fuerza para probar).

Nunca subas `credentials.json`, `server_settings.cfg`, `.env` ni archivos `.db` (están en `.gitignore`).
