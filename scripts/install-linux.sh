#!/usr/bin/env bash
# Instala o actualiza Gestor La Loba desde GitHub Releases.
#
# Uso:
#   bash install-linux.sh                      # descarga la última versión
#   bash install-linux.sh GestorLaLoba-linux.tar.gz   # usa un paquete ya descargado
#
# Después, la app se actualiza sola (avisa al abrir cuando hay versión nueva).
#
# La configuración y la base local viven en ~/.config/gestor-la-loba y no se
# tocan al actualizar.
set -euo pipefail

GITHUB_REPO="fernandois-dev/sincronizador-la-loba"
ASSET="GestorLaLoba-linux.tar.gz"
INSTALL_DIR="$HOME/.local/share/gestor-la-loba"
BIN_NAME="gestor-la-loba"
BIN_DIR="$HOME/.local/bin"
DESKTOP_FILE="$HOME/.local/share/applications/gestor-la-loba.desktop"

TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

if [ $# -ge 1 ]; then
  cp "$1" "$TMP/release.tar.gz"
elif command -v gh >/dev/null 2>&1 && gh auth status >/dev/null 2>&1; then
  echo "Descargando la última versión con gh..."
  gh release download --repo "$GITHUB_REPO" --pattern "$ASSET" --dir "$TMP"
  mv "$TMP/$ASSET" "$TMP/release.tar.gz"
else
  command -v curl >/dev/null 2>&1 || { echo "Error: falta curl."; exit 1; }
  AUTH=()
  [ -n "${GITHUB_TOKEN:-}" ] && AUTH=(-H "Authorization: Bearer $GITHUB_TOKEN")
  echo "Buscando la última versión..."
  ASSET_URL=$(curl -fsSL "${AUTH[@]}" "https://api.github.com/repos/$GITHUB_REPO/releases/latest" \
    | python3 -c "import json,sys; print(next(a['url'] for a in json.load(sys.stdin)['assets'] if a['name']=='$ASSET'))" ) || {
      echo "No se pudo consultar GitHub. Revisa la conexión a internet"
      echo "o descarga $ASSET desde la página de Releases y pásalo como argumento."
      exit 1; }
  echo "Descargando..."
  curl -fsSL "${AUTH[@]}" -H "Accept: application/octet-stream" "$ASSET_URL" -o "$TMP/release.tar.gz"
fi

echo "Instalando en $INSTALL_DIR ..."
rm -rf "$INSTALL_DIR"
mkdir -p "$INSTALL_DIR"
tar -xzf "$TMP/release.tar.gz" -C "$INSTALL_DIR"

BINARY="$INSTALL_DIR/$BIN_NAME"
chmod +x "$BINARY"
mkdir -p "$BIN_DIR"
ln -sf "$BINARY" "$BIN_DIR/$BIN_NAME"

# Ícono en el menú de aplicaciones
ICONO=$(find "$INSTALL_DIR" -name 'icon*.png' | head -1 || true)
mkdir -p "$(dirname "$DESKTOP_FILE")"
cat > "$DESKTOP_FILE" <<EOF
[Desktop Entry]
Type=Application
Name=Gestor La Loba
Exec=$BINARY
Path=$INSTALL_DIR
Icon=${ICONO:-utilities-terminal}
Categories=Office;
Terminal=false
EOF

if ! echo "$PATH" | grep -q "$BIN_DIR"; then
  echo ""
  echo "Para usar el comando '$BIN_NAME' agrega a ~/.bashrc:"
  echo "  export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

echo ""
echo "Instalación completada. Ábrelo desde el menú (Gestor La Loba) o con: $BIN_NAME"
echo "Configuración y datos: ~/.config/gestor-la-loba"
