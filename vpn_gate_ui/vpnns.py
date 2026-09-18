"""Статус и управление network-namespace kill switch (vpn-ns-run)."""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

NS_NAME = os.environ.get("VPN_NS_NAME", "vpnonly")
VETH_HOST = os.environ.get("VPN_VETH_HOST", "veth-vpn0")
TABLE_ID = os.environ.get("VPN_TABLE_ID", "200")
WATCH_PID_FILE = Path(os.environ.get("VPN_NS_WATCH_PID", f"/run/vpn-ns-{NS_NAME}.pid"))


def find_vpn_ns_run() -> Path | None:
    env = os.environ.get("VPN_NS_RUN")
    if env and os.access(env, os.X_OK):
        return Path(env)

    repo = Path(__file__).resolve().parent.parent / "vpn-ns-run"
    candidates = [
        Path("/usr/bin/vpn-ns-run"),
        Path("/usr/local/bin/vpn-ns-run"),
        Path(os.environ.get("XDG_BIN_HOME") or (Path.home() / ".local" / "bin")) / "vpn-ns-run",
        repo,
    ]
    which = shutil.which("vpn-ns-run")
    if which:
        candidates.append(Path(which))

    for path in candidates:
        if path.is_file() and os.access(path, os.X_OK):
            return path
    return None


def _sudo_prefix(ns_run: Path) -> list[str]:
    if os.geteuid() == 0:
        return [str(ns_run)]
    sudo = shutil.which("sudo")
    if not sudo:
        raise RuntimeError("нужен sudo для управления kill switch namespace")
    # Сначала пробуем без пароля (sudoers NOPASSWD).
    try:
        ok = subprocess.run(
            [sudo, "-n", "true"],
            capture_output=True, timeout=2,
        ).returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if ok:
        return [sudo, "-n", "--", str(ns_run)]
    return [sudo, "--", str(ns_run)]


def run_ns_command(*args: str, timeout: float = 15) -> subprocess.CompletedProcess[str]:
    ns_run = find_vpn_ns_run()
    if ns_run is None:
        raise FileNotFoundError("vpn-ns-run не найден")
    cmd = [*_sudo_prefix(ns_run), *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


@dataclass
class NsStatus:
    available: bool
    ns_exists: bool
    veth_up: bool
    watcher: bool
    vpn_routes: bool
    detail: str


def query_status() -> NsStatus:
    ns_run = find_vpn_ns_run()
    if ns_run is None:
        return NsStatus(
            available=False,
            ns_exists=False,
            veth_up=False,
            watcher=False,
            vpn_routes=False,
            detail="vpn-ns-run не найден",
        )

    ns_exists = Path(f"/var/run/netns/{NS_NAME}").exists()
    veth_up = Path(f"/sys/class/net/{VETH_HOST}").is_dir()
    watcher = False
    if WATCH_PID_FILE.is_file():
        try:
            pid = int(WATCH_PID_FILE.read_text().strip())
            watcher = Path(f"/proc/{pid}").exists()
        except (OSError, ValueError):
            watcher = False

    vpn_routes = False
    out = ""
    ip_bin = shutil.which("ip") or "/usr/sbin/ip"
    try:
        out = subprocess.run(
            [ip_bin, "route", "show", "table", TABLE_ID],
            capture_output=True, text=True, timeout=2,
        ).stdout
        vpn_routes = any(f"dev {iface}" in out for iface in ("amn0", "wg0", "tun0"))
    except (OSError, subprocess.SubprocessError):
        out = ""

    if not ns_exists:
        detail = "namespace не активен"
    elif vpn_routes:
        detail = "namespace активен · маршруты через VPN"
    elif "blackhole" in out:
        detail = "namespace активен · VPN down (kill switch)"
    else:
        detail = "namespace активен"

    if watcher and ns_exists:
        detail += " · watcher"

    return NsStatus(
        available=True,
        ns_exists=ns_exists,
        veth_up=veth_up,
        watcher=watcher,
        vpn_routes=vpn_routes,
        detail=detail,
    )


def ns_up() -> str:
    proc = run_ns_command("--up")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ошибка --up").strip())
    return (proc.stderr or proc.stdout or "ok").strip()


def ns_down() -> str:
    proc = run_ns_command("--down")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ошибка --down").strip())
    return (proc.stderr or proc.stdout or "ok").strip()


def ns_repair() -> str:
    proc = run_ns_command("--repair")
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "ошибка --repair").strip())
    return (proc.stderr or proc.stdout or "ok").strip()
