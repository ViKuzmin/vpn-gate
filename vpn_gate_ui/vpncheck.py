"""Прямая (не через subprocess-обёртку) проверка состояния VPN.

Логика зеркалит vpn-gate-check, генерируемый core.write_vpn_check, чтобы
UI могло мгновенно показывать статус без установленного gate.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

DEFAULT_IFACES = ["wg0"]


def _iface_exists(iface: str) -> bool:
    return Path(f"/sys/class/net/{iface}").is_dir()


def _iface_is_up(iface: str) -> bool:
    if not _iface_exists(iface):
        return False

    operstate_path = Path(f"/sys/class/net/{iface}/operstate")
    if operstate_path.is_file():
        try:
            operstate = operstate_path.read_text().strip()
        except OSError:
            operstate = ""
        if operstate in ("up", "unknown"):
            flags_path = Path(f"/sys/class/net/{iface}/flags")
            if flags_path.is_file():
                try:
                    flags = int(flags_path.read_text().strip(), 16)
                except (OSError, ValueError):
                    flags = 0
                if flags & 0x1:
                    return True
            else:
                return operstate == "up"

    ip_bin = shutil.which("ip")
    if ip_bin:
        try:
            out = subprocess.run(
                [ip_bin, "-o", "link", "show", iface],
                capture_output=True, text=True, timeout=2,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            out = ""
        if not out:
            return False
        return ",UP," in out or " state UP " in out

    return False


def _has_vpn_route(iface: str) -> bool:
    ip_bin = shutil.which("ip")
    if not ip_bin:
        return False
    try:
        out = subprocess.run(
            [ip_bin, "-4", "route", "show"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return False
    for line in out.splitlines():
        if line.startswith(("default", "0.0.0.0/1", "128.0.0.0/1")):
            fields = line.split()
            if "dev" in fields:
                idx = fields.index("dev")
                if idx + 1 < len(fields) and fields[idx + 1] == iface:
                    return True
    return False


def check_vpn(ifaces: list[str] | None = None, strict: bool = False) -> str | None:
    """Возвращает имя активного VPN-интерфейса или None, если VPN не подключен."""
    for iface in (ifaces or DEFAULT_IFACES):
        iface = iface.strip()
        if not iface:
            continue
        if _iface_is_up(iface):
            if strict and not _has_vpn_route(iface):
                continue
            return iface
    return None
