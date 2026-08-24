from __future__ import annotations

from gi.repository import Gio, GLib


OBJECT_PATH = "/StatusNotifierItem"
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
    <signal name="NewToolTip"/>
  </interface>
</node>
"""


class StatusNotifier:
    """Minimal, event-driven StatusNotifierItem for GNOME AppIndicator."""

    def __init__(self, application, app_id: str) -> None:
        self.application = application
        self.app_id = app_id
        self.connection: Gio.DBusConnection | None = None
        self.registration_id = 0
        self._active_entry = None
        self._node_info = Gio.DBusNodeInfo.new_for_xml(INTROSPECTION_XML)

    def start(self) -> None:
        try:
            self.connection = Gio.bus_get_sync(Gio.BusType.SESSION, None)
            interface = self._node_info.interfaces[0]
            self.registration_id = self.connection.register_object(
                OBJECT_PATH,
                interface,
                self._method_called,
                self._get_property,
                None,
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
        if self.connection and self.registration_id:
            self.connection.unregister_object(self.registration_id)
        self.registration_id = 0
        self.connection = None

    def update(self, active_entry) -> None:
        self._active_entry = active_entry
        if not self.connection:
            return
        try:
            self.connection.emit_signal(
                None,
                OBJECT_PATH,
                "org.kde.StatusNotifierItem",
                "NewToolTip",
                None,
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
        _interface_name,
        method_name,
        _parameters,
        invocation: Gio.DBusMethodInvocation,
    ) -> None:
        if method_name in {"Activate", "SecondaryActivate", "ContextMenu"}:
            GLib.idle_add(self.application.activate)
        invocation.return_value(None)

    def _get_property(
        self,
        _connection,
        _sender,
        _object_path,
        _interface_name,
        property_name: str,
    ) -> GLib.Variant:
        values = {
            "Category": GLib.Variant("s", "ApplicationStatus"),
            "Id": GLib.Variant("s", self.app_id),
            "Title": GLib.Variant("s", self._title()),
            "Status": GLib.Variant("s", "Active"),
            "WindowId": GLib.Variant("u", 0),
            "IconName": GLib.Variant("s", self.app_id),
            "IconPixmap": GLib.Variant("a(iiay)", []),
            "OverlayIconName": GLib.Variant("s", ""),
            "AttentionIconName": GLib.Variant("s", self.app_id),
            "ItemIsMenu": GLib.Variant("b", False),
            "Menu": GLib.Variant("o", "/NO_DBUSMENU"),
        }
        return values[property_name]

    def _title(self) -> str:
        if self._active_entry:
            return f"{self._active_entry.task_name} · Local Tracker"
        return "Local Tracker"
