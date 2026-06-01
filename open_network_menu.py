#!/usr/bin/env python3
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
WATCHER_BUS = "org.kde.StatusNotifierWatcher"
WATCHER_PATH = "/StatusNotifierWatcher"
WATCHER_IFACE = "org.kde.StatusNotifierWatcher"
ITEM_IFACE = "org.kde.StatusNotifierItem"
MENU_LOAD_DELAY_MS = 100
QUIT_DELAY_MS = 600
ANCHOR_SIZE = 1
WAYBAR_OFFSET = 80
TARGET_ALIASES = {
    "vpn": "clash",
}
TARGETS = {
    "network": {
        "fallback": ["nm-connection-editor"],
        "markers": (
            "nm-applet",
            "nm_applet",
            "networkmanager",
            "network manager",
        ),
    },
    "clash": {
        "fallback": ["clash-verge"],
        "markers": (
            "clash-verge",
            "clash verge",
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


def property_value(bus, destination, path, interface, name):
    result = bus.call_sync(
        destination,
        path,
        "org.freedesktop.DBus.Properties",
        "Get",
        GLib.Variant("(ss)", (interface, name)),
        GLib.VariantType.new("(v)"),
        Gio.DBusCallFlags.NONE,
        1000,
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


def parse_item(item):
    log(f"Parsing item: {item}")
    if "/" not in item:
        return item, "/StatusNotifierItem"

    destination, path = item.split("/", 1)
    return destination, f"/{path}"


def item_matches(bus, destination, path, raw_item, target):
    candidates = [raw_item, path]

    for name in ("Id", "Title", "IconName"):
        try:
            value = property_value(bus, destination, path, ITEM_IFACE, name)
            candidates.append(value)
            log(f"{destination}{path} {name}: {value}")
        except GLib.Error as error:
            log(f"{destination}{path} {name} error: {error.message}")

    text = " ".join(str(value).lower() for value in candidates)
    matched = any(marker in text for marker in target["markers"])
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


def open_fallback(target):
    log(f"Opening fallback: {' '.join(target['fallback'])}")
    subprocess.Popen(target["fallback"])


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
        items = registered_items(bus)
        log(f"Registered items: {items}")
    except GLib.Error as error:
        log(f"DBus setup error: {error.message}")
        open_fallback(target)
        return 1

    for item in items:
        destination, path = parse_item(item)
        if item_matches(bus, destination, path, item, target) and open_dbus_menu(
            bus,
            destination,
            path,
        ):
            log(f"Opened {target_name} tray menu")
            return 0

    log(f"No matching {target_name} tray item opened")
    open_fallback(target)
    return 1


if __name__ == "__main__":
    sys.exit(main())
