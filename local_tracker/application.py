from __future__ import annotations

from importlib.resources import files

from gi.repository import Adw, Gdk, Gio, GLib, Gtk

from .indicator import StatusNotifier
from .service import TrackerService
from .storage import StorageError


APP_ID = "io.github.localtracker.LocalTracker"
TIMER_NOTIFICATION_ID = "active-timer"


class LocalTrackerApplication(Adw.Application):
    def __init__(self) -> None:
        super().__init__(
            application_id=APP_ID,
            flags=Gio.ApplicationFlags.DEFAULT_FLAGS,
        )
        self.service: TrackerService | None = None
        self.window = None
        self.indicator: StatusNotifier | None = None
        self._tray_held = False
        self._timer_held = False

        self.create_action("quit", self.on_quit, ["<primary>q"])
        self.create_action("show", self.on_show)
        self.create_action("show-tracker", self.on_show_tracker, ["<primary>1"])
        self.create_action("show-reports", self.on_show_reports, ["<primary>2"])
        self.create_action("stop-timer", self.on_stop_timer)
        self.create_action("about", self.on_about)

    def do_startup(self) -> None:
        Adw.Application.do_startup(self)
        Adw.StyleManager.get_default().set_color_scheme(Adw.ColorScheme.FORCE_DARK)
        provider = Gtk.CssProvider()
        provider.load_from_path(str(files("local_tracker").joinpath("style.css")))
        Gtk.StyleContext.add_provider_for_display(
            Gdk.Display.get_default(),
            provider,
            Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
        )
        try:
            self.service = TrackerService()
        except StorageError as error:
            self.service = TrackerService.__new__(TrackerService)
            self.service.data = None
            self.service._listeners = []
            self.service.store = None
            GLib.idle_add(self._fatal_storage_error, str(error))
            return
        self.indicator = StatusNotifier(self, APP_ID)
        self.indicator.start()
        self.hold()
        self._tray_held = True
        self.service.subscribe(self._sync_background_state)
        self._sync_background_state()

    def do_shutdown(self) -> None:
        if self.indicator:
            self.indicator.stop()
        Adw.Application.do_shutdown(self)

    def do_activate(self) -> None:
        if self.service is None or self.service.data is None:
            return
        if self.window is None:
            from .window import MainWindow

            self.window = MainWindow(self, self.service)
            self.window.connect("destroy", self._window_destroyed)
        self.window.present()

    def _window_destroyed(self, _window: Gtk.Window) -> None:
        self.window = None

    def _fatal_storage_error(self, message: str) -> bool:
        dialog = Adw.MessageDialog(
            transient_for=None,
            heading="Local data could not be opened",
            body=message,
        )
        dialog.add_response("quit", "Quit")
        dialog.connect("response", lambda *_: self.quit())
        dialog.present()
        return GLib.SOURCE_REMOVE

    def _sync_background_state(self) -> None:
        active = self.service.active_entry if self.service else None
        if self.indicator:
            self.indicator.update(active)
        if active:
            if not self._timer_held:
                self.hold()
                self._timer_held = True
            notification = Gio.Notification.new(active.task_name)
            notification.set_body(f"Tracking · {active.project_name}")
            notification.set_priority(Gio.NotificationPriority.NORMAL)
            notification.set_default_action("app.show")
            notification.add_button("Stop", "app.stop-timer")
            self.send_notification(TIMER_NOTIFICATION_ID, notification)
        else:
            self.withdraw_notification(TIMER_NOTIFICATION_ID)
            if self._timer_held:
                self.release()
                self._timer_held = False

    def on_show(self, *_args) -> None:
        self.activate()

    def on_show_tracker(self, *_args) -> None:
        self.activate()
        self.window.stack.set_visible_child_name("tracker")

    def on_show_reports(self, *_args) -> None:
        self.activate()
        self.window.stack.set_visible_child_name("reports")

    def on_stop_timer(self, *_args) -> None:
        if self.service:
            self.service.stop()

    def last_startable_task(self):
        if not self.service:
            return None
        for entry in sorted(
            self.service.data.entries,
            key=lambda candidate: candidate.start_at,
            reverse=True,
        ):
            try:
                task = self.service.task(entry.task_id)
                project = self.service.project(task.project_id)
            except ValueError:
                continue
            if not task.archived and not project.archived:
                return task
        tasks = self.service.active_tasks()
        return tasks[0] if tasks else None

    def start_last_timer(self) -> bool:
        if not self.service or self.service.active_entry:
            return GLib.SOURCE_REMOVE
        task = self.last_startable_task()
        if task:
            self.service.start(task.id)
        else:
            self.activate()
        return GLib.SOURCE_REMOVE

    def stop_timer_from_indicator(self) -> bool:
        if self.service:
            self.service.stop()
        return GLib.SOURCE_REMOVE

    def quit_from_indicator(self) -> bool:
        self.on_quit()
        return GLib.SOURCE_REMOVE

    def on_quit(self, *_args) -> None:
        if self.service and self.service.active_entry:
            self.service.stop()
        self.quit()

    def on_about(self, *_args) -> None:
        about = Adw.AboutWindow(
            transient_for=self.window,
            application_name="Local Tracker",
            application_icon=APP_ID,
            developer_name="Local Tracker contributors",
            version="0.1.0",
            comments="Private, offline time tracking for GNOME.",
            license_type=Gtk.License.GPL_3_0,
        )
        about.present()

    def create_action(
        self,
        name: str,
        callback,
        shortcuts: list[str] | None = None,
    ) -> None:
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.set_accels_for_action(f"app.{name}", shortcuts)
