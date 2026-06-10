#!/usr/bin/env python3
import pathlib
import re
import subprocess
import sys

import gi

gi.require_version("DbusmenuGtk3", "0.4")
gi.require_version("Gdk", "3.0")
gi.require_version("Gtk", "3.0")
gi.require_version("GtkLayerShell", "0.1")
from gi.repository import DbusmenuGtk3, Gdk, Gio, GLib, Gtk, GtkLayerShell


LOG_PATH = "/tmp/waybar-network-menu.log"
CACHE_PATH = pathlib.Path("/tmp/waybar-tray-menu-cache")
WATCHER_BUS = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_LOAD_DELAY_MS = 30
QUIT_DELAY_MS = 350
ANCHOR_SIZE = 1
WAYBAR_OFFSET = 80
TARGET_ALIASES = {
    "vpn": "clash",
}
TARGETS = {
    "network": {
        "markers": (
            "nm-applet",
            "nm_applet",
            "networkmanager",
            "network manager",
        ),
        "paths": (
            "/org/ayatana/NotificationItem/nm_applet",
            "/StatusNotifierItem",
        ),
    },
    "clash": {
        "markers": (
            "clash-verge",
            "clash verge",
        ),
        "paths": (
            "/org/ayatana/NotificationItem/tray_icon_tray_app_main",
            "/StatusNotifierItem",
        ),
    },
}
MENU_CSS = """
menu {
    background-color: rgba(26, 27, 38, 0.98);
    border: 1px solid rgba(122, 162, 247, 0.35);
    border-radius: 12px;
    padding: 6px;
}

menuitem {
    min-height: 28px;
    padding: 7px 14px;
    border-radius: 8px;
    color: #c0caf5;
}

menuitem:hover {
    background-color: rgba(122, 162, 247, 0.22);
}

menuitem label {
    color: #c0caf5;
}

separator {
    background-color: rgba(122, 162, 247, 0.24);
    min-height: 1px;
    margin: 5px 8px;
}
"""


def log(message):
    with open(LOG_PATH, "a", encoding="utf-8") as log_file:
        log_file.write(f"{message}\n")


def cache_path(target_name):
    return CACHE_PATH.with_name(f"{CACHE_PATH.name}-{target_name}")


def cached_item(target_name):
    path = cache_path(target_name)
    try:
        item = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None

    return item or None


def write_cache(target_name, item):
    try:
        cache_path(target_name).write_text(f"{item}\n", encoding="utf-8")
    except OSError as error:
        log(f"Cache write error: {error}")


def property_value(bus, destination, path, interface, name, timeout=1000):
    result = bus.call_sync(
        destination,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        GLib.Variant("(ss)", (interface, name)),
        GLib.VariantType.new("(v)"),
        Gio.DBusCallFlags.NONE,
        timeout,
        None,
    )
    return result.get_child_value(0).get_variant().unpack()


def registered_items(bus):
    log("Reading registered StatusNotifierItems")
    return property_value(
        bus,
        WATCHER_BUS,
        WATCHER_PATH,
        WATCHER_IFACE,
        "RegisteredStatusNotifierItems",
    )


def bus_names(bus):
    result = bus.call_sync(
        "org.freedesktop.DBus",
        "/org/freedesktop/DBus",
        "org.freedesktop.DBus",
        "ListNames",
        None,
        GLib.VariantType.new("(as)"),
        Gio.DBusCallFlags.NONE,
        1000,
        None,
    )
    return result.unpack()[0]


def discover_items(bus, target):
    log("Scanning StatusNotifierItem candidates")
    items = []

    try:
        names = bus_names(bus)
    except GLib.Error as error:
        log(f"ListNames error: {error.message}")
        return items

    for name in names:
        if not name.startswith(":"):
            continue

        for path in target["paths"]:
            raw_item = f"{name}{path}"
            if item_matches(bus, name, path, raw_item, target, 100):
                items.append(raw_item)
                log(f"Scanned items: {items}")
                return items

    log(f"Scanned items: {items}")
    return items


def parse_item(item):
    log(f"Parsing item: {item}")
    if "/" not in item:
        return item, "/StatusNotifierItem"

    destination, path = item.split("/", 1)
    return destination, f"/{path}"


def item_matches(bus, destination, path, raw_item, target, timeout=1000):
    candidates = [raw_item] if timeout == 1000 else []
    markers = target["markers"]

    text = " ".join(str(value).lower() for value in candidates)
    if any(marker in text for marker in markers):
        log(f"{destination}{path} matched: True")
        return True

    for name in ("Id", "Title", "IconName"):
        try:
            value = property_value(bus, destination, path, ITEM_IFACE, name, timeout)
            candidates.append(value)
            log(f"{destination}{path} {name}: {value}")
            text = " ".join(str(value).lower() for value in candidates)
            if any(marker in text for marker in markers):
                log(f"{destination}{path} matched: True")
                return True
        except GLib.Error as error:
            log(f"{destination}{path} {name} error: {error.message}")

    text = " ".join(str(value).lower() for value in candidates)
    matched = any(marker in text for marker in markers)
    log(f"{destination}{path} matched: {matched}")
    return matched


def menu_path(bus, destination, path):
    try:
        value = property_value(bus, destination, path, ITEM_IFACE, "Menu")
    except GLib.Error as error:
        log(f"{destination}{path} Menu error: {error.message}")
        return None

    log(f"{destination}{path} Menu: {value}")
    if not value or value == "/":
        return None

    return value


def cursor_position():
    try:
        output = subprocess.check_output(
            ["hyprctl", "cursorpos"],
            text=True,
            timeout=1,
        )
    except (OSError, subprocess.SubprocessError) as error:
        log(f"cursorpos fallback: {error}")
        return 0, 44

    numbers = re.findall(r"-?\d+", output)
    if len(numbers) < 2:
        log(f"cursorpos parse fallback: {output.strip()}")
        return 0, 44

    position = int(numbers[0]), int(numbers[1])
    log(f"cursorpos: {position[0]}, {position[1]}")
    return position


def monitor_at(x, y):
    display = Gdk.Display.get_default()
    if display is None:
        log("No default GDK display")
        return None, None

    for index in range(display.get_n_monitors()):
        monitor = display.get_monitor(index)
        geometry = monitor.get_geometry()
        if (
            geometry.x <= x < geometry.x + geometry.width
            and geometry.y <= y < geometry.y + geometry.height
        ):
            return monitor, geometry

    monitor = display.get_primary_monitor() or display.get_monitor(0)
    geometry = monitor.get_geometry() if monitor is not None else None
    return monitor, geometry


def anchor_margin(position, origin, size):
    if size <= ANCHOR_SIZE:
        return 0

    return min(max(position - origin, 0), size - ANCHOR_SIZE)


def apply_dark_theme():
    settings = Gtk.Settings.get_default()
    if settings is not None:
        settings.set_property("gtk-application-prefer-dark-theme", True)

    screen = Gdk.Screen.get_default()
    if screen is None:
        log("No default GDK screen")
        return

    provider = Gtk.CssProvider()
    provider.load_from_data(MENU_CSS.encode("utf-8"))
    Gtk.StyleContext.add_provider_for_screen(
        screen,
        provider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
    )


def create_anchor():
    x, y = cursor_position()
    monitor, geometry = monitor_at(x, y)
    left = anchor_margin(x, geometry.x, geometry.width) if geometry else x
    top_position = y - WAYBAR_OFFSET
    top = anchor_margin(top_position, geometry.y, geometry.height) if geometry else top_position

    window = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
    window.set_decorated(False)
    window.set_resizable(False)
    window.set_default_size(ANCHOR_SIZE, ANCHOR_SIZE)
    window.set_size_request(ANCHOR_SIZE, ANCHOR_SIZE)
    window.set_opacity(0)
    window.set_skip_taskbar_hint(True)
    window.set_skip_pager_hint(True)

    GtkLayerShell.init_for_window(window)
    GtkLayerShell.set_namespace(window, "waybar-network-menu")
    GtkLayerShell.set_layer(window, GtkLayerShell.Layer.OVERLAY)
    GtkLayerShell.set_keyboard_mode(window, GtkLayerShell.KeyboardMode.NONE)
    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.LEFT, True)
    GtkLayerShell.set_anchor(window, GtkLayerShell.Edge.TOP, True)
    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.LEFT, left)
    GtkLayerShell.set_margin(window, GtkLayerShell.Edge.TOP, top)
    if monitor is not None:
        GtkLayerShell.set_monitor(window, monitor)

    window.show_all()
    log(f"Anchor window at {left}, {top}")
    return window


def open_dbus_menu(bus, destination, path):
    path = menu_path(bus, destination, path)
    if path is None:
        return False

    apply_dark_theme()

    try:
        menu = DbusmenuGtk3.Menu.new(destination, path)
    except GLib.Error as error:
        log(f"Dbusmenu create error: {error.message}")
        return False

    anchor = create_anchor()
    opened = {"value": False}
    closing = {"scheduled": False}

    def finish_close():
        anchor.destroy()
        Gtk.main_quit()
        return False

    def close_menu(*_args):
        if closing["scheduled"]:
            return

        closing["scheduled"] = True
        log("Dbusmenu menu closed, waiting for item activation")
        GLib.timeout_add(QUIT_DELAY_MS, finish_close)

    def show_menu():
        try:
            menu.show_all()
            menu.popup_at_widget(
                anchor,
                Gdk.Gravity.NORTH_WEST,
                Gdk.Gravity.NORTH_WEST,
                None,
            )
            opened["value"] = True
            log("Dbusmenu popup requested")
        except Exception as error:
            log(f"Dbusmenu popup error: {error}")
            anchor.destroy()
            Gtk.main_quit()
        return False

    menu.connect("deactivate", close_menu)
    GLib.timeout_add(MENU_LOAD_DELAY_MS, show_menu)
    Gtk.main()
    return opened["value"]


def resolve_target():
    requested = sys.argv[1] if len(sys.argv) > 1 else "network"
    name = TARGET_ALIASES.get(requested, requested)
    if name not in TARGETS:
        log(f"Unknown target '{requested}', using network")
        name = "network"

    return name, TARGETS[name]


def main():
    target_name, target = resolve_target()
    log(f"--- invocation: {target_name} ---")
    try:
        bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    except GLib.Error as error:
        log(f"DBus setup error: {error.message}")
        return 1

    item = cached_item(target_name)
    if item is not None:
        log(f"Trying cached item: {item}")
        destination, path = parse_item(item)
        if item_matches(bus, destination, path, item, target, 100) and open_dbus_menu(
            bus,
            destination,
            path,
        ):
            log(f"Opened cached {target_name} tray menu")
            return 0

    try:
        items = registered_items(bus)
        log(f"Registered items: {items}")
    except GLib.Error as error:
        log(f"StatusNotifierWatcher error: {error.message}")
        items = discover_items(bus, target)

    for item in items:
        destination, path = parse_item(item)
        if item_matches(bus, destination, path, item, target) and open_dbus_menu(
            bus,
            destination,
            path,
        ):
            write_cache(target_name, item)
            log(f"Opened {target_name} tray menu")
            return 0

    log(f"No matching {target_name} tray item opened")
    return 1


if __name__ == "__main__":
    sys.exit(main())
