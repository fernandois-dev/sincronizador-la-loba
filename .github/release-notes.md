## Instalar o actualizar

**Si ya tienes el Gestor instalado**, no descargues nada: al abrirlo te ofrece actualizar con un clic.

**Windows:** descarga `GestorLaLoba-windows.zip`, descomprímelo donde quieras (por ejemplo en `Documentos\GestorLaLoba`) y abre `gestor-la-loba.exe`.
Para actualizar, reemplaza la carpeta por la nueva: la configuración y la base local no se tocan.

**Linux:** descarga `GestorLaLoba-linux.tar.gz` y descomprímelo, o ejecuta `bash install-linux.sh` (instala en `~/.local/share/gestor-la-loba` y agrega el ícono al menú).

**Primera vez en un equipo:** el Gestor pide los archivos de configuración (`credentials.json`, `server_settings.cfg` y, si usas IA o Mercado Libre, `.env`). Elígelos desde donde los tengas y se copian a:
- Windows: `%APPDATA%\GestorLaLoba`
- Linux: `~/.config/gestor-la-loba`

Esos archivos nunca van dentro de este paquete.
