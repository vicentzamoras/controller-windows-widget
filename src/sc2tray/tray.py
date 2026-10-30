"""The system tray app: icon, tooltip, context menu, notifications and the flyout panel."""
import ctypes
import os
import tempfile
import threading

import pystray
from pystray import Menu, MenuItem

from . import config, device, i18n, icons
from . import protocol as p
from .monitor import Monitor
from .i18n import t
from .state import ControllerState
from .text import TOOLTIP_MAX, connection_label, duration, header, status, tooltip  # noqa: F401

THEME_POLL = 10             # s between checks of the light/dark theme
SM_CXSMICON = 49

APP_MODE_DARK, APP_MODE_LIGHT = 2, 3


def menu_theme(light):
    """Dark or light context menus, like the rest of Windows (uxtheme's unnamed
    SetPreferredAppMode / FlushMenuThemes, the ones Explorer and Notepad++ use)."""
    try:
        ux = ctypes.windll.uxtheme
        ux[135](APP_MODE_LIGHT if light else APP_MODE_DARK)
        ux[136]()
    except (OSError, AttributeError):
        pass


def small_icon_size():
    try:
        return ctypes.windll.user32.GetSystemMetrics(SM_CXSMICON) or 16
    except OSError:
        return 16


class TrayIcon(pystray.Icon):
    """Loads the icon at the image's own size.

    Stock pystray saves Pillow's default ICO sizes and loads the 32 px one,
    which the shell then shrinks; the fine level bar blurs at 16 px.
    """

    def _assert_icon_handle(self):
        if self._icon_handle:
            return
        from pystray._util import win32
        size = self.icon.width
        fd, path = tempfile.mkstemp(".ico")
        try:
            with os.fdopen(fd, "wb") as f:
                self.icon.save(f, format="ICO", sizes=[(size, size)])
            self._icon_handle = win32.LoadImage(None, path, win32.IMAGE_ICON, size, size, win32.LR_LOADFROMFILE)
        finally:
            os.remove(path)


class App:
    def __init__(self):
        self.cfg = config.Config()
        i18n.use(self.cfg["language"])
        self.size = small_icon_size()
        self.light = config.taskbar_is_light()
        self.apps_light = config.apps_use_light()
        menu_theme(self.apps_light)
        self.state = ControllerState()
        self._drawn = None
        self._low_notified = False
        self._stop = threading.Event()
        self.monitor = Monitor(self.on_change)
        self.icon = TrayIcon("SC2Tray", self._image(), tooltip(self.state), self._menu())
        from .panel import Panel     # Tk: created here, on the main thread
        self.panel = Panel(self)

    # --- rendering ---------------------------------------------------------

    def _key(self):
        st = self.state
        return icons.kind_of(st, self.cfg["low_threshold"]), st.battery_pct, self.light

    def _image(self):
        kind, pct, light = self._drawn = self._key()
        return icons.render(kind, pct, light, self.size)

    def _refresh(self):
        if self._key() != self._drawn:
            self.icon.icon = self._image()
        title = tooltip(self.state)
        if title != self.icon.title:
            self.icon.title = title
        self.icon.update_menu()

    # --- state changes -----------------------------------------------------

    def on_change(self, st):
        prev, self.state = self.state, st
        self._notify(prev, st)
        self._refresh()
        self.panel.call(self.panel.refresh)

    def _notify(self, prev, st):
        cfg = self.cfg
        live = st.connected and not st.provisional and st.battery_pct >= 0
        if live and not st.charging and st.battery_pct <= cfg["low_threshold"]:
            if not self._low_notified and cfg["notify_low"]:
                eta = t("low_eta", time=duration(st.eta_min)) if st.eta_min else ""
                self.icon.notify(eta + t("low_body"), t("low_title", n=st.battery_pct))
            self._low_notified = True
        elif live and (st.charging or st.battery_pct > cfg["low_threshold"] + 2):
            self._low_notified = False
        if st.charged and not prev.charged and prev.connected and cfg["notify_full"]:
            self.icon.notify(t("full_body"), t("full_title"))
        if prev.connected and not st.connected and cfg["notify_disconnect"]:
            last = t("gone_last", n=st.battery_pct) if st.battery_pct >= 0 else ""
            self.icon.notify(last or t("gone_body"), t("gone_title"))

    def _watch_theme(self):
        while not self._stop.wait(THEME_POLL):
            light = config.taskbar_is_light()
            if light != self.light:
                self.light = light
                self._refresh()
            apps_light = config.apps_use_light()
            if apps_light != self.apps_light:
                self.apps_light = apps_light
                menu_theme(apps_light)

    # --- menu --------------------------------------------------------------

    def find(self, melody):
        """Vibrates (melody None) or plays a tune on the awake pad, in the background."""
        path = self.monitor.live_path
        if path:
            threading.Thread(target=self._run_find, args=(path, melody), daemon=True).start()

    def _run_find(self, path, melody):
        try:
            device.find_controller(path, p.MELODIES.get(melody) if melody else None)
        except OSError:
            self.icon.notify(t("find_failed"), t("find"))

    def melodies(self):
        """(name in protocol.MELODIES, label) of the tunes "find" can play."""
        return [(name, t(f"melody_{name}")) for name in p.MELODIES]

    def toggles(self):
        """(config key, label) of the notification switches."""
        return [("notify_low", t("notify_low", n=self.cfg["low_threshold"])),
                ("notify_full", t("notify_full")),
                ("notify_disconnect", t("notify_disconnect"))]

    def languages(self):
        """(config value, label) of the language choices."""
        return [("system", t("language_system")), *i18n.LANGUAGES.items()]

    def set_language(self, choice):
        self.cfg.set("language", choice)
        i18n.use(choice)
        self.icon.menu = self._menu()   # its fixed labels are built in the old language
        self._refresh()
        self.panel.call(self.panel.refresh)

    def toggle_autostart(self):
        try:
            config.set_autostart(not config.autostart_enabled())
        except OSError:
            self.icon.notify(t("autostart_failed"), "SC2Tray")

    def quit(self):
        self._stop.set()
        self.monitor.stop()
        self.icon.stop()
        self.panel.call(self.panel.quit)

    def _menu(self):
        awake = lambda item: self.monitor.live_path is not None
        tune = lambda name: lambda: self.find(name)     # pystray actions take 0-2 arguments
        find = Menu(*[MenuItem(label, tune(name)) for name, label in self.melodies()])
        toggle = lambda key: MenuItem(lambda item: dict(self.toggles())[key], lambda: self.cfg.toggle(key),
                                      checked=lambda item: self.cfg[key])
        language = lambda choice, label: MenuItem(label, lambda: self.set_language(choice), radio=True,
                                                  checked=lambda item: self.cfg["language"] == choice)
        return Menu(
            # Default item: left click (and its bold label) opens the panel
            MenuItem(lambda item: header(self.state), lambda: self.panel.call(self.panel.toggle), default=True),
            Menu.SEPARATOR,
            MenuItem(t("find"), find, enabled=awake),
            Menu.SEPARATOR,
            *[toggle(key) for key, _ in self.toggles()],
            MenuItem(t("autostart"), self.toggle_autostart,
                     checked=lambda item: config.autostart_enabled()),
            MenuItem(t("language"), Menu(*[language(choice, label) for choice, label in self.languages()])),
            Menu.SEPARATOR,
            MenuItem(t("quit"), self.quit))

    # --- lifecycle ---------------------------------------------------------

    def _setup(self, icon):
        icon.visible = True
        self.monitor.start()
        threading.Thread(target=self._watch_theme, name="sc2-theme", daemon=True).start()

    def run(self):
        """pystray pumps its own Win32 loop in a thread; Tk keeps the main one."""
        self.icon.run_detached(setup=self._setup)
        try:
            self.panel.mainloop()
        finally:
            self.quit()


def run():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # system DPI: crisp menu and a true small-icon size
    except (OSError, AttributeError):
        pass
    mutex = config.single_instance()
    if mutex is None:
        return 0                # already running
    App().run()
    return 0
