#!/usr/bin/env bash
# Собирает .deb пакет vpn-gate из исходников этого репозитория.
# Использование: packaging/build-deb.sh [каталог_для_результата]
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
DEB_SRC="$SCRIPT_DIR/debian"
OUT_DIR="$(cd "$(dirname "${1:-$SCRIPT_DIR/build}")" && pwd)/$(basename "${1:-$SCRIPT_DIR/build}")"

PKG_NAME="vpn-gate"
ARCH="all"

command -v dpkg-deb >/dev/null 2>&1 || {
  echo "Не найден dpkg-deb. Установите dpkg-dev: sudo apt install dpkg-dev" >&2
  exit 1
}

VERSION="$(cd "$ROOT_DIR" && python3 -c "from vpn_gate_ui import __version__; print(__version__)")"

mkdir -p "$OUT_DIR"
STAGE="$OUT_DIR/${PKG_NAME}_${VERSION}_${ARCH}"
rm -rf "$STAGE"

mkdir -p \
  "$STAGE/DEBIAN" \
  "$STAGE/usr/bin" \
  "$STAGE/usr/lib/python3/dist-packages" \
  "$STAGE/usr/share/applications" \
  "$STAGE/usr/share/icons/hicolor/scalable/apps" \
  "$STAGE/usr/share/doc/$PKG_NAME"

# --- CLI-установщик ---
install -m 0755 "$ROOT_DIR/install-vpn-gate.sh" "$STAGE/usr/bin/vpn-gate-install"

# --- Python-пакет GUI ---
cp -r "$ROOT_DIR/vpn_gate_ui" "$STAGE/usr/lib/python3/dist-packages/"
find "$STAGE/usr/lib/python3/dist-packages/vpn_gate_ui" \
  -name '__pycache__' -type d -prune -exec rm -rf {} +
find "$STAGE/usr/lib/python3/dist-packages/vpn_gate_ui" -type f -exec chmod 0644 {} +
find "$STAGE/usr/lib/python3/dist-packages/vpn_gate_ui" -type d -exec chmod 0755 {} +

# --- Launcher GUI ---
cat > "$STAGE/usr/bin/vpn-gate-ui" <<'LAUNCHER_EOF'
#!/usr/bin/env python3
"""Запуск GUI-обёртки VPN Gate (пакет vpn_gate_ui)."""

from vpn_gate_ui.app import main

if __name__ == "__main__":
    raise SystemExit(main())
LAUNCHER_EOF
chmod 0755 "$STAGE/usr/bin/vpn-gate-ui"

# --- .desktop ---
install -m 0644 "$DEB_SRC/vpn-gate-ui.desktop" \
  "$STAGE/usr/share/applications/vpn-gate-ui.desktop"

# --- значок ---
if [[ -f "$SCRIPT_DIR/logo.svg" ]]; then
  install -m 0644 "$SCRIPT_DIR/logo.svg" \
    "$STAGE/usr/share/icons/hicolor/scalable/apps/vpn-gate.svg"
else
  echo "Внимание: packaging/logo.svg не найден, значок не будет включён в пакет" >&2
fi

# --- Документация ---
install -m 0644 "$ROOT_DIR/README.md" "$STAGE/usr/share/doc/$PKG_NAME/README.md"
install -m 0644 "$ROOT_DIR/README.en.md" "$STAGE/usr/share/doc/$PKG_NAME/README.en.md"
install -m 0644 "$DEB_SRC/copyright" "$STAGE/usr/share/doc/$PKG_NAME/copyright"
gzip -n -9 -c "$DEB_SRC/changelog" > "$STAGE/usr/share/doc/$PKG_NAME/changelog.Debian.gz"
chmod 0644 "$STAGE/usr/share/doc/$PKG_NAME/changelog.Debian.gz"

# --- DEBIAN/control (+ вычисленный Installed-Size) ---
sed "s/@VERSION@/$VERSION/" "$DEB_SRC/control.in" > "$STAGE/DEBIAN/control"
INSTALLED_SIZE_KB="$(du -sk "$STAGE" --exclude=DEBIAN | cut -f1)"
printf 'Installed-Size: %s\n' "$INSTALLED_SIZE_KB" >> "$STAGE/DEBIAN/control"

install -m 0755 "$DEB_SRC/postinst" "$STAGE/DEBIAN/postinst"
install -m 0755 "$DEB_SRC/postrm" "$STAGE/DEBIAN/postrm"

DEB_FILE="$OUT_DIR/${PKG_NAME}_${VERSION}_${ARCH}.deb"
dpkg-deb --build --root-owner-group "$STAGE" "$DEB_FILE"

echo
echo "Собрано: $DEB_FILE"
echo "Установка:   sudo apt install $DEB_FILE   (или: sudo dpkg -i $DEB_FILE)"
echo "Удаление:    sudo apt remove $PKG_NAME"
