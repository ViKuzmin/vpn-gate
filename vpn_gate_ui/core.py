"""Бизнес-логика управления gate'ами приложений.

Питоновский порт логики install-vpn-gate.sh: тот же layout на диске
(~/.local/bin/<app>, ~/.local/bin/<app>-vpn-gate, ~/.local/bin/vpn-gate-check,
~/.config/<app>-vpn-gate/{config,real-bin}), так что CLI-скрипт и это
приложение могут управлять одними и теми же установками.
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

HOME = Path.home()
BIN_DIR = Path(os.environ.get("XDG_BIN_HOME") or (HOME / ".local" / "bin"))
DATA_HOME = Path(os.environ.get("XDG_DATA_HOME") or (HOME / ".local" / "share"))
DESKTOP_DIR = DATA_HOME / "applications"
CONFIG_HOME = Path(os.environ.get("XDG_CONFIG_HOME") or (HOME / ".config"))
STATE_HOME = Path(os.environ.get("XDG_STATE_HOME") or (HOME / ".local" / "state"))
CHECK_NAME = "vpn-gate-check"
GATE_SUFFIX = "-vpn-gate"
LOG_DIR = STATE_HOME / "vpn-gate"
LOG_FILE = LOG_DIR / "events.log"

_IDENT_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9._+-]*$")


class GateError(Exception):
    """Ожидаемая ошибка бизнес-логики (показывается пользователю как есть)."""


def is_ident(name: str) -> bool:
    return bool(_IDENT_RE.match(name))


def cfg_dir_for(app: str) -> Path:
    return CONFIG_HOME / f"{app}-vpn-gate"


def _require_ident(app: str) -> None:
    if not is_ident(app):
        raise GateError(f"Некорректное имя приложения: {app}")


# --------------------------------------------------------------------------
# Шаблоны генерируемых bash-скриптов (идентичны install-vpn-gate.sh,
# оставлены как bash, чтобы проверка при запуске приложения была быстрой и
# не тянула Python/GTK в runtime).
# --------------------------------------------------------------------------

VPN_CHECK_SCRIPT = r"""#!/usr/bin/env bash
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
"""

_GATE_TEMPLATE = r"""#!/usr/bin/env bash
# Launch the real __APP__ binary only when the VPN is connected.
set -euo pipefail

APP=__APP_Q__
CHECK="${VPN_GATE_CHECK:-${XDG_BIN_HOME:-$HOME/.local/bin}/vpn-gate-check}"
REAL_BIN="${VPN_GATE_REAL_BIN:-}"
CFG_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/${APP}-vpn-gate"
LOG_DIR="${VPN_GATE_LOG_DIR:-${XDG_STATE_HOME:-$HOME/.local/state}/vpn-gate}"
LOG_FILE="$LOG_DIR/events.log"
LOG_MAX_LINES=500
LOG_KEEP_LINES=300

log_block() {
  local title="$1"
  local body="$2"
  local ts
  ts="$(date -Is 2>/dev/null || date)"

  title="${title//$'\t'/ }"
  title="${title//$'\n'/ }"
  body="${body//$'\t'/ }"
  body="${body//$'\n'/ }"

  mkdir -p "$LOG_DIR" 2>/dev/null || return 0
  printf '%s\t%s\t%s\t%s\n' "$ts" "$APP" "$title" "$body" >>"$LOG_FILE" 2>/dev/null || return 0

  local total
  total="$(wc -l <"$LOG_FILE" 2>/dev/null || printf '0')"
  if (( total > LOG_MAX_LINES )); then
    tail -n "$LOG_KEEP_LINES" "$LOG_FILE" >"$LOG_FILE.tmp" 2>/dev/null \
      && mv -f "$LOG_FILE.tmp" "$LOG_FILE" 2>/dev/null
  fi
}

notify() {
  local title="$1"
  local body="$2"
  if command -v notify-send >/dev/null 2>&1; then
    notify-send --app-name="$APP" --urgency=normal "$title" "$body" || true
  fi
  printf '%s: %s\n' "$title" "$body" >&2
  log_block "$title" "$body"
}

resolve_real_bin() {
  if [[ -n "$REAL_BIN" && -x "$REAL_BIN" ]]; then
    printf '%s\n' "$REAL_BIN"
    return 0
  fi

  if [[ -f "$CFG_DIR/real-bin" ]]; then
    local saved
    saved="$(<"$CFG_DIR/real-bin")"
    if [[ -n "$saved" && -x "$saved" ]]; then
      printf '%s\n' "$saved"
      return 0
    fi
  fi

  local self candidate self_real
  self="$(realpath -e "${BASH_SOURCE[0]}" 2>/dev/null || printf '%s' "${BASH_SOURCE[0]}")"
  while IFS= read -r candidate; do
    [[ -n "$candidate" ]] || continue
    self_real="$(realpath -e "$candidate" 2>/dev/null || true)"
    if [[ -n "$self_real" && "$self_real" == "$self" ]]; then
      continue
    fi
    if [[ "$candidate" == */.local/bin/$APP ]]; then
      continue
    fi
    if [[ -x "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done < <(type -aP "$APP" 2>/dev/null || true)

  return 1
}

export VPN_GATE_CONFIG="${VPN_GATE_CONFIG:-$CFG_DIR/config}"

if ! "$CHECK" >/dev/null; then
  notify "$APP заблокирован" "Включите VPN и попробуйте снова."
  exit 126
fi

REAL="$(resolve_real_bin)" || {
  notify "$APP не найден" "Укажите REAL_BIN при установке или переустановите gate."
  exit 127
}

exec "$REAL" "$@"
"""


def write_vpn_check(dest: Path) -> None:
    dest.write_text(VPN_CHECK_SCRIPT)
    dest.chmod(0o755)


def write_app_gate(dest: Path, app: str) -> None:
    content = _GATE_TEMPLATE.replace("__APP__", app).replace("__APP_Q__", shlex.quote(app))
    dest.write_text(content)
    dest.chmod(0o755)


# --------------------------------------------------------------------------
# Поиск бинарников / .desktop
# --------------------------------------------------------------------------

def _path_dirs() -> list[str]:
    return [d for d in os.environ.get("PATH", "").split(":") if d]


def find_real_bin(app: str, bin_dir: Path, real_bin_env: str | None = None) -> str | None:
    if real_bin_env and os.access(real_bin_env, os.X_OK):
        return real_bin_env

    excluded = {str(bin_dir / app), str(bin_dir / f"{app}{GATE_SUFFIX}")}
    for d in _path_dirs():
        candidate = os.path.join(d, app)
        if candidate in excluded:
            continue
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate

    for d in ("/usr/bin", "/usr/local/bin", "/bin"):
        candidate = os.path.join(d, app)
        if os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def scan_path_apps() -> list[str]:
    """Список исполняемых имён из PATH — для автокомплита в диалоге добавления."""
    names: set[str] = set()
    for d in _path_dirs():
        if not os.path.isdir(d):
            continue
        try:
            with os.scandir(d) as it:
                for entry in it:
                    try:
                        if entry.is_file(follow_symlinks=True) and os.access(entry.path, os.X_OK):
                            names.add(entry.name)
                    except OSError:
                        continue
        except OSError:
            continue
    return sorted(names)


def _grab_desktop_key(text: str, key: str, default: str) -> str:
    m = re.search(rf"^{key}=(.*)$", text, re.MULTILINE)
    if m and m.group(1).strip():
        return m.group(1).strip()
    return default


def install_desktop_override(app: str, wrapper: Path) -> None:
    desktop_src = None
    for candidate in (
        Path("/usr/share/applications") / f"{app}.desktop",
        Path("/usr/local/share/applications") / f"{app}.desktop",
    ):
        if candidate.is_file():
            desktop_src = candidate
            break

    name, icon, comment, categories = app, app, "Requires VPN", "Utility;"
    if desktop_src is not None:
        text = desktop_src.read_text(errors="ignore")
        name = _grab_desktop_key(text, "Name", app)
        icon = _grab_desktop_key(text, "Icon", app)
        comment = _grab_desktop_key(text, "Comment", "Requires VPN") + " (VPN)"
        categories = _grab_desktop_key(text, "Categories", "Utility;")

    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    dest = DESKTOP_DIR / f"{app}.desktop"
    dest.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        f"Name={name}\n"
        f"Comment={comment}\n"
        f"Exec={wrapper}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        f"Categories={categories}\n"
    )


# --------------------------------------------------------------------------
# Конфиг приложения (интерфейсы, строгий режим, путь к реальному бинарнику)
# --------------------------------------------------------------------------

def parse_config(config_path: Path) -> tuple[str, bool]:
    ifaces, strict = "wg0", False
    if config_path.is_file():
        text = config_path.read_text(errors="ignore")
        m = re.search(r'VPN_IFACES\s*=\s*"([^"]*)"', text)
        if m and m.group(1).strip():
            ifaces = m.group(1).strip()
        m2 = re.search(r"VPN_STRICT_ROUTE\s*=\s*\"?([01])\"?", text)
        if m2:
            strict = m2.group(1) == "1"
    return ifaces, strict


def write_config(app: str, ifaces: str, strict: bool) -> None:
    cfg_dir = cfg_dir_for(app)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    config_path = cfg_dir / "config"
    config_path.write_text(
        "# Сетевые интерфейсы VPN (через пробел)\n"
        f'VPN_IFACES="{ifaces}"\n\n'
        "# 1 = требовать маршрут через VPN-интерфейс\n"
        f"VPN_STRICT_ROUTE={1 if strict else 0}\n"
    )
    config_path.chmod(0o644)


def read_real_bin(app: str) -> str | None:
    path = cfg_dir_for(app) / "real-bin"
    if not path.is_file():
        return None
    value = path.read_text(errors="ignore").strip()
    return value or None


def write_real_bin(app: str, real: str) -> None:
    cfg_dir = cfg_dir_for(app)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    path = cfg_dir / "real-bin"
    path.write_text(real + "\n")
    path.chmod(0o644)


# --------------------------------------------------------------------------
# Install / uninstall / list
# --------------------------------------------------------------------------

@dataclass
class InstallResult:
    app: str
    real_bin: str
    wrapper: Path
    gate: Path
    check: Path
    path_warning: bool


def do_install(
    app: str,
    real_bin_override: str | None = None,
    ifaces: str = "wg0",
    strict: bool = False,
) -> InstallResult:
    _require_ident(app)

    cfg_dir = cfg_dir_for(app)
    gate = BIN_DIR / f"{app}{GATE_SUFFIX}"
    wrapper = BIN_DIR / app

    BIN_DIR.mkdir(parents=True, exist_ok=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    DESKTOP_DIR.mkdir(parents=True, exist_ok=True)

    real = real_bin_override if real_bin_override else find_real_bin(app, BIN_DIR)
    if not real:
        raise GateError(
            f"Не найден бинарник «{app}» в PATH.\n"
            "Укажите путь к реальному бинарнику вручную."
        )
    if not os.access(real, os.X_OK):
        raise GateError(f"Указанный путь не является исполняемым файлом: {real}")

    real_resolved = os.path.realpath(real)
    wrapper_resolved = os.path.realpath(wrapper) if wrapper.exists() else None
    if wrapper_resolved and real_resolved == wrapper_resolved:
        raise GateError(
            f"Похоже, «{app}» уже является обёрткой. Укажите путь к настоящему бинарнику."
        )

    write_vpn_check(BIN_DIR / CHECK_NAME)
    write_app_gate(gate, app)
    write_real_bin(app, real)

    if not (cfg_dir / "config").exists():
        write_config(app, ifaces, strict)

    q_real = shlex.quote(real)
    q_check = shlex.quote(str(BIN_DIR / CHECK_NAME))
    q_gate = shlex.quote(str(gate))
    q_cfg = shlex.quote(str(cfg_dir / "config"))

    wrapper.write_text(
        "#!/usr/bin/env bash\n"
        f"export VPN_GATE_REAL_BIN={q_real}\n"
        f"export VPN_GATE_CHECK={q_check}\n"
        f"export VPN_GATE_CONFIG={q_cfg}\n"
        f"exec {q_gate} \"$@\"\n"
    )
    wrapper.chmod(0o755)

    install_desktop_override(app, wrapper)

    path_warning = str(BIN_DIR) not in _path_dirs()

    return InstallResult(
        app=app,
        real_bin=real,
        wrapper=wrapper,
        gate=gate,
        check=BIN_DIR / CHECK_NAME,
        path_warning=path_warning,
    )


def do_uninstall(app: str, purge: bool = False) -> None:
    _require_ident(app)

    cfg_dir = cfg_dir_for(app)
    gate = BIN_DIR / f"{app}{GATE_SUFFIX}"
    wrapper = BIN_DIR / app

    for path in (wrapper, gate, DESKTOP_DIR / f"{app}.desktop"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    if not any(BIN_DIR.glob(f"*{GATE_SUFFIX}")):
        try:
            (BIN_DIR / CHECK_NAME).unlink()
        except FileNotFoundError:
            pass

    if purge:
        shutil.rmtree(cfg_dir, ignore_errors=True)


def launch_wrapper(app: str, args: list[str]) -> None:
    """Запускает обёртку приложения (~/.local/bin/<app>) с заданными аргументами.

    Обёртка сама решит, пропускать запуск или блокировать (в зависимости от
    состояния VPN) — здесь только детач-запуск процесса, без ожидания.
    """
    _require_ident(app)
    wrapper = BIN_DIR / app
    if not wrapper.is_file():
        raise GateError(f"Обёртка для «{app}» не найдена: {wrapper}")

    subprocess.Popen(
        [str(wrapper), *args],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


@dataclass
class AppInfo:
    app: str
    real_bin: str | None
    ifaces: str
    strict: bool
    wrapper_exists: bool
    gate_path: Path
    wrapper_path: Path

    @property
    def status_ok(self) -> bool:
        return bool(self.real_bin) and os.access(self.real_bin, os.X_OK) and self.wrapper_exists

    @property
    def status_text(self) -> str:
        if not self.wrapper_exists:
            return "обёртка отсутствует"
        if not self.real_bin:
            return "путь не задан"
        if not os.access(self.real_bin, os.X_OK):
            return "бинарник не найден"
        return "OK"


@dataclass
class BlockEvent:
    timestamp: str
    app: str
    title: str
    body: str


def list_block_events(limit: int = 200) -> list[BlockEvent]:
    """Читает журнал блокировок запуска, новые события — первыми."""
    if not LOG_FILE.is_file():
        return []
    events: list[BlockEvent] = []
    try:
        lines = LOG_FILE.read_text(errors="ignore").splitlines()
    except OSError:
        return []
    for line in lines:
        parts = line.split("\t", 3)
        if len(parts) != 4:
            continue
        ts, app, title, body = parts
        events.append(BlockEvent(timestamp=ts, app=app, title=title, body=body))
    events.reverse()
    return events[:limit]


def clear_block_log() -> None:
    try:
        LOG_FILE.unlink()
    except FileNotFoundError:
        pass


def list_gated_apps() -> list[AppInfo]:
    result: list[AppInfo] = []
    if not BIN_DIR.is_dir():
        return result
    for gate_path in sorted(BIN_DIR.glob(f"*{GATE_SUFFIX}")):
        app = gate_path.name[: -len(GATE_SUFFIX)]
        if not app:
            continue
        cfg_dir = cfg_dir_for(app)
        real_bin = read_real_bin(app)
        ifaces, strict = parse_config(cfg_dir / "config")
        wrapper_path = BIN_DIR / app
        result.append(
            AppInfo(
                app=app,
                real_bin=real_bin,
                ifaces=ifaces,
                strict=strict,
                wrapper_exists=wrapper_path.exists(),
                gate_path=gate_path,
                wrapper_path=wrapper_path,
            )
        )
    return result
