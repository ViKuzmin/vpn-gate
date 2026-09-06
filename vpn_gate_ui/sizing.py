"""Адаптивные размеры окон в зависимости от текущего разрешения экрана."""

from __future__ import annotations

import gi

gi.require_version("Gdk", "4.0")
from gi.repository import Gdk  # noqa: E402

_FALLBACK_SIZE = (1280, 800)


def monitor_size() -> tuple[int, int]:
    """Геометрия текущего (основного) монитора, либо разумный fallback."""
    try:
        display = Gdk.Display.get_default()
        if display is None:
            return _FALLBACK_SIZE
        monitors = display.get_monitors()
        if monitors.get_n_items() == 0:
            return _FALLBACK_SIZE
        geometry = monitors.get_item(0).get_geometry()
        if geometry.width > 0 and geometry.height > 0:
            return geometry.width, geometry.height
    except Exception:
        pass
    return _FALLBACK_SIZE


def scaled_size(
    frac_w: float, frac_h: float,
    min_w: int, min_h: int,
    max_w: int, max_h: int,
) -> tuple[int, int]:
    """Доля от размера экрана, ограниченная разумными мин/макс значениями."""
    screen_w, screen_h = monitor_size()
    width = max(min_w, min(max_w, round(screen_w * frac_w)))
    height = max(min_h, min(max_h, round(screen_h * frac_h)))
    return width, height
