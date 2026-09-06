"""Настройки самого UI (не путать с per-app конфигом gate'а)."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

from . import core

SETTINGS_DIR = core.CONFIG_HOME / "vpn-gate-ui"
SETTINGS_PATH = SETTINGS_DIR / "settings.json"
AUTOSTART_DIR = SETTINGS_DIR.parent / "autostart"
AUTOSTART_DESKTOP = AUTOSTART_DIR / "vpn-gate-ui.desktop"

APP_ID = "org.vpngate.Ui"
ICON_NAME = "vpn-gate"


@dataclass
class UiSettings:
    default_ifaces: str = "wg0"
    default_strict: bool = False
    notifications_enabled: bool = True
    autostart_enabled: bool = False
    poll_interval_sec: int = 5


def load_settings() -> UiSettings:
    if SETTINGS_PATH.is_file():
        try:
            data = json.loads(SETTINGS_PATH.read_text())
        except (OSError, ValueError):
            data = {}
    else:
        data = {}
    defaults = asdict(UiSettings())
    defaults.update({k: v for k, v in data.items() if k in defaults})
    return UiSettings(**defaults)


def save_settings(settings: UiSettings) -> None:
    SETTINGS_DIR.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(asdict(settings), ensure_ascii=False, indent=2))


def _launcher_command() -> str:
    override = os.environ.get("VPN_GATE_UI_LAUNCHER")
    if override:
        return override
    this_dir = Path(__file__).resolve().parent.parent
    launcher = this_dir / "vpn-gate-ui"
    if launcher.is_file():
        return str(launcher)
    return "vpn-gate-ui"


def set_autostart(enabled: bool) -> None:
    if enabled:
        AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        AUTOSTART_DESKTOP.write_text(
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=VPN Gate\n"
            "Comment=Индикатор состояния VPN и управление защищёнными приложениями\n"
            f"Exec={_launcher_command()} --background\n"
            f"Icon={ICON_NAME}\n"
            "Terminal=false\n"
            "NoDisplay=false\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
    else:
        try:
            AUTOSTART_DESKTOP.unlink()
        except FileNotFoundError:
            pass


def is_autostart_enabled() -> bool:
    return AUTOSTART_DESKTOP.is_file()


SYSTEM_DESKTOP_ENTRY = Path("/usr/share/applications/vpn-gate-ui.desktop")
SYSTEM_ICON = Path(f"/usr/share/icons/hicolor/scalable/apps/{ICON_NAME}.svg")
USER_ICON = core.DATA_HOME / "icons" / "hicolor" / "scalable" / "apps" / f"{ICON_NAME}.svg"


def _repo_logo_source() -> Path | None:
    """Путь к packaging/logo.svg при запуске прямо из репозитория (не из .deb)."""
    candidate = Path(__file__).resolve().parent.parent / "packaging" / "logo.svg"
    return candidate if candidate.is_file() else None


def ensure_icon_installed() -> None:
    """Устанавливает значок приложения в тему hicolor, если он ещё не там.

    Из .deb значок уже лежит в /usr/share/icons/hicolor/..., тогда ничего
    не делаем. При запуске прямо из репозитория копируем packaging/logo.svg
    в ~/.local/share/icons/hicolor/scalable/apps/, чтобы Icon=vpn-gate
    находился темой иконок.
    """
    if SYSTEM_ICON.is_file() or USER_ICON.is_file():
        return

    source = _repo_logo_source()
    if source is None:
        return

    USER_ICON.parent.mkdir(parents=True, exist_ok=True)
    USER_ICON.write_bytes(source.read_bytes())


def ensure_desktop_entry() -> None:
    """Регистрирует UI в меню приложений (~/.local/share/applications).

    Если приложение установлено системно (.deb), там уже есть свой
    .desktop-файл — не дублируем его в домашнем каталоге пользователя.
    """
    if SYSTEM_DESKTOP_ENTRY.is_file():
        return

    dest = core.DESKTOP_DIR / "vpn-gate-ui.desktop"
    core.DESKTOP_DIR.mkdir(parents=True, exist_ok=True)
    dest.write_text(
        "[Desktop Entry]\n"
        "Type=Application\n"
        "Name=VPN Gate\n"
        "Comment=Управление приложениями, защищёнными VPN\n"
        f"Exec={_launcher_command()}\n"
        f"Icon={ICON_NAME}\n"
        "Terminal=false\n"
        "StartupNotify=true\n"
        "Categories=Network;\n"
    )
