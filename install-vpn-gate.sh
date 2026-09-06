#!/usr/bin/env bash
# Один установщик: обёртка приложения, которое стартует только при включённом VPN.
#
# Установка:   ./install-vpn-gate.sh <приложение>
# Удаление:    ./install-vpn-gate.sh --uninstall <приложение>
# С конфигом:  ./install-vpn-gate.sh --uninstall <приложение> --purge
#
# Примеры:
#   ./install-vpn-gate.sh alacarte
#   ./install-vpn-gate.sh opencode
#   REAL_BIN=/usr/bin/alacarte ./install-vpn-gate.sh alacarte
set -euo pipefail

BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
DESKTOP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
CHECK_NAME="vpn-gate-check"

usage() {
  cat >&2 <<'EOF'
Использование:
  install-vpn-gate.sh <приложение>
  install-vpn-gate.sh --uninstall <приложение> [--purge]

Переменные окружения:
  REAL_BIN     полный путь к настоящему бинарнику (если не в PATH / неоднозначно)
  VPN_IFACES   интерфейсы через пробел (по умолчанию wg0), пишется в config при первой установке
EOF
  exit 2
}

is_ident() {
  [[ "$1" =~ ^[A-Za-z0-9_][A-Za-z0-9._+-]*$ ]]
}

cfg_dir_for() {
  printf '%s\n' "${XDG_CONFIG_HOME:-$HOME/.config}/${1}-vpn-gate"
}

write_vpn_check() {
  local dest="$1"
  cat >"$dest" <<'CHECK_EOF'
#!/usr/bin/env bash
# Exit 0 and print the active interface if the VPN looks connected.
set -euo pipefail

CONFIG_FILE="${VPN_GATE_CONFIG:-${XDG_CONFIG_HOME:-$HOME/.config}/vpn-gate/config}"
IFACES=(wg0)

# Env overrides config (preserve before source).
_PRESET_IFACES="${VPN_IFACES-}"
_PRESET_STRICT="${VPN_STRICT_ROUTE-}"

if [[ -f "$CONFIG_FILE" ]]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

if [[ -n "${_PRESET_IFACES}" ]]; then
  VPN_IFACES="$_PRESET_IFACES"
fi
if [[ -n "${_PRESET_STRICT}" ]]; then
  VPN_STRICT_ROUTE="$_PRESET_STRICT"
fi

if [[ -n "${VPN_IFACES:-}" ]]; then
  # shellcheck disable=SC2206
  IFACES=($VPN_IFACES)
fi

IP_BIN=""
for candidate in ip /sbin/ip /usr/sbin/ip /bin/ip; do
  if command -v "$candidate" >/dev/null 2>&1; then
    IP_BIN="$(command -v "$candidate")"
    break
  elif [[ -x "$candidate" ]]; then
    IP_BIN="$candidate"
    break
  fi
done

iface_exists() {
  local iface="$1"
  [[ -d "/sys/class/net/$iface" ]]
}

iface_is_up() {
  local iface="$1"
  local flags operstate

  iface_exists "$iface" || return 1

  if [[ -r "/sys/class/net/$iface/operstate" ]]; then
    operstate="$(<"/sys/class/net/$iface/operstate")"
    if [[ "$operstate" == "up" || "$operstate" == "unknown" ]]; then
      if [[ -r "/sys/class/net/$iface/flags" ]]; then
        flags="$(<"/sys/class/net/$iface/flags")"
        if (( flags & 0x1 )); then
          return 0
        fi
      else
        [[ "$operstate" == "up" ]]
        return
      fi
    fi
  fi

  if [[ -n "$IP_BIN" ]]; then
    local state
    state="$("$IP_BIN" -o link show "$iface" 2>/dev/null || true)"
    [[ -n "$state" ]] || return 1
    [[ "$state" == *",UP,"* ]] || [[ "$state" == *" state UP "* ]]
    return
  fi

  return 1
}

has_vpn_route() {
  local iface="$1"
  [[ -n "$IP_BIN" ]] || return 1
  "$IP_BIN" -4 route show 2>/dev/null | grep -E "^(default|0\.0\.0\.0/1|128\.0\.0\.0/1)" | grep -qw "dev $iface"
}

for iface in "${IFACES[@]}"; do
  if iface_is_up "$iface"; then
    if [[ "${VPN_STRICT_ROUTE:-0}" == "1" ]] && ! has_vpn_route "$iface"; then
      continue
    fi
    printf '%s\n' "$iface"
    exit 0
  fi
done

exit 1
CHECK_EOF
  chmod 0755 "$dest"
}

write_app_gate() {
  local dest="$1"
  local app="$2"
  local app_q
  app_q="$(printf '%q' "$app")"

  cat >"$dest" <<GATE_EOF
#!/usr/bin/env bash
# Launch the real ${app} binary only when the VPN is connected.
set -euo pipefail

APP=${app_q}
CHECK="\${VPN_GATE_CHECK:-\${XDG_BIN_HOME:-\$HOME/.local/bin}/vpn-gate-check}"
REAL_BIN="\${VPN_GATE_REAL_BIN:-}"
CFG_DIR="\${XDG_CONFIG_HOME:-\$HOME/.config}/\${APP}-vpn-gate"
LOG_DIR="\${VPN_GATE_LOG_DIR:-\${XDG_STATE_HOME:-\$HOME/.local/state}/vpn-gate}"
LOG_FILE="\$LOG_DIR/events.log"
LOG_MAX_LINES=500
LOG_KEEP_LINES=300

log_block() {
  local title="\$1"
  local body="\$2"
  local ts
  ts="\$(date -Is 2>/dev/null || date)"

  title="\${title//\$'\\t'/ }"
  title="\${title//\$'\\n'/ }"
  body="\${body//\$'\\t'/ }"
  body="\${body//\$'\\n'/ }"

  mkdir -p "\$LOG_DIR" 2>/dev/null || return 0
  printf '%s\\t%s\\t%s\\t%s\\n' "\$ts" "\$APP" "\$title" "\$body" >>"\$LOG_FILE" 2>/dev/null || return 0

  local total
  total="\$(wc -l <"\$LOG_FILE" 2>/dev/null || printf '0')"
  if (( total > LOG_MAX_LINES )); then
    tail -n "\$LOG_KEEP_LINES" "\$LOG_FILE" >"\$LOG_FILE.tmp" 2>/dev/null \\
      && mv -f "\$LOG_FILE.tmp" "\$LOG_FILE" 2>/dev/null
  fi
}

notify() {
  local title="\$1"
  local body="\$2"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send --app-name="\$APP" --urgency=normal "\$title" "\$body" || true
  fi
  printf '%s: %s\\n' "\$title" "\$body" >&2
  log_block "\$title" "\$body"
}

resolve_real_bin() {
  if [[ -n "\$REAL_BIN" && -x "\$REAL_BIN" ]]; then
    printf '%s\\n' "\$REAL_BIN"
    return 0
  fi

  if [[ -f "\$CFG_DIR/real-bin" ]]; then
    local saved
    saved="\$(<"\$CFG_DIR/real-bin")"
    if [[ -n "\$saved" && -x "\$saved" ]]; then
      printf '%s\\n' "\$saved"
      return 0
    fi
  fi

  local self candidate self_real
  self="\$(realpath -e "\${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "\${BASH_SOURCE[0]}")"
  while IFS= read -r candidate; do
    [[ -n "\$candidate" ]] || continue
    self_real="\$(realpath -e "\$candidate" 2>/dev/null || true)"
    if [[ -n "\$self_real" && "\$self_real" == "\$self" ]]; then
      continue
    fi
    if [[ "\$candidate" == */.local/bin/\$APP ]]; then
      continue
    fi
    if [[ -x "\$candidate" ]]; then
      printf '%s\\n' "\$candidate"
      return 0
    fi
  done < <(type -aP "\$APP" 2>/dev/null || true)

  return 1
}

export VPN_GATE_CONFIG="\${VPN_GATE_CONFIG:-\$CFG_DIR/config}"

if ! "\$CHECK" >/dev/null; then
  notify "\$APP заблокирован" "Включите VPN и попробуйте снова."
  exit 126
fi

REAL="\$(resolve_real_bin)" || {
  notify "\$APP не найден" "Укажите REAL_BIN при установке или переустановите gate."
  exit 127
}

exec "\$REAL" "\$@"
GATE_EOF
  chmod 0755 "$dest"
}

find_real_bin() {
  local app="$1"
  local bin_dir="$2"

  if [[ -n "${REAL_BIN:-}" && -x "${REAL_BIN}" ]]; then
    printf '%s\n' "$REAL_BIN"
    return 0
  fi

  local candidate
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    case "$candidate" in
      "$bin_dir/$app"|"$bin_dir/${app}-vpn-gate") continue ;;
    esac
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(type -aP "$app" 2>/dev/null || true)

  for candidate in "/usr/bin/$app" "/usr/local/bin/$app" "/bin/$app"; do
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

install_desktop_override() {
  local app="$1"
  local wrapper="$2"
  local desktop_src=""
  local name icon comment categories

  for desktop_src in \
    "/usr/share/applications/${app}.desktop" \
    "/usr/local/share/applications/${app}.desktop"; do
    [[ -f "$desktop_src" ]] && break
    desktop_src=""
  done

  name="$app"
  icon="$app"
  comment="Requires VPN"
  categories="Utility;"

  if [[ -n "$desktop_src" ]]; then
    name="$(grep -E '^Name=' "$desktop_src" | head -n1 | cut -d= -f2- || true)"
    [[ -n "$name" ]] || name="$app"
    icon="$(grep -E '^Icon=' "$desktop_src" | head -n1 | cut -d= -f2- || true)"
    [[ -n "$icon" ]] || icon="$app"
    comment="$(grep -E '^Comment=' "$desktop_src" | head -n1 | cut -d= -f2- || true)"
    [[ -n "$comment" ]] || comment="Requires VPN"
    comment="${comment} (VPN)"
    categories="$(grep -E '^Categories=' "$desktop_src" | head -n1 | cut -d= -f2- || true)"
    [[ -n "$categories" ]] || categories="Utility;"
  fi

  cat >"$DESKTOP_DIR/${app}.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=$name
Comment=$comment
Exec=$wrapper
Icon=$icon
Terminal=false
StartupNotify=true
Categories=$categories
EOF
}

do_uninstall() {
  local app="$1"
  local purge="${2:-0}"
  local cfg_dir gate wrapper

  cfg_dir="$(cfg_dir_for "$app")"
  gate="$BIN_DIR/${app}-vpn-gate"
  wrapper="$BIN_DIR/$app"

  rm -f "$wrapper" "$gate" "$DESKTOP_DIR/${app}.desktop"

  # Shared checker: remove only if no other *-vpn-gate remains.
  if ! compgen -G "$BIN_DIR/*-vpn-gate" >/dev/null; then
    rm -f "$BIN_DIR/$CHECK_NAME"
  fi

  if [[ "$purge" == "1" ]]; then
    rm -rf "$cfg_dir"
  fi

  printf 'Удалено: %s\n' "$app"
}

do_install() {
  local app="$1"
  local cfg_dir gate wrapper real
  local q_real q_check q_gate q_cfg

  cfg_dir="$(cfg_dir_for "$app")"
  gate="$BIN_DIR/${app}-vpn-gate"
  wrapper="$BIN_DIR/$app"

  mkdir -p "$BIN_DIR" "$cfg_dir" "$DESKTOP_DIR"

  if ! real="$(find_real_bin "$app" "$BIN_DIR")"; then
    printf 'Не найден бинарник «%s» в PATH.\n' "$app" >&2
    printf 'Установите программу или укажите:\n' >&2
    printf '  REAL_BIN=/полный/путь/%s %s %s\n' "$app" "$0" "$app" >&2
    exit 1
  fi

  if [[ "$(realpath -e "$real" 2>/dev/null || true)" == "$(realpath -e "$wrapper" 2>/dev/null || true)" ]]; then
    printf 'Похоже, «%s» уже является обёрткой. Укажите REAL_BIN на настоящий бинарник.\n' "$app" >&2
    exit 1
  fi

  write_vpn_check "$BIN_DIR/$CHECK_NAME"
  write_app_gate "$gate" "$app"

  printf '%s\n' "$real" >"$cfg_dir/real-bin"
  chmod 0644 "$cfg_dir/real-bin"

  if [[ ! -f "$cfg_dir/config" ]]; then
    cat >"$cfg_dir/config" <<EOF
# Сетевые интерфейсы VPN (через пробел)
VPN_IFACES="${VPN_IFACES:-wg0}"

# 1 = требовать маршрут через VPN-интерфейс
VPN_STRICT_ROUTE=0
EOF
    chmod 0644 "$cfg_dir/config"
  fi

  q_real="$(printf '%q' "$real")"
  q_check="$(printf '%q' "$BIN_DIR/$CHECK_NAME")"
  q_gate="$(printf '%q' "$gate")"
  q_cfg="$(printf '%q' "$cfg_dir/config")"

  cat >"$wrapper" <<EOF
#!/usr/bin/env bash
export VPN_GATE_REAL_BIN=$q_real
export VPN_GATE_CHECK=$q_check
export VPN_GATE_CONFIG=$q_cfg
exec $q_gate "\$@"
EOF
  chmod 0755 "$wrapper"

  install_desktop_override "$app" "$wrapper"

  case ":$PATH:" in
    *":$BIN_DIR:"*) ;;
    *)
      printf '\nДобавьте в ~/.bashrc или ~/.profile:\n  export PATH="%s:\$PATH"\n\n' "$BIN_DIR" >&2
      ;;
  esac

  printf 'Установлено для «%s».\n' "$app"
  printf '  real:    %s\n' "$real"
  printf '  wrapper: %s\n' "$wrapper"
  printf '  check:   %s/%s\n' "$BIN_DIR" "$CHECK_NAME"
  printf '\nПроверка:\n'
  printf '  %s && echo VPN_OK || echo NO_VPN\n' "$BIN_DIR/$CHECK_NAME"
  printf '  выключите VPN → %s должен отказать\n' "$app"
  printf '  включите VPN  → %s должен стартовать\n' "$app"

  if [[ "$(command -v "$app" 2>/dev/null || true)" != "$wrapper" ]]; then
    printf '\nВнимание: в PATH первым идёт: %s\n' "$(command -v "$app" 2>/dev/null || echo '?')" >&2
    printf 'Нужно, чтобы раньше был каталог %s\n' "$BIN_DIR" >&2
  fi
}

MODE="install"
APP=""
PURGE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --uninstall) MODE="uninstall"; shift ;;
    --purge) PURGE=1; shift ;;
    --) shift; break ;;
    -*)
      printf 'Неизвестный ключ: %s\n' "$1" >&2
      usage
      ;;
    *)
      if [[ -n "$APP" ]]; then
        printf 'Лишний аргумент: %s\n' "$1" >&2
        usage
      fi
      APP="$1"
      shift
      ;;
  esac
done

[[ -n "$APP" ]] || usage
is_ident "$APP" || {
  printf 'Некорректное имя приложения: %s\n' "$APP" >&2
  exit 2
}

if [[ "$MODE" == "uninstall" ]]; then
  do_uninstall "$APP" "$PURGE"
else
  do_install "$APP"
fi
