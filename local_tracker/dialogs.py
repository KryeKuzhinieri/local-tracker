from __future__ import annotations

from datetime import datetime

from gi.repository import Adw, Gtk

from .models import Project, Task, TimeEntry, from_iso
from .service import TrackerError, TrackerService

COLORS = [
    ("Violet", "#7c6ff0"),
    ("Blue", "#3d8bfd"),
    ("Cyan", "#22b8cf"),
    ("Green", "#40c057"),
    ("Amber", "#fab005"),
    ("Orange", "#fd7e14"),
    ("Pink", "#e64980"),
    ("Red", "#ef476f"),
]


def format_local_input(value: datetime) -> str:
    return value.astimezone().strftime("%Y-%m-%d %H:%M")


def parse_local_input(value: str) -> datetime:
    return datetime.strptime(value.strip(), "%Y-%m-%d %H:%M").astimezone()


def error_dialog(parent: Gtk.Window, message: str) -> None:
    dialog = Adw.MessageDialog(
        transient_for=parent,
        heading="Could not save",
        body=message,
    )
    dialog.add_response("ok", "OK")
    dialog.present()


def form_row(label: str, widget: Gtk.Widget) -> Gtk.Box:
    box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
    title = Gtk.Label(label=label, xalign=0)
    title.add_css_class("caption")
    title.add_css_class("muted")
    box.append(title)
    box.append(widget)
    return box


class EntryEditor(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        service: TrackerService,
        entry: TimeEntry,
    ) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Edit time entry",
            default_width=480,
            default_height=540,
        )
        self.service = service
        self.entry = entry
        self.tasks = sorted(
            service.data.tasks,
            key=lambda task: (
                service.project(task.project_id).name.casefold(),
                task.name.casefold(),
            ),
        )

        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_start(cancel)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_bottom(24)
        content.set_margin_start(24)
        content.set_margin_end(24)

        names = [
            f"{service.project(task.project_id).name} · {task.name}"
            + (" (archived)" if task.archived else "")
            for task in self.tasks
        ]
        self.task_dropdown = Gtk.DropDown.new_from_strings(names)
        selected = next(
            (
                index
                for index, task in enumerate(self.tasks)
                if task.id == entry.task_id
            ),
            0,
        )
        self.task_dropdown.set_selected(selected)
        content.append(form_row("TASK AND PROJECT", self.task_dropdown))

        self.note_entry = Gtk.Entry(text=entry.note, placeholder_text="Optional note")
        content.append(form_row("NOTE", self.note_entry))

        self.start_entry = Gtk.Entry(
            text=format_local_input(from_iso(entry.start_at)),
            placeholder_text="YYYY-MM-DD HH:MM",
        )
        content.append(form_row("START", self.start_entry))

        self.end_entry = Gtk.Entry(
            text=format_local_input(from_iso(entry.end_at)) if entry.end_at else "",
            placeholder_text="Leave empty to keep running",
        )
        content.append(form_row("END", self.end_entry))

        hint = Gtk.Label(
            label="Times use your local timezone · Format: YYYY-MM-DD HH:MM",
            xalign=0,
            wrap=True,
        )
        hint.add_css_class("muted")
        content.append(hint)
        toolbar.set_content(content)
        self.set_content(toolbar)

    def _save(self, *_args) -> None:
        try:
            if not self.tasks:
                raise TrackerError("Create a task before editing entries")
            task = self.tasks[self.task_dropdown.get_selected()]
            start = parse_local_input(self.start_entry.get_text())
            end_text = self.end_entry.get_text().strip()
            end = parse_local_input(end_text) if end_text else None
            self.service.update_entry(
                self.entry.id,
                task.id,
                self.note_entry.get_text(),
                start,
                end,
            )
        except (TrackerError, ValueError) as error:
            error_dialog(self, str(error))
            return
        self.close()


class ItemEditor(Adw.Window):
    def __init__(
        self,
        parent: Gtk.Window,
        service: TrackerService,
        item: Project | Task,
        on_saved,
    ) -> None:
        title = "Edit project" if isinstance(item, Project) else "Edit task"
        super().__init__(
            transient_for=parent,
            modal=True,
            title=title,
            default_width=420,
            default_height=340,
        )
        self.service = service
        self.item = item
        self.on_saved = on_saved
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        header.set_show_end_title_buttons(False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._save)
        header.pack_start(cancel)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        content = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=18)
        content.set_margin_top(24)
        content.set_margin_start(24)
        content.set_margin_end(24)
        self.name = Gtk.Entry(text=item.name)
        content.append(form_row("NAME", self.name))

        if isinstance(item, Project):
            self.colors = [value for _, value in COLORS]
            self.secondary = Gtk.DropDown.new_from_strings(
                [label for label, _ in COLORS]
            )
            try:
                self.secondary.set_selected(self.colors.index(item.color))
            except ValueError:
                self.secondary.set_selected(0)
            content.append(form_row("COLOR", self.secondary))
        else:
            self.projects = service.active_projects()
            self.secondary = Gtk.DropDown.new_from_strings(
                [project.name for project in self.projects]
            )
            selected = next(
                (
                    index
                    for index, project in enumerate(self.projects)
                    if project.id == item.project_id
                ),
                0,
            )
            self.secondary.set_selected(selected)
            content.append(form_row("PROJECT", self.secondary))

        toolbar.set_content(content)
        self.set_content(toolbar)

    def _save(self, *_args) -> None:
        try:
            if isinstance(self.item, Project):
                color = self.colors[self.secondary.get_selected()]
                self.service.update_project(self.item.id, self.name.get_text(), color)
            else:
                if not self.projects:
                    raise TrackerError("Create a project first")
                project = self.projects[self.secondary.get_selected()]
                self.service.update_task(self.item.id, self.name.get_text(), project.id)
        except (TrackerError, IndexError) as error:
            error_dialog(self, str(error))
            return
        self.on_saved()
        self.close()


class ManagerWindow(Adw.Window):
    def __init__(self, parent: Gtk.Window, service: TrackerService) -> None:
        super().__init__(
            transient_for=parent,
            modal=True,
            title="Projects and tasks",
            default_width=620,
            default_height=650,
        )
        self.service = service
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar()
        toolbar.add_top_bar(header)

        self.stack = Adw.ViewStack()
        self.stack.add_titled_with_icon(
            self._project_page(),
            "projects",
            "Projects",
            "folder-symbolic",
        )
        self.stack.add_titled_with_icon(
            self._task_page(),
            "tasks",
            "Tasks",
            "view-list-symbolic",
        )
        switcher = Adw.ViewSwitcher()
        switcher.set_stack(self.stack)
        header.set_title_widget(switcher)
        toolbar.set_content(self.stack)
        self.set_content(toolbar)
        self.refresh()

    def _project_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("page")
        form = Gtk.Box(spacing=10)
        self.project_name = Gtk.Entry(placeholder_text="New project name", hexpand=True)
        self.project_color = Gtk.DropDown.new_from_strings(
            [label for label, _ in COLORS]
        )
        add = Gtk.Button(label="Add project")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._add_project)
        form.append(self.project_name)
        form.append(self.project_color)
        form.append(add)
        page.append(form)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self.project_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.project_list.add_css_class("boxed-list")
        scroll.set_child(self.project_list)
        page.append(scroll)
        return page

    def _task_page(self) -> Gtk.Widget:
        page = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        page.add_css_class("page")
        form = Gtk.Box(spacing=10)
        self.task_name = Gtk.Entry(placeholder_text="New task name", hexpand=True)
        self.task_project = Gtk.DropDown()
        add = Gtk.Button(label="Add task")
        add.add_css_class("suggested-action")
        add.connect("clicked", self._add_task)
        form.append(self.task_name)
        form.append(self.task_project)
        form.append(add)
        page.append(form)
        scroll = Gtk.ScrolledWindow(vexpand=True)
        self.task_list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.NONE)
        self.task_list.add_css_class("boxed-list")
        scroll.set_child(self.task_list)
        page.append(scroll)
        return page

    def refresh(self) -> None:
        self._clear(self.project_list)
        self._clear(self.task_list)
        projects = sorted(
            self.service.data.projects,
            key=lambda project: (project.archived, project.name.casefold()),
        )
        for project in projects:
            self.project_list.append(
                self._item_row(
                    project.name,
                    "Archived" if project.archived else project.color,
                    lambda _button, item=project: self._edit(item),
                    lambda _button, item=project: self._remove(item),
                )
            )

        active_projects = self.service.active_projects()
        self.task_projects = active_projects
        self.task_project.set_model(
            Gtk.StringList.new([project.name for project in active_projects])
        )
        tasks = sorted(
            self.service.data.tasks,
            key=lambda task: (
                task.archived,
                self.service.project(task.project_id).name.casefold(),
                task.name.casefold(),
            ),
        )
        for task in tasks:
            project = self.service.project(task.project_id)
            subtitle = f"{project.name}{' · Archived' if task.archived else ''}"
            self.task_list.append(
                self._item_row(
                    task.name,
                    subtitle,
                    lambda _button, item=task: self._edit(item),
                    lambda _button, item=task: self._remove(item),
                )
            )

    def _item_row(self, title: str, subtitle: str, edit_cb, remove_cb) -> Gtk.Widget:
        row = Adw.ActionRow(title=title, subtitle=subtitle)
        edit = Gtk.Button(icon_name="document-edit-symbolic", valign=Gtk.Align.CENTER)
        edit.set_tooltip_text("Edit")
        edit.connect("clicked", edit_cb)
        remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        remove.set_tooltip_text("Delete or archive")
        remove.add_css_class("flat")
        remove.add_css_class("danger")
        remove.connect("clicked", remove_cb)
        row.add_suffix(edit)
        row.add_suffix(remove)
        return row

    def _add_project(self, *_args) -> None:
        try:
            color = COLORS[self.project_color.get_selected()][1]
            self.service.add_project(self.project_name.get_text(), color)
            self.project_name.set_text("")
            self.refresh()
        except (TrackerError, IndexError) as error:
            error_dialog(self, str(error))

    def _add_task(self, *_args) -> None:
        try:
            if not self.task_projects:
                raise TrackerError("Create a project first")
            project = self.task_projects[self.task_project.get_selected()]
            self.service.add_task(self.task_name.get_text(), project.id)
            self.task_name.set_text("")
            self.refresh()
        except (TrackerError, IndexError) as error:
            error_dialog(self, str(error))

    def _edit(self, item: Project | Task) -> None:
        ItemEditor(self, self.service, item, self.refresh).present()

    def _remove(self, item: Project | Task) -> None:
        noun = "project" if isinstance(item, Project) else "task"
        dialog = Adw.MessageDialog(
            transient_for=self,
            heading=f"Remove “{item.name}”?",
            body=(
                f"This {noun} will be archived if existing time entries use it. "
                "Historical reports will remain intact."
            ),
        )
        dialog.add_response("cancel", "Cancel")
        dialog.add_response("remove", "Remove")
        dialog.set_response_appearance("remove", Adw.ResponseAppearance.DESTRUCTIVE)
        dialog.connect("response", self._remove_response, item)
        dialog.present()

    def _remove_response(
        self, _dialog: Adw.MessageDialog, response: str, item: Project | Task
    ) -> None:
        if response != "remove":
            return
        if isinstance(item, Project):
            self.service.remove_project(item.id)
        else:
            self.service.remove_task(item.id)
        self.refresh()

    @staticmethod
    def _clear(listbox: Gtk.ListBox) -> None:
        while child := listbox.get_first_child():
            listbox.remove(child)
