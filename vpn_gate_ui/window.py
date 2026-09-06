"""Главное окно (Dashboard): статус VPN + список защищённых приложений."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, GLib, Gtk  # noqa: E402

from . import core, dialogs, settings, sizing, vpncheck  # noqa: E402

_NARROW_WIDTH_PX = 480


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, app: Adw.Application):
        width, height = sizing.scaled_size(
            frac_w=0.32, frac_h=0.6,
            min_w=440, min_h=440,
            max_w=760, max_h=820,
        )
        super().__init__(application=app, title="VPN Gate",
                          default_width=width, default_height=height)
        self.set_size_request(360, 380)
        self.set_icon_name(settings.ICON_NAME)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="VPN Gate"))

        settings_btn = Gtk.Button(icon_name="emblem-system-symbolic")
        settings_btn.set_tooltip_text("Настройки")
        settings_btn.connect("clicked", self._open_settings)
        header.pack_end(settings_btn)

        log_btn = Gtk.Button(icon_name="dialog-warning-symbolic")
        log_btn.set_tooltip_text("Журнал блокировок")
        log_btn.connect("clicked", self._open_log)
        header.pack_end(log_btn)
        toolbar_view.add_top_bar(header)

        self.toast_overlay = Adw.ToastOverlay()

        root_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0)

        self.status_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10,
                                   margin_top=14, margin_bottom=14, margin_start=18, margin_end=18)
        self.status_icon = Gtk.Image(icon_name="dialog-question-symbolic", pixel_size=28)
        status_texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, hexpand=True)
        self.status_label = Gtk.Label(xalign=0, wrap=True)
        self.status_label.add_css_class("title-4")
        self.status_sub_label = Gtk.Label(xalign=0, wrap=True)
        self.status_sub_label.add_css_class("dim-label")
        self.status_sub_label.add_css_class("caption")
        status_texts.append(self.status_label)
        status_texts.append(self.status_sub_label)
        self.check_btn = Gtk.Button(label="Проверить сейчас", valign=Gtk.Align.CENTER,
                                     halign=Gtk.Align.START)
        self.check_btn.connect("clicked", lambda *_: self.refresh_status())
        self.status_box.append(self.status_icon)
        self.status_box.append(status_texts)
        self.status_box.append(self.check_btn)
        root_box.append(self.status_box)
        root_box.append(Gtk.Separator())

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_top(16)
        self.listbox.set_margin_bottom(16)
        self.listbox.set_margin_start(16)
        self.listbox.set_margin_end(16)

        empty_status = Adw.StatusPage(
            title="Нет защищённых приложений",
            description="Нажмите «Добавить приложение», чтобы создать первую защиту.",
            icon_name="security-medium-symbolic",
        )
        self.listbox.set_placeholder(empty_status)

        scroller = Gtk.ScrolledWindow(child=self.listbox, vexpand=True,
                                       hscrollbar_policy=Gtk.PolicyType.NEVER)
        root_box.append(scroller)
        root_box.append(Gtk.Separator())

        self.bottom_bar = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8,
                                   margin_top=10, margin_bottom=10, margin_start=18, margin_end=18)
        add_btn = Gtk.Button(label="+ Добавить приложение", hexpand=True)
        add_btn.add_css_class("suggested-action")
        add_btn.connect("clicked", self._open_add)
        refresh_btn = Gtk.Button(label="Обновить список", hexpand=True)
        refresh_btn.connect("clicked", lambda *_: self.refresh_all())
        self.bottom_bar.append(add_btn)
        self.bottom_bar.append(refresh_btn)
        root_box.append(self.bottom_bar)

        self.toast_overlay.set_child(root_box)
        toolbar_view.set_content(self.toast_overlay)
        self.set_content(toolbar_view)

        self._setup_breakpoint()

        self.refresh_all()
        GLib.timeout_add_seconds(5, self._on_timer)

    def _setup_breakpoint(self) -> None:
        """Переключает тесные горизонтальные ряды в вертикальную раскладку,
        когда окно становится узким — чтобы элементы не «слипались»."""
        condition = Adw.BreakpointCondition.new_length(
            Adw.BreakpointConditionLengthType.MAX_WIDTH, _NARROW_WIDTH_PX, Adw.LengthUnit.PX,
        )
        breakpoint_ = Adw.Breakpoint.new(condition)
        breakpoint_.add_setter(self.status_box, "orientation", Gtk.Orientation.VERTICAL)
        breakpoint_.add_setter(self.check_btn, "halign", Gtk.Align.FILL)
        breakpoint_.add_setter(self.bottom_bar, "orientation", Gtk.Orientation.VERTICAL)
        self.add_breakpoint(breakpoint_)

    def _on_timer(self) -> bool:
        self.refresh_status()
        return True

    def refresh_status(self) -> None:
        ui = settings.load_settings()
        ifaces = [i for i in ui.default_ifaces.split() if i] or vpncheck.DEFAULT_IFACES
        active = vpncheck.check_vpn(ifaces, ui.default_strict)

        for cls in ("success", "error"):
            self.status_label.remove_css_class(cls)

        if active:
            self.status_icon.set_from_icon_name("emblem-ok-symbolic")
            self.status_label.set_text("VPN подключен")
            self.status_label.add_css_class("success")
            self.status_sub_label.set_text(f"интерфейс: {active}")
        else:
            self.status_icon.set_from_icon_name("dialog-warning-symbolic")
            self.status_label.set_text("VPN отключен")
            self.status_label.add_css_class("error")
            self.status_sub_label.set_text(f"проверялись: {', '.join(ifaces)}")

    def refresh_all(self) -> None:
        self.refresh_status()
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

        for app_info in core.list_gated_apps():
            self.listbox.append(self._build_row(app_info))

    def _build_row(self, app_info: core.AppInfo) -> Adw.ActionRow:
        row = Adw.ActionRow(title=app_info.app)
        details = [f"iface: {app_info.ifaces}"]
        if app_info.strict:
            details.append("строгий режим")
        details.append(app_info.status_text)
        row.set_subtitle(" · ".join(details))

        icon_name = "emblem-ok-symbolic" if app_info.status_ok else "dialog-warning-symbolic"
        row.add_prefix(Gtk.Image(icon_name=icon_name, pixel_size=20))

        launch_btn = Gtk.Button(icon_name="media-playback-start-symbolic", valign=Gtk.Align.CENTER)
        launch_btn.set_tooltip_text("Запустить с аргументами")
        launch_btn.connect("clicked", lambda *_: self._open_launch(app_info.app))
        row.add_suffix(launch_btn)

        edit_btn = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER)
        edit_btn.set_tooltip_text("Изменить")
        edit_btn.connect("clicked", lambda *_: self._open_edit(app_info))
        row.add_suffix(edit_btn)

        delete_btn = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        delete_btn.set_tooltip_text("Удалить")
        delete_btn.connect("clicked", lambda *_: self._confirm_delete(app_info.app))
        row.add_suffix(delete_btn)

        row.set_activatable_widget(edit_btn)
        return row

    def _open_add(self, *_args) -> None:
        dialog = dialogs.AddAppDialog(self, on_installed=self._on_installed)
        dialog.present()

    def _on_installed(self) -> None:
        self.refresh_all()
        self._toast("Приложение установлено")

    def _open_launch(self, app: str) -> None:
        dialog = dialogs.LaunchAppDialog(
            self, app,
            on_launched=lambda: self._toast(f"«{app}» запущен"),
        )
        dialog.present()

    def _open_edit(self, app_info: core.AppInfo) -> None:
        dialog = dialogs.EditAppDialog(
            self, app_info,
            on_saved=lambda: (self.refresh_all(), self._toast("Настройки сохранены")),
            on_uninstalled=lambda: (self.refresh_all(), self._toast("Защита удалена")),
        )
        dialog.present()

    def _confirm_delete(self, app: str) -> None:
        dialogs.confirm_delete(
            self, app,
            lambda: (self.refresh_all(), self._toast("Защита удалена")),
        )

    def _open_settings(self, *_args) -> None:
        dialog = dialogs.SettingsDialog(self)
        dialog.present()

    def _open_log(self, *_args) -> None:
        dialog = dialogs.LogDialog(self)
        dialog.present()

    def _toast(self, message: str) -> None:
        self.toast_overlay.add_toast(Adw.Toast(title=message, timeout=3))
