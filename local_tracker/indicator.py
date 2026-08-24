from __future__ import annotations

from gi.repository import Gio, GLib

OBJECT_PATH = "/StatusNotifierItem"
MENU_PATH = "/MenuBar"
WATCHER_NAME = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_INTERFACE = "org.kde.StatusNotifierWatcher"

INTROSPECTION_XML = """
<node>
  <interface name="org.kde.StatusNotifierItem">
    <property name="Category" type="s" access="read"/>
    <property name="Id" type="s" access="read"/>
    <property name="Title" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="WindowId" type="u" access="read"/>
    <property name="IconName" type="s" access="read"/>
    <property name="IconPixmap" type="a(iiay)" access="read"/>
    <property name="OverlayIconName" type="s" access="read"/>
    <property name="AttentionIconName" type="s" access="read"/>
    <property name="ItemIsMenu" type="b" access="read"/>
    <property name="Menu" type="o" access="read"/>
    <method name="Activate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="SecondaryActivate">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="ContextMenu">
      <arg name="x" type="i" direction="in"/>
      <arg name="y" type="i" direction="in"/>
    </method>
    <method name="Scroll">
      <arg name="delta" type="i" direction="in"/>
      <arg name="orientation" type="s" direction="in"/>
    </method>
    <signal name="NewStatus">
      <arg name="status" type="s"/>
    </signal>
    <signal name="NewIcon"/>
    <signal name="NewToolTip"/>
  </interface>
  <interface name="com.canonical.dbusmenu">
    <property name="Version" type="u" access="read"/>
    <property name="TextDirection" type="s" access="read"/>
    <property name="Status" type="s" access="read"/>
    <property name="IconThemePath" type="as" access="read"/>
    <method name="GetLayout">
      <arg name="parentId" type="i" direction="in"/>
      <arg name="recursionDepth" type="i" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="revision" type="u" direction="out"/>
      <arg name="layout" type="(ia{sv}av)" direction="out"/>
    </method>
    <method name="GetGroupProperties">
      <arg name="ids" type="ai" direction="in"/>
      <arg name="propertyNames" type="as" direction="in"/>
      <arg name="properties" type="a(ia{sv})" direction="out"/>
    </method>
    <method name="Event">
      <arg name="id" type="i" direction="in"/>
      <arg name="eventId" type="s" direction="in"/>
      <arg name="data" type="v" direction="in"/>
      <arg name="timestamp" type="u" direction="in"/>
    </method>
    <method name="AboutToShow">
      <arg name="id" type="i" direction="in"/>
      <arg name="needUpdate" type="b" direction="out"/>
    </method>
    <signal name="LayoutUpdated">
      <arg name="revision" type="u"/>
      <arg name="parent" type="i"/>
    </signal>
  </interface>
</node>
"""


class StatusNotifier:
    """Minimal, event-driven StatusNotifierItem for GNOME AppIndicator."""

    def __init__(self, application, app_id: str) -> None:
        self.application = application
        self.app_id = app_id
        self.connection: Gio.DBusConnection | None = None
        self.registration_ids: list[int] = []
        self._active_entry = None
        self._revision = 1
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)

    def start(self) -> None:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            self.registration_ids.append(
                self.connection.register_object(
                    OBJECT_PATH,
                    self._node_info.interfaces[0],
                    self._method_called,
                    self._get_property,
                    None,
                )
            )
            self.registration_ids.append(
                self.connection.register_object(
                    MENU_PATH,
                    self._node_info.interfaces[1],
                    self._method_called,
                    self._get_property,
                    None,
                )
            )
            self.connection.call(
                WATCHER_NAME,
                WATCHER_PATH,
                WATCHER_INTERFACE,
                "RegisterStatusNotifierItem",
                GLib.Variant("(s)", (OBJECT_PATH,)),
                None,
                Gio.DBusCallFlags.NONE,
                -1,
                None,
                self._registered,
            )
        except GLib.Error:
            self.stop()

    def stop(self) -> None:
        if self.connection:
            for registration_id in self.registration_ids:
                self.connection.unregister_object(registration_id)
        self.registration_ids.clear()
        self.connection = None

    def update(self, active_entry) -> None:
        self._active_entry = active_entry
        self._revision += 1
        if not self.connection:
            return
        try:
            self.connection.emit_signal(
                None,
                OBJECT_PATH,
                "org.kde.StatusNotifierItem",
                "NewIcon",
                None,
            )
            self.connection.emit_signal(
                None,
                OBJECT_PATH,
                "org.kde.StatusNotifierItem",
                "NewToolTip",
                None,
            )
            self.connection.emit_signal(
                None,
                MENU_PATH,
                "com.canonical.dbusmenu",
                "LayoutUpdated",
                GLib.Variant("(ui)", (self._revision, 0)),
            )
        except GLib.Error:
            pass

    def _registered(self, connection: Gio.DBusConnection, result) -> None:
        try:
            connection.call_finish(result)
        except GLib.Error:
            # GNOME without an indicator extension simply ignores the item.
            pass

    def _method_called(
        self,
        _connection,
        _sender,
        _object_path,
        interface_name,
        method_name,
        parameters,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if interface_name == "com.canonical.dbusmenu":
            self._menu_method(method_name, parameters, invocation)
            return
        if method_name in {"Activate", "SecondaryActivate"}:
            self.application.activate()
        invocation.return_value(None)

    def _menu_method(
        self,
        method_name: str,
        parameters: GLib.Variant,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "GetLayout":
            invocation.return_value(self._layout())
        elif method_name == "GetGroupProperties":
            ids, _property_names = parameters.unpack()
            properties = [
                (item_id, self._item_properties(item_id))
                for item_id in ids
                if item_id in {0, 1, 2, 3, 4, 5, 6}
            ]
            invocation.return_value(GLib.Variant("(a(ia{sv}))", (properties,)))
        elif method_name == "AboutToShow":
            invocation.return_value(GLib.Variant("(b)", (False,)))
        elif method_name == "Event":
            item_id, event_id, _data, _timestamp = parameters.unpack()
            if event_id == "clicked":
                self._activate_menu_item(item_id)
            invocation.return_value(None)
        else:
            invocation.return_dbus_error(
                "com.canonical.dbusmenu.Error.UnknownMethod",
                f"Unknown menu method: {method_name}",
            )

    def _get_property(
        self,
        _connection,
        _sender,
        _object_path,
        interface_name,
        property_name: str,
    ) -> GLib.Variant:
        if interface_name == "com.canonical.dbusmenu":
            menu_values = {
                "Version": GLib.Variant("u", 3),
                "TextDirection": GLib.Variant("s", "ltr"),
                "Status": GLib.Variant("s", "normal"),
                "IconThemePath": GLib.Variant("as", []),
            }
            return menu_values[property_name]
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self._title()),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", self._icon_name()),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", self.app_id),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", MENU_PATH),
        }
        return values[property_name]

    def _layout(self) -> GLib.Variant:
        children = [self._menu_item(item_id) for item_id in (1, 2, 3, 4, 5, 6)]
        return GLib.Variant(
            "(u(ia{sv}av))",
            (self._revision, (0, {}, children)),
        )

    def _menu_item(self, item_id: int) -> GLib.Variant:
        return GLib.Variant(
            "(ia{sv}av)",
            (item_id, self._item_properties(item_id), []),
        )

    def _item_properties(self, item_id: int) -> dict[str, GLib.Variant]:
        active = self._active_entry is not None
        if item_id in {2, 5}:
            return {"type": GLib.Variant("s", "separator")}
        labels = {
            1: "Show Local Tracker",
            3: self._start_label(),
            4: "Stop timer",
            6: "Quit",
        }
        properties = {
            "label": GLib.Variant("s", labels.get(item_id, "")),
            "enabled": GLib.Variant(
                "b",
                (item_id != 3 or not active) and (item_id != 4 or active),
            ),
            "visible": GLib.Variant("b", True),
        }
        if item_id == 1:
            properties["icon-name"] = GLib.Variant("s", self.app_id)
        return properties

    def _activate_menu_item(self, item_id: int) -> None:
        callbacks = {
            1: self.application.activate,
            3: self.application.start_last_timer,
            4: self.application.stop_timer_from_indicator,
            6: self.application.quit_from_indicator,
        }
        callback = callbacks.get(item_id)
        if callback:
            callback()

    def _start_label(self) -> str:
        task = self.application.last_startable_task()
        return f"Start {task.name}" if task else "Start last task"

    def _title(self) -> str:
        if self._active_entry:
            return f"{self._active_entry.task_name} · Local Tracker"
        return "Local Tracker"

    def _icon_name(self) -> str:
        return self.app_id if self._active_entry else f"{self.app_id}-inactive"
