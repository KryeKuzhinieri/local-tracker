from __future__ import annotations

from datetime import date, datetime

from gi.repository import Adw, Gio, GLib, Gtk

from .dialogs import EntryEditor, ManagerWindow, error_dialog
from .models import Project, Task, TimeEntry, from_iso
from .service import TrackerError, TrackerService


def format_duration(seconds: int, *, compact: bool = False) -> str:
    hours, remainder = divmod(max(0, seconds), 3600)
    minutes, secs = divmod(remainder, 60)
    if compact and not hours:
        return f"{minutes:02d}:{secs:02d}"
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def local_datetime(value: str) -> datetime:
    return from_iso(value).astimezone()


class MainWindow(Adw.ApplicationWindow):
    def __init__(self, application, service: TrackerService) -> None:
        super().__init__(
            application=application,
            title="Local Tracker",
            default_width=960,
            default_height=720,
        )
        self.service = service
        self.projects: list[Project] = []
        self.tasks: list[Task] = []
        self._destroyed = False

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.add_css_class("app-header")
        header.set_title_widget(self._build_switcher())

        manage = Gtk.Button(icon_name="folder-new-symbolic")
        manage.set_tooltip_text("Manage projects and tasks")
        manage.connect("clicked", self._open_manager)
        header.pack_start(manage)

        menu = Gio.Menu()
        menu.append("About Local Tracker", "app.about")
        menu.append("Quit", "app.quit")
        menu_button = Gtk.MenuButton(
            icon_name="open-menu-symbolic",
            menu_model=menu,
            tooltip_text="Main menu",
        )
        header.pack_end(menu_button)
        toolbar.add_top_bar(header)

        self.stack = Adw.ViewStack()
        self.tracker_page = self._build_tracker_page()
        self.report_page = self._build_report_page()
        self.stack.add_titled_with_icon(
            self.tracker_page,
            "tracker",
            "Tracker",
            "media-playback-start-symbolic",
        )
        self.stack.add_titled_with_icon(
            self.report_page,
            "reports",
            "Reports",
            "view-list-symbolic",
        )
        self.stack.connect(
            "notify::visible-child-name",
            lambda *_: (
                self._refresh_report()
                if self.stack.get_visible_child_name() == "reports"
                else None
            ),
        )
        self.switcher.set_stack(self.stack)
        toolbar.set_content(self.stack)

        self.set_content(toolbar)
        self.service.subscribe(self.refresh)
        self.connect("close-request", self._hide_to_tray)
        self.connect("notify::visible", self._visibility_changed)
        self.connect("destroy", self._on_destroy)
        self._timer_source = 0
        self._timer_interval = 0
        self._schedule_tick()
        self.refresh()

    def _build_switcher(self) -> Gtk.Widget:
        self.switcher = Adw.ViewSwitcher()
        self.switcher.set_policy(Adw.ViewSwitcherPolicy.WIDE)
        return self.switcher

    def _build_tracker_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.add_css_class("page")
        page.set_size_request(560, -1)

        hero = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        hero.add_css_class("hero-card")
        status = Gtk.Box(spacing=12)
        status_text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.status_label = Gtk.Label(label="READY TO TRACK", xalign=0)
        self.status_label.add_css_class("eyebrow")
        self.active_title = Gtk.Label(label="Choose a task", xalign=0, ellipsize=3)
        self.active_title.add_css_class("title-2")
        self.active_project = Gtk.Label(
            label="Everything stays on this device", xalign=0
        )
        self.active_project.add_css_class("muted")
        status_text.append(self.status_label)
        status_text.append(self.active_title)
        status_text.append(self.active_project)
        status.append(status_text)
        timer_group = Gtk.Box(
            spacing=10,
            halign=Gtk.Align.END,
            valign=Gtk.Align.CENTER,
            hexpand=True,
        )
        self.timer_label = Gtk.Label(label="00:00:00", xalign=1)
        self.timer_label.add_css_class("timer")
        self.daily_total_label = Gtk.Label(label="(00:00:00)")
        self.daily_total_label.add_css_class("daily-total")
        timer_group.append(self.timer_label)
        timer_group.append(self.daily_total_label)
        status.append(timer_group)
        hero.append(status)

        form = Gtk.Grid(column_spacing=12, row_spacing=12)
        form.set_column_homogeneous(True)
        self.project_dropdown = Gtk.DropDown()
        self.project_dropdown.connect("notify::selected", self._project_changed)
        self.task_dropdown = Gtk.DropDown()
        self.task_dropdown.connect("notify::selected", self._selection_changed)
        form.attach(self._field("PROJECT", self.project_dropdown), 0, 0, 1, 1)
        form.attach(self._field("TASK", self.task_dropdown), 1, 0, 1, 1)
        hero.append(form)

        self.note_entry = Gtk.Entry(placeholder_text="Optional note about this session")
        self.note_entry.connect("changed", self._selection_changed)
        hero.append(self._field("NOTE", self.note_entry))

        self.track_button = Gtk.Button(label="Start tracking")
        self.track_button.add_css_class("start-button")
        self.track_button.connect("clicked", self._track_clicked)
        hero.append(self.track_button)
        page.append(hero)

        heading = Gtk.Box(spacing=8)
        recent_title = Gtk.Label(label="Recent entries", xalign=0, hexpand=True)
        recent_title.add_css_class("title-3")
        heading.append(recent_title)
        page.append(heading)

        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        card.add_css_class("surface-card")
        self.recent_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.recent_list.add_css_class("separators")
        card.append(self.recent_list)
        self.empty_recent = Gtk.Label(
            label="No tracked time yet.\nCreate a project and task to get started.",
            justify=Gtk.Justification.CENTER,
        )
        self.empty_recent.add_css_class("muted")
        self.empty_recent.set_margin_top(32)
        self.empty_recent.set_margin_bottom(32)
        card.append(self.empty_recent)
        page.append(card)
        scroll.set_child(page)
        return scroll

    def _build_report_page(self) -> Gtk.Widget:
        scroll = Gtk.ScrolledWindow(hscrollbar_policy=Gtk.PolicyType.NEVER)
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=20)
        page.add_css_class("page")

        top = Gtk.Box(spacing=12)
        heading_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        heading = Gtk.Label(label="Time report", xalign=0)
        heading.add_css_class("title-1")
        subheading = Gtk.Label(
            label="A clear summary of where your time went.", xalign=0
        )
        subheading.add_css_class("muted")
        heading_box.append(heading)
        heading_box.append(subheading)
        top.append(heading_box)

        today = date.today()
        self.report_start = Gtk.Entry(
            text=today.replace(day=1).isoformat(),
            width_chars=11,
            tooltip_text="Start date (YYYY-MM-DD)",
        )
        self.report_end = Gtk.Entry(
            text=today.isoformat(),
            width_chars=11,
            tooltip_text="End date (YYYY-MM-DD)",
        )
        apply = Gtk.Button(label="Apply")
        apply.add_css_class("suggested-action")
        apply.connect("clicked", self._refresh_report)
        filters = Gtk.Box(spacing=8, halign=Gtk.Align.END, hexpand=True)
        filters.append(self.report_start)
        filters.append(Gtk.Label(label="to"))
        filters.append(self.report_end)
        filters.append(apply)
        top.append(filters)
        page.append(top)

        summary = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        summary.add_css_class("hero-card")
        total_title = Gtk.Label(label="TOTAL TRACKED", xalign=0)
        total_title.add_css_class("eyebrow")
        self.report_total = Gtk.Label(label="00:00:00", xalign=0)
        self.report_total.add_css_class("total")
        summary.append(total_title)
        summary.append(self.report_total)
        self.project_totals = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=4)
        summary.append(self.project_totals)
        page.append(summary)

        report_heading = Gtk.Label(label="Entries", xalign=0)
        report_heading.add_css_class("title-3")
        page.append(report_heading)
        report_card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        report_card.add_css_class("surface-card")
        self.report_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.report_list.add_css_class("separators")
        report_card.append(self.report_list)
        page.append(report_card)
        scroll.set_child(page)
        return scroll

    @staticmethod
    def _field(title: str, widget: Gtk.Widget) -> Gtk.Widget:
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        label = Gtk.Label(label=title, xalign=0)
        label.add_css_class("eyebrow")
        box.append(label)
        box.append(widget)
        return box

    def refresh(self) -> None:
        if self._destroyed:
            return
        selected_project = self._selected_project_id()
        selected_task = self._selected_task_id()
        active = self.service.active_entry
        if active:
            selected_project = selected_project or active.project_id
            selected_task = selected_task or active.task_id

        self.projects = self.service.active_projects()
        self.project_dropdown.set_model(
            Gtk.StringList.new([project.name for project in self.projects])
        )
        project_index = next(
            (
                index
                for index, project in enumerate(self.projects)
                if project.id == selected_project
            ),
            0,
        )
        if self.projects:
            self.project_dropdown.set_selected(project_index)
        self._load_tasks(selected_task)
        self._refresh_active()
        self._refresh_recent()
        self._refresh_report()

    def _load_tasks(self, selected_id: str | None = None) -> None:
        project_id = self._selected_project_id()
        self.tasks = self.service.active_tasks(project_id) if project_id else []
        self.task_dropdown.set_model(
            Gtk.StringList.new([task.name for task in self.tasks])
        )
        selected = next(
            (index for index, task in enumerate(self.tasks) if task.id == selected_id),
            0,
        )
        if self.tasks:
            self.task_dropdown.set_selected(selected)
        self.track_button.set_sensitive(bool(self.tasks))

    def _project_changed(self, *_args) -> None:
        self._load_tasks()
        self._selection_changed()

    def _selection_changed(self, *_args) -> None:
        active = self.service.active_entry
        selected_task = self._selected_task_id()
        if active and selected_task and selected_task != active.task_id:
            self.track_button.set_label("Switch task")
            self.track_button.remove_css_class("stop-button")
            self.track_button.add_css_class("start-button")
        elif active:
            self.track_button.set_label("Stop timer")
            self.track_button.remove_css_class("start-button")
            self.track_button.add_css_class("stop-button")
        else:
            self.track_button.set_label("Start tracking")
            self.track_button.remove_css_class("stop-button")
            self.track_button.add_css_class("start-button")

    def _track_clicked(self, *_args) -> None:
        task_id = self._selected_task_id()
        if not task_id:
            self._open_manager()
            return
        active = self.service.active_entry
        if active and active.task_id == task_id:
            try:
                self.service.stop()
            except TrackerError as error:
                error_dialog(self, str(error))
            return
        if active:
            dialog = Adw.MessageDialog(
                transient_for=self,
                heading="Switch the active timer?",
                body=(
                    f"“{active.task_name}” will stop and the selected task will start."
                ),
            )
            dialog.add_response("cancel", "Cancel")
            dialog.add_response("switch", "Switch")
            dialog.set_response_appearance("switch", Adw.ResponseAppearance.SUGGESTED)
            dialog.connect("response", self._switch_response, task_id)
            dialog.present()
            return
        self._start(task_id)

    def _switch_response(
        self, _dialog: Adw.MessageDialog, response: str, task_id: str
    ) -> None:
        if response != "switch":
            return
        try:
            self.service.stop()
            self.service.start(task_id, self.note_entry.get_text())
        except TrackerError as error:
            error_dialog(self, str(error))

    def _start(self, task_id: str) -> None:
        try:
            self.service.start(task_id, self.note_entry.get_text())
        except TrackerError as error:
            error_dialog(self, str(error))

    def _refresh_active(self) -> None:
        active = self.service.active_entry
        if active:
            self.status_label.set_label("TRACKING NOW")
            self.active_title.set_label(active.task_name)
            self.active_project.set_label(active.project_name)
            self.timer_label.set_label(format_duration(active.duration_seconds()))
        else:
            self.status_label.set_label("READY TO TRACK")
            self.active_title.set_label("Choose a task")
            self.active_project.set_label("Everything stays on this device")
            self.timer_label.set_label("00:00:00")
        self._refresh_daily_total()
        self._selection_changed()

    def _refresh_recent(self) -> None:
        self._clear(self.recent_list)
        entries = sorted(
            self.service.data.entries, key=lambda entry: entry.start_at, reverse=True
        )[:12]
        self.empty_recent.set_visible(not entries)
        for entry in entries:
            self.recent_list.append(self._entry_row(entry))

    def _entry_row(self, entry: TimeEntry) -> Gtk.Widget:
        row = Gtk.Box(spacing=12)
        row.add_css_class("entry-row")
        text = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3, hexpand=True)
        title = Gtk.Label(label=entry.task_name, xalign=0, ellipsize=3)
        title.add_css_class("heading")
        start = local_datetime(entry.start_at)
        subtitle_text = f"{entry.project_name} · {start.strftime('%a, %d %b · %H:%M')}"
        if entry.note:
            subtitle_text += f" · {entry.note}"
        subtitle = Gtk.Label(label=subtitle_text, xalign=0, ellipsize=3)
        subtitle.add_css_class("muted")
        text.append(title)
        text.append(subtitle)
        row.append(text)
        duration = Gtk.Label(
            label=(
                "Running"
                if entry.running
                else format_duration(entry.duration_seconds())
            )
        )
        duration.add_css_class("monospace")
        row.append(duration)
        edit = Gtk.Button(icon_name="document-edit-symbolic")
        edit.add_css_class("flat")
        edit.set_tooltip_text("Edit entry")
        edit.connect(
            "clicked", lambda _button: EntryEditor(self, self.service, entry).present()
        )
        row.append(edit)
        delete = Gtk.Button(icon_name="user-trash-symbolic")
        delete.add_css_class("flat")
        delete.add_css_class("danger")
        delete.set_tooltip_text("Delete entry")
        delete.connect("clicked", lambda _button: self._confirm_delete(entry))
        row.append(delete)
        return row

    def _confirm_delete(self, entry: TimeEntry) -> None:
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Delete “{entry.task_name}”?",
            body="This time entry cannot be recovered after the next save.",
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("delete", "Delete")
        dialog.set_response_appearance("delete", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect(
            "response",
            lambda _dialog, response: (
                self.service.delete_entry(entry.id) if response == "delete" else None
            ),
        )
        dialog.present()

    def _refresh_report(self, *_args) -> None:
        try:
            start = date.fromisoformat(self.report_start.get_text().strip())
            end = date.fromisoformat(self.report_end.get_text().strip())
            if end < start:
                raise ValueError("End date must not be before start date")
        except ValueError as error:
            if _args:
                error_dialog(self, f"Use dates in YYYY-MM-DD format. {error}")
            return

        total, totals = self.service.report_totals(start, end)
        self.report_total.set_label(format_duration(total))
        self._clear_box(self.project_totals)
        for (name, _color), seconds in sorted(
            totals.items(), key=lambda item: item[1], reverse=True
        ):
            line = Gtk.Box(spacing=8)
            line.set_margin_top(3)
            project = Gtk.Label(label=name, xalign=0, hexpand=True)
            project.add_css_class("muted")
            duration = Gtk.Label(label=format_duration(seconds))
            line.append(project)
            line.append(duration)
            self.project_totals.append(line)

        self._clear(self.report_list)
        for entry in self.service.entries_between(start, end):
            self.report_list.append(self._entry_row(entry))

    def _open_manager(self, *_args) -> None:
        ManagerWindow(self, self.service).present()

    def _selected_project_id(self) -> str | None:
        selected = self.project_dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self.projects):
            return None
        return self.projects[selected].id

    def _selected_task_id(self) -> str | None:
        selected = self.task_dropdown.get_selected()
        if selected == Gtk.INVALID_LIST_POSITION or selected >= len(self.tasks):
            return None
        return self.tasks[selected].id

    def _tick(self) -> bool:
        if self._destroyed:
            return GLib.SOURCE_REMOVE
        active = self.service.active_entry
        if self.get_visible():
            if active:
                self.timer_label.set_label(format_duration(active.duration_seconds()))
            self._refresh_daily_total()
        return GLib.SOURCE_CONTINUE

    def _refresh_daily_total(self) -> None:
        seconds = self.service.total_for_day(date.today())
        self.daily_total_label.set_label(f"({format_duration(seconds)})")

    def _visibility_changed(self, *_args) -> None:
        self._schedule_tick()

    def _schedule_tick(self) -> None:
        interval = 1 if self.get_visible() else 30
        if self._timer_source and self._timer_interval == interval:
            return
        if self._timer_source:
            GLib.source_remove(self._timer_source)
        self._timer_interval = interval
        self._timer_source = GLib.timeout_add_seconds(interval, self._tick)

    def _on_destroy(self, *_args) -> None:
        self._destroyed = True
        self.service.unsubscribe(self.refresh)
        if self._timer_source:
            GLib.source_remove(self._timer_source)
            self._timer_source = 0

    def _hide_to_tray(self, *_args) -> bool:
        self.set_visible(False)
        return True

    @staticmethod
    def _clear(listbox: Gtk.ListBox) -> None:
        while child := listbox.get_first_child():
            listbox.remove(child)

    @staticmethod
    def _clear_box(box: Gtk.Box) -> None:
        while child := box.get_first_child():
            box.remove(child)
