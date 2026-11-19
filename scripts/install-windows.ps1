# Instala o actualiza Gestor La Loba desde GitHub Releases.
#
# Uso (PowerShell):
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1
#   powershell -ExecutionPolicy Bypass -File install-windows.ps1 -Zip .\GestorLaLoba-windows.zip
#
# Después, la app se actualiza sola (avisa al abrir cuando hay versión nueva).
#
#
# La configuración y la base local viven en %APPDATA%\GestorLaLoba y no se
# tocan al actualizar.
param([string]$Zip = "")
$ErrorActionPreference = 'Stop'

$GithubRepo = "fernandois-dev/sincronizador-la-loba"
$Asset      = "GestorLaLoba-windows.zip"
$InstallDir = "$env:LOCALAPPDATA\GestorLaLoba"
$tmp        = Join-Path $env:TEMP $Asset

$tieneGh = $false
if (Get-Command gh -ErrorAction SilentlyContinue) {
    try { gh auth status *> $null; $tieneGh = ($LASTEXITCODE -eq 0) } catch { $tieneGh = $false }
}

if ($Zip) {
    Copy-Item $Zip $tmp -Force
}
elseif ($tieneGh) {
    Write-Host "Descargando la ultima version con gh..." -ForegroundColor Cyan
    gh release download --repo $GithubRepo --pattern $Asset --dir $env:TEMP --clobber
}
else {
    $headers = @{}
    if ($env:GITHUB_TOKEN) { $headers["Authorization"] = "Bearer $env:GITHUB_TOKEN" }
    Write-Host "Buscando la ultima version..." -ForegroundColor Cyan
    try {
        $release = Invoke-RestMethod -Headers $headers -Uri "https://api.github.com/repos/$GithubRepo/releases/latest"
    } catch {
        Write-Error "No se pudo consultar GitHub. Revisa la conexión a internet o descarga $Asset desde Releases y usa -Zip."
        exit 1
    }
    $item = $release.assets | Where-Object { $_.name -eq $Asset } | Select-Object -First 1
    if (-not $item) { Write-Error "La ultima version no tiene $Asset."; exit 1 }
    $headers["Accept"] = "application/octet-stream"
    Write-Host "Descargando $($release.tag_name)..." -ForegroundColor Cyan
    Invoke-WebRequest -Headers $headers -Uri $item.url -OutFile $tmp
}

Write-Host "Instalando en $InstallDir..." -ForegroundColor Cyan
Get-Process gestor-la-loba -ErrorAction SilentlyContinue | Stop-Process -Force
if (Test-Path $InstallDir) { Remove-Item $InstallDir -Recurse -Force }
New-Item -ItemType Directory -Path $InstallDir | Out-Null
Expand-Archive -Path $tmp -DestinationPath $InstallDir -Force
Remove-Item $tmp

$exe = Get-ChildItem -Path $InstallDir -Filter "gestor-la-loba.exe" -Recurse | Select-Object -First 1
if (-not $exe) { $exe = Get-ChildItem -Path $InstallDir -Filter "*.exe" -Recurse | Select-Object -First 1 }

# Accesos directos: Escritorio y menú Inicio
$wsh = New-Object -ComObject WScript.Shell
foreach ($carpeta in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $wsh.CreateShortcut((Join-Path $carpeta 'Gestor La Loba.lnk'))
    $lnk.TargetPath = $exe.FullName
    $lnk.WorkingDirectory = $exe.DirectoryName
    $lnk.Save()
}

Write-Host ""
Write-Host "Instalacion completada. Abrelo desde el Escritorio o el menu Inicio (Gestor La Loba)." -ForegroundColor Green
Write-Host "Configuracion y datos: $env:APPDATA\GestorLaLoba"
