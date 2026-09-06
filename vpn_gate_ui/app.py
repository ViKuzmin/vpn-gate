"""Точка входа GTK4/Adwaita приложения."""

from __future__ import annotations

import sys

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio  # noqa: E402

from . import settings  # noqa: E402
from .settings import APP_ID  # noqa: E402
from .window import MainWindow  # noqa: E402


class VpnGateApp(Adw.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID,
                          flags=Gio.ApplicationFlags.HANDLES_COMMAND_LINE)
        self._window: MainWindow | None = None
        self.connect("activate", self._on_activate)
        self.connect("command-line", self._on_command_line)

    def _on_activate(self, _app) -> None:
        if self._window is None:
            settings.ensure_icon_installed()
            settings.ensure_desktop_entry()
            self._window = MainWindow(self)
        self._window.refresh_all()
        self._window.present()

    def _on_command_line(self, _app, _cmdline) -> int:
        # Повторный запуск (в т.ч. из автозапуска) просто поднимает существующее окно.
        self.activate()
        return 0


def main() -> int:
    app = VpnGateApp()
    return app.run(sys.argv)


if __name__ == "__main__":
    raise SystemExit(main())
