@echo off
setlocal
set "DIR=%~dp0"
cd /d "%DIR%"
echo Sincronizador ML - instalacion
echo.
set FALTA=
if not exist ".env" set FALTA=%FALTA% .env
if not exist "credentials.json" set FALTA=%FALTA% credentials.json
if not exist "server_settings.cfg" set FALTA=%FALTA% server_settings.cfg
if defined FALTA (
  echo Faltan en esta carpeta:%FALTA%
  echo Copialos desde el Gestor La Loba y vuelve a ejecutar este archivo. Ver LEEME.txt
  pause
  exit /b 1
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Startup')+'\Sincronizador ML.lnk'); $s.TargetPath='%DIR%SincronizadorML.exe'; $s.WorkingDirectory='%DIR%'; $s.Save()"
echo Listo: el Sincronizador ML partira solo cada vez que inicies sesion en Windows.
start "" "%DIR%SincronizadorML.exe"
echo Se abrio. Busca el circulo de color junto al reloj, o en la flecha de iconos ocultos.
pause
