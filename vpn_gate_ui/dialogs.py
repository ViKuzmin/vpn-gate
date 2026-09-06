"""Диалоги: добавление, редактирование приложения, настройки, подтверждения."""

from __future__ import annotations

import shlex
from typing import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gio, Gtk  # noqa: E402

from . import core, settings, sizing  # noqa: E402

_DIALOG_NARROW_WIDTH_PX = 420


def show_error(parent: Gtk.Window, heading: str, body: str) -> None:
    dialog = Adw.MessageDialog.new(parent, heading, body)
    dialog.add_response("ok", "ОК")
    dialog.set_default_response("ok")
    dialog.present()


def _labeled_entry_row(group: Adw.PreferencesGroup, title: str) -> tuple[Adw.ActionRow, Gtk.Entry]:
    row = Adw.ActionRow(title=title)
    entry = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=8)
    row.add_suffix(entry)
    row.set_activatable_widget(entry)
    group.add(row)
    return row, entry


def _dialog_size(frac_w: float = 0.26, frac_h: float = 0.4,
                  min_w: int = 380, min_h: int = 200,
                  max_w: int = 560, max_h: int = 680) -> tuple[int, int]:
    return sizing.scaled_size(frac_w, frac_h, min_w, min_h, max_w, max_h)


def _add_narrow_breakpoint(window: Adw.Window, *rows: Adw.PreferencesRow,
                            extra_setters: tuple[tuple[object, str, object], ...] = ()) -> None:
    """На узких окнах разрешает заголовкам строк перенос вместо усечения
    и применяет дополнительные (виджет, свойство, значение) настройки —
    например, переключает панель кнопок в вертикальную раскладку."""
    condition = Adw.BreakpointCondition.new_length(
        Adw.BreakpointConditionLengthType.MAX_WIDTH, _DIALOG_NARROW_WIDTH_PX, Adw.LengthUnit.PX,
    )
    bp = Adw.Breakpoint.new(condition)
    for row in rows:
        bp.add_setter(row, "title-lines", 0)
    for widget, prop, value in extra_setters:
        bp.add_setter(widget, prop, value)
    window.add_breakpoint(bp)


class AddAppDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window, on_installed: Callable[[], None]):
        width, height = _dialog_size(frac_h=0.5, min_h=420, max_h=560)
        super().__init__(
            transient_for=parent,
            modal=True,
            default_width=width,
            default_height=height,
            title="Добавить приложение",
        )
        self.set_size_request(340, 360)
        self._on_installed = on_installed

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Добавить приложение"))
        toolbar_view.add_top_bar(header)

        group = Adw.PreferencesGroup()

        _, self.name_entry = _labeled_entry_row(group, "Имя приложения")
        self.name_entry.set_placeholder_text("например, alacarte")
        self._setup_completion(self.name_entry)

        real_row, self.real_entry = _labeled_entry_row(group, "Реальный бинарник")
        self.real_entry.set_placeholder_text("определяется автоматически, если пусто")
        browse_btn = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        browse_btn.set_tooltip_text("Обзор…")
        browse_btn.connect("clicked", self._on_browse)
        real_row.add_suffix(browse_btn)

        ui_settings = settings.load_settings()

        _, self.ifaces_entry = _labeled_entry_row(group, "Интерфейсы VPN")
        self.ifaces_entry.set_text(ui_settings.default_ifaces)

        strict_row = Adw.SwitchRow(title="Строгий режим", subtitle="Требовать маршрут через VPN-интерфейс")
        strict_row.set_active(ui_settings.default_strict)
        self.strict_row = strict_row
        group.add(strict_row)

        self.error_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error_label.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18,
                           margin_bottom=18, margin_start=18, margin_end=18)
        content.append(group)
        content.append(self.error_label)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Отмена")
        cancel_btn.connect("clicked", lambda *_: self.close())
        self.install_btn = Gtk.Button(label="Установить")
        self.install_btn.add_css_class("suggested-action")
        self.install_btn.connect("clicked", self._on_install)
        button_box.append(cancel_btn)
        button_box.append(self.install_btn)
        content.append(button_box)

        scroller = Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        _add_narrow_breakpoint(self, real_row)

    def _setup_completion(self, entry: Gtk.Entry) -> None:
        store = Gtk.ListStore(str)
        for name in core.scan_path_apps():
            store.append([name])
        completion = Gtk.EntryCompletion()
        completion.set_model(store)
        completion.set_text_column(0)
        completion.set_inline_completion(True)
        completion.set_popup_completion(True)
        entry.set_completion(completion)

    def _on_browse(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Выберите реальный бинарник")
        dialog.open(self, None, self._on_browse_finished)

    def _on_browse_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except Exception:
            return
        if gfile is not None:
            path = gfile.get_path()
            if path:
                self.real_entry.set_text(path)

    def _on_install(self, *_args) -> None:
        app = self.name_entry.get_text().strip()
        real = self.real_entry.get_text().strip() or None
        ifaces = self.ifaces_entry.get_text().strip() or "wg0"
        strict = self.strict_row.get_active()

        if not app:
            self._show_inline_error("Укажите имя приложения.")
            return
        if not core.is_ident(app):
            self._show_inline_error("Недопустимое имя приложения (буквы, цифры, . _ + -).")
            return

        self.install_btn.set_sensitive(False)
        try:
            core.do_install(app, real_bin_override=real, ifaces=ifaces, strict=strict)
        except core.GateError as exc:
            self._show_inline_error(str(exc))
            self.install_btn.set_sensitive(True)
            return
        except OSError as exc:
            self._show_inline_error(f"Ошибка файловой системы: {exc}")
            self.install_btn.set_sensitive(True)
            return

        self._on_installed()
        self.close()

    def _show_inline_error(self, message: str) -> None:
        self.error_label.set_text(message)
        self.error_label.set_visible(True)


class LaunchAppDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window, app: str, on_launched: Callable[[], None]):
        width, height = _dialog_size(frac_h=0.28, min_h=220, max_h=320)
        super().__init__(
            transient_for=parent,
            modal=True,
            default_width=width,
            default_height=height,
            title=f"Запуск: {app}",
        )
        self.set_size_request(320, 220)
        self._app = app
        self._on_launched = on_launched

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=f"Запуск «{app}»"))
        toolbar_view.add_top_bar(header)

        group = Adw.PreferencesGroup()
        _, self.args_entry = _labeled_entry_row(group, "Аргументы командной строки")
        self.args_entry.set_placeholder_text("например: --file test.txt")
        self.args_entry.connect("activate", self._on_launch)

        self.error_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error_label.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18,
                           margin_bottom=18, margin_start=18, margin_end=18)
        content.append(group)
        content.append(self.error_label)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Отмена")
        cancel_btn.connect("clicked", lambda *_: self.close())
        self.launch_btn = Gtk.Button(label="Запустить")
        self.launch_btn.add_css_class("suggested-action")
        self.launch_btn.connect("clicked", self._on_launch)
        button_box.append(cancel_btn)
        button_box.append(self.launch_btn)
        content.append(button_box)

        toolbar_view.set_content(content)
        self.set_content(toolbar_view)

        self.args_entry.grab_focus()

    def _on_launch(self, *_args) -> None:
        raw = self.args_entry.get_text().strip()
        try:
            args = shlex.split(raw) if raw else []
        except ValueError as exc:
            self._show_inline_error(f"Не удалось разобрать аргументы: {exc}")
            return

        try:
            core.launch_wrapper(self._app, args)
        except core.GateError as exc:
            self._show_inline_error(str(exc))
            return
        except OSError as exc:
            self._show_inline_error(f"Не удалось запустить: {exc}")
            return

        self._on_launched()
        self.close()

    def _show_inline_error(self, message: str) -> None:
        self.error_label.set_text(message)
        self.error_label.set_visible(True)


class EditAppDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window, app_info: core.AppInfo,
                 on_saved: Callable[[], None], on_uninstalled: Callable[[], None]):
        width, height = _dialog_size(frac_h=0.55, min_h=460, max_h=600)
        super().__init__(
            transient_for=parent,
            modal=True,
            default_width=width,
            default_height=height,
            title=f"Настройки: {app_info.app}",
        )
        self.set_size_request(340, 380)
        self._app = app_info.app
        self._on_saved = on_saved
        self._on_uninstalled = on_uninstalled
        self._parent = parent

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title=app_info.app, subtitle="Настройки защиты"))
        toolbar_view.add_top_bar(header)

        group = Adw.PreferencesGroup()

        real_row, self.real_entry = _labeled_entry_row(group, "Реальный бинарник")
        self.real_entry.set_text(app_info.real_bin or "")
        browse_btn = Gtk.Button(icon_name="document-open-symbolic", valign=Gtk.Align.CENTER)
        browse_btn.set_tooltip_text("Обзор…")
        browse_btn.connect("clicked", self._on_browse)
        real_row.add_suffix(browse_btn)

        _, self.ifaces_entry = _labeled_entry_row(group, "Интерфейсы VPN")
        self.ifaces_entry.set_text(app_info.ifaces)

        strict_row = Adw.SwitchRow(title="Строгий режим", subtitle="Требовать маршрут через VPN-интерфейс")
        strict_row.set_active(app_info.strict)
        self.strict_row = strict_row
        group.add(strict_row)

        self.check_result = Gtk.Label(wrap=True, xalign=0)
        check_row = Adw.ActionRow(title="Проверка")
        check_btn = Gtk.Button(label="Проверить сейчас", valign=Gtk.Align.CENTER)
        check_btn.connect("clicked", self._on_check_now)
        check_row.add_suffix(check_btn)
        group.add(check_row)

        self.error_label = Gtk.Label(wrap=True, xalign=0, visible=False)
        self.error_label.add_css_class("error")

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12, margin_top=18,
                           margin_bottom=18, margin_start=18, margin_end=18)
        content.append(group)
        content.append(self.check_result)
        content.append(self.error_label)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
        remove_btn = Gtk.Button(label="Удалить защиту")
        remove_btn.add_css_class("destructive-action")
        remove_btn.connect("clicked", self._on_remove)
        button_box.append(remove_btn)

        spacer = Gtk.Box(hexpand=True)
        button_box.append(spacer)

        cancel_btn = Gtk.Button(label="Отмена")
        cancel_btn.connect("clicked", lambda *_: self.close())
        save_btn = Gtk.Button(label="Сохранить")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        button_box.append(cancel_btn)
        button_box.append(save_btn)
        content.append(button_box)

        scroller = Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        _add_narrow_breakpoint(
            self, real_row,
            extra_setters=((button_box, "orientation", Gtk.Orientation.VERTICAL),),
        )

    def _on_browse(self, *_args) -> None:
        dialog = Gtk.FileDialog(title="Выберите реальный бинарник")
        dialog.open(self, None, self._on_browse_finished)

    def _on_browse_finished(self, dialog: Gtk.FileDialog, result: Gio.AsyncResult) -> None:
        try:
            gfile = dialog.open_finish(result)
        except Exception:
            return
        if gfile is not None:
            path = gfile.get_path()
            if path:
                self.real_entry.set_text(path)

    def _on_check_now(self, *_args) -> None:
        from . import vpncheck
        ifaces = [i for i in self.ifaces_entry.get_text().split() if i]
        active = vpncheck.check_vpn(ifaces, self.strict_row.get_active())
        if active:
            self.check_result.set_text(f"VPN подключен через «{active}».")
            self.check_result.remove_css_class("error")
        else:
            self.check_result.set_text("VPN не обнаружен для указанных интерфейсов.")
            self.check_result.add_css_class("error")

    def _on_save(self, *_args) -> None:
        real = self.real_entry.get_text().strip()
        ifaces = self.ifaces_entry.get_text().strip() or "wg0"
        strict = self.strict_row.get_active()

        if real:
            core.write_real_bin(self._app, real)
        core.write_config(self._app, ifaces, strict)
        self._on_saved()
        self.close()

    def _on_remove(self, *_args) -> None:
        self.close()
        confirm_delete(self._parent, self._app, self._on_uninstalled)


def confirm_delete(parent: Gtk.Window, app: str, on_deleted: Callable[[], None]) -> None:
    dialog = Adw.MessageDialog.new(parent, f"Удалить защиту для «{app}»?",
                                    "Обёртка и .desktop-файл будут удалены.")
    dialog.add_response("cancel", "Отмена")
    dialog.add_response("delete", "Удалить")
    dialog.add_response("purge", "Удалить с конфигом")
    dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_response_appearance("purge", Adw.ResponseAppearance.DESTRUCTIVE)
    dialog.set_default_response("cancel")
    dialog.set_close_response("cancel")

    def _on_response(_dialog, response):
        if response in ("delete", "purge"):
            core.do_uninstall(app, purge=(response == "purge"))
            on_deleted()

    dialog.connect("response", _on_response)
    dialog.present()


class LogDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window):
        width, height = _dialog_size(frac_w=0.3, frac_h=0.55, min_w=420, min_h=420,
                                      max_w=640, max_h=760)
        super().__init__(
            transient_for=parent,
            modal=True,
            default_width=width,
            default_height=height,
            title="Журнал блокировок",
        )
        self.set_size_request(340, 320)

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Журнал блокировок"))
        refresh_btn = Gtk.Button(icon_name="view-refresh-symbolic")
        refresh_btn.set_tooltip_text("Обновить")
        refresh_btn.connect("clicked", lambda *_: self._reload())
        header.pack_start(refresh_btn)
        clear_btn = Gtk.Button(icon_name="user-trash-symbolic")
        clear_btn.set_tooltip_text("Очистить журнал")
        clear_btn.connect("clicked", self._on_clear)
        header.pack_end(clear_btn)
        toolbar_view.add_top_bar(header)

        self.listbox = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.listbox.add_css_class("boxed-list")
        self.listbox.set_margin_top(16)
        self.listbox.set_margin_bottom(16)
        self.listbox.set_margin_start(16)
        self.listbox.set_margin_end(16)

        self.empty_status = Adw.StatusPage(
            title="Блокировок пока не было",
            description="Здесь появятся попытки запуска защищённых приложений без VPN.",
            icon_name="dialog-information-symbolic",
        )
        self.listbox.set_placeholder(self.empty_status)

        scroller = Gtk.ScrolledWindow(child=self.listbox, vexpand=True,
                                       hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

        self._reload()

    def _reload(self) -> None:
        child = self.listbox.get_first_child()
        while child is not None:
            next_child = child.get_next_sibling()
            self.listbox.remove(child)
            child = next_child

        for event in core.list_block_events():
            row = Adw.ActionRow(title=f"{event.app} — {event.title}")
            row.set_subtitle(f"{event.timestamp} · {event.body}")
            row.add_prefix(Gtk.Image(icon_name="dialog-warning-symbolic", pixel_size=20))
            self.listbox.append(row)

    def _on_clear(self, *_args) -> None:
        core.clear_block_log()
        self._reload()


class SettingsDialog(Adw.Window):
    def __init__(self, parent: Gtk.Window):
        width, height = _dialog_size(frac_h=0.55, min_h=460, max_h=600)
        super().__init__(
            transient_for=parent,
            modal=True,
            default_width=width,
            default_height=height,
            title="Настройки",
        )
        self.set_size_request(340, 380)
        self._ui_settings = settings.load_settings()

        toolbar_view = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_title_widget(Adw.WindowTitle(title="Настройки"))
        toolbar_view.add_top_bar(header)

        group = Adw.PreferencesGroup(title="Значения по умолчанию для новых приложений")
        _, self.ifaces_entry = _labeled_entry_row(group, "Интерфейсы VPN")
        self.ifaces_entry.set_text(self._ui_settings.default_ifaces)

        self.strict_row = Adw.SwitchRow(title="Строгий режим по умолчанию")
        self.strict_row.set_active(self._ui_settings.default_strict)
        group.add(self.strict_row)

        group2 = Adw.PreferencesGroup(title="Приложение")
        self.notify_row = Adw.SwitchRow(title="Уведомления",
                                         subtitle="Показывать системные уведомления о блокировке")
        self.notify_row.set_active(self._ui_settings.notifications_enabled)
        group2.add(self.notify_row)

        self.autostart_row = Adw.SwitchRow(title="Автозапуск",
                                            subtitle="Запускать в трее при входе в систему")
        self.autostart_row.set_active(self._ui_settings.autostart_enabled)
        group2.add(self.autostart_row)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18, margin_top=18,
                           margin_bottom=18, margin_start=18, margin_end=18)
        content.append(group)
        content.append(group2)

        button_box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8, halign=Gtk.Align.END)
        cancel_btn = Gtk.Button(label="Отмена")
        cancel_btn.connect("clicked", lambda *_: self.close())
        save_btn = Gtk.Button(label="Сохранить")
        save_btn.add_css_class("suggested-action")
        save_btn.connect("clicked", self._on_save)
        button_box.append(cancel_btn)
        button_box.append(save_btn)
        content.append(button_box)

        scroller = Gtk.ScrolledWindow(child=content, hscrollbar_policy=Gtk.PolicyType.NEVER)
        toolbar_view.set_content(scroller)
        self.set_content(toolbar_view)

    def _on_save(self, *_args) -> None:
        self._ui_settings.default_ifaces = self.ifaces_entry.get_text().strip() or "wg0"
        self._ui_settings.default_strict = self.strict_row.get_active()
        self._ui_settings.notifications_enabled = self.notify_row.get_active()
        autostart = self.autostart_row.get_active()
        self._ui_settings.autostart_enabled = autostart
        settings.save_settings(self._ui_settings)
        settings.set_autostart(autostart)
        self.close()
