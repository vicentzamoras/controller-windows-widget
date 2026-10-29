"""The system tray app: icon, tooltip, context menu and notifications."""
import ctypes
import os
import tempfile
import threading

import pystray
from pystray import Menu, MenuItem

from . import config, device, icons
from . import protocol as p
from .monitor import Monitor
from .state import ControllerState

THEME_POLL = 10             # s between checks of the taskbar's light/dark theme
TOOLTIP_MAX = 127           # Windows truncates NOTIFYICONDATA.szTip beyond this
SM_CXSMICON = 49

MELODY_LABELS = [("ticktock", "Tic-tac"), ("bird", "Pájaro"), ("ringing", "Timbre"),
                 ("sos", "SOS"), ("alarm", "Alarma")]
SIGNAL_LABELS = {4: "excelente", 3: "buena", 2: "regular", 1: "débil"}


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


def connection_label(st):
    if st.connection == "receiver":
        return "Steam Machine" if st.internal else "Puck"
    return {"bluetooth": "Bluetooth", "usb": "USB-C"}.get(st.connection, "")


def duration(minutes):
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def header(st):
    if st.connected and st.battery_pct >= 0 and not st.provisional:
        return f"Steam Controller 2 — {st.battery_pct} %"
    if st.connected:
        return "Steam Controller 2 — leyendo batería…"
    return "Steam Controller 2 — sin conexión"


def status(st):
    if not st.connected:
        if st.docked:
            return "Apagado en el dock · cargando"
        if st.receiver:
            return "Mando apagado o fuera de alcance"
        return "Receptor no conectado"
    parts = ["Cargado" if st.charged else "Cargando" if st.charging else "Con batería", connection_label(st)]
    if st.docked:
        parts.append("en el dock")
    return " · ".join(x for x in parts if x)


def tooltip(st):
    lines = [header(st), status(st)]
    if st.signal_dbm is not None:
        lines.append(f"Señal {SIGNAL_LABELS[p.signal_bars(st.signal_dbm)]} ({st.signal_dbm} dBm)".replace("-", "−"))
    if st.eta_min is not None:
        lines.append(f"Lleno en ~{duration(st.eta_min)}" if st.charging else f"Quedan ~{duration(st.eta_min)}")
    elif not st.connected and st.battery_pct >= 0:
        lines.append(f"Último nivel: {st.battery_pct} %" + (f" ({st.last_seen})" if st.last_seen else ""))
    return "\n".join(lines)[:TOOLTIP_MAX]


class App:
    def __init__(self):
        self.cfg = config.Config()
        self.size = small_icon_size()
        self.light = config.taskbar_is_light()
        self.state = ControllerState()
        self._drawn = None
        self._low_notified = False
        self._stop = threading.Event()
        self.monitor = Monitor(self.on_change)
        self.icon = TrayIcon("SC2Tray", self._image(), tooltip(self.state), self._menu())

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

    def _notify(self, prev, st):
        cfg = self.cfg
        live = st.connected and not st.provisional and st.battery_pct >= 0
        if live and not st.charging and st.battery_pct <= cfg["low_threshold"]:
            if not self._low_notified and cfg["notify_low"]:
                eta = f"Quedan ~{duration(st.eta_min)}. " if st.eta_min else ""
                self.icon.notify(f"{eta}Pon el mando en el puck o conéctalo por USB-C.",
                                 f"Batería baja: {st.battery_pct} %")
            self._low_notified = True
        elif live and (st.charging or st.battery_pct > cfg["low_threshold"] + 2):
            self._low_notified = False
        if st.charged and not prev.charged and prev.connected and cfg["notify_full"]:
            self.icon.notify("El Steam Controller está al 100 %.", "Carga completa")
        if prev.connected and not st.connected and cfg["notify_disconnect"]:
            last = f"Último nivel conocido: {st.battery_pct} %." if st.battery_pct >= 0 else ""
            self.icon.notify(last or "El mando se apagó o perdió la conexión.", "Mando desconectado")

    def _watch_theme(self):
        while not self._stop.wait(THEME_POLL):
            light = config.taskbar_is_light()
            if light != self.light:
                self.light = light
                self._refresh()

    # --- menu --------------------------------------------------------------

    def _find(self, melody):
        def action(icon, item):
            path = self.monitor.live_path
            if path:
                threading.Thread(target=self._run_find, args=(path, melody), daemon=True).start()
        return action

    def _run_find(self, path, melody):
        try:
            device.find_controller(path, p.MELODIES.get(melody) if melody else None)
        except OSError:
            self.icon.notify("No se pudo enviar la señal al mando.", "Buscar mando")

    def _toggle(self, key):
        def action(icon, item):
            self.cfg.toggle(key)
        return action

    def _toggle_autostart(self, icon, item):
        try:
            config.set_autostart(not config.autostart_enabled())
        except OSError:
            self.icon.notify("No se pudo cambiar el inicio automático.", "SC2Tray")

    def _quit(self, icon, item):
        self._stop.set()
        self.monitor.stop()
        icon.stop()

    def _menu(self):
        awake = lambda item: self.monitor.live_path is not None
        find = Menu(
            MenuItem("Solo vibración", self._find(None)),
            Menu.SEPARATOR,
            *[MenuItem(label, self._find(name)) for name, label in MELODY_LABELS])
        return Menu(
            MenuItem(lambda item: header(self.state), None, enabled=False),
            MenuItem(lambda item: status(self.state), None, enabled=False),
            Menu.SEPARATOR,
            MenuItem("Buscar mando", find, enabled=awake),
            Menu.SEPARATOR,
            MenuItem(lambda item: f"Avisar con batería baja ({self.cfg['low_threshold']} %)",
                     self._toggle("notify_low"), checked=lambda item: self.cfg["notify_low"]),
            MenuItem("Avisar al terminar la carga", self._toggle("notify_full"),
                     checked=lambda item: self.cfg["notify_full"]),
            MenuItem("Avisar al desconectarse", self._toggle("notify_disconnect"),
                     checked=lambda item: self.cfg["notify_disconnect"]),
            MenuItem("Iniciar con Windows", self._toggle_autostart,
                     checked=lambda item: config.autostart_enabled()),
            Menu.SEPARATOR,
            MenuItem("Salir", self._quit))

    # --- lifecycle ---------------------------------------------------------

    def _setup(self, icon):
        icon.visible = True
        self.monitor.start()
        threading.Thread(target=self._watch_theme, name="sc2-theme", daemon=True).start()

    def run(self):
        self.icon.run(setup=self._setup)


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
