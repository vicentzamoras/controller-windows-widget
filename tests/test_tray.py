from dataclasses import replace

from sc2tray import icons, tray
from sc2tray.state import ControllerState

LIVE = ControllerState(battery_pct=78, connected=True, provisional=False, connection="receiver",
                       receiver=True, signal_dbm=-52, eta_min=190, last_seen="14:32")


def test_tooltip_live():
    assert tray.tooltip(LIVE) == ("Steam Controller 2: 78 %\nCon batería · Puck\n"
                                  "Señal excelente (−52 dBm)\nQuedan ~3 h 10 min")


def test_tooltip_states():
    charging = replace(LIVE, charging=True, docked=True, signal_dbm=None, eta_min=80)
    assert tray.tooltip(charging).splitlines()[1:] == ["Cargando · Puck · en el dock", "Lleno en ~1 h 20 min"]
    off = replace(LIVE, connected=False, provisional=True, connection="", signal_dbm=None, eta_min=None)
    assert tray.tooltip(off).splitlines() == ["Steam Controller 2: sin conexión",
                                              "Mando apagado o fuera de alcance", "Último nivel: 78 % (14:32)"]
    assert tray.status(replace(off, receiver=False)) == "Receptor no conectado"
    assert tray.status(replace(off, docked=True)) == "Apagado en el dock · cargando"
    assert tray.status(replace(LIVE, connection="usb", charging=True, charged=True)) == "Cargado · USB-C"
    assert len(tray.tooltip(LIVE)) <= tray.TOOLTIP_MAX


def test_icon_kind():
    assert icons.kind_of(LIVE, 15) == icons.NORMAL
    assert icons.kind_of(replace(LIVE, battery_pct=15), 15) == icons.LOW
    assert icons.kind_of(replace(LIVE, charging=True), 15) == icons.CHARGING
    assert icons.kind_of(replace(LIVE, charging=True, charged=True), 15) == icons.FULL
    assert icons.kind_of(replace(LIVE, connected=False, docked=True), 15) == icons.DOCK
    assert icons.kind_of(replace(LIVE, connected=False), 15) == icons.OFF
    assert icons.render(icons.CHARGING, 46, False, 20).size == (20, 20)


class FakeIcon:
    def __init__(self):
        self.sent = []

    def notify(self, message, title):
        self.sent.append(title)


def make_app():
    app = object.__new__(tray.App)
    app.cfg = {"notify_low": True, "low_threshold": 15, "notify_full": True, "notify_disconnect": False}
    app.icon = FakeIcon()
    app._low_notified = False
    return app


def test_low_battery_notifies_once_until_recharged():
    app = make_app()
    for pct in (16, 15, 14, 13):
        app._notify(replace(LIVE, battery_pct=pct + 1), replace(LIVE, battery_pct=pct))
    assert app.icon.sent == ["Batería baja: 15 %"]
    app._notify(LIVE, replace(LIVE, battery_pct=13, charging=True))      # put on charge: re-arms
    app._notify(LIVE, replace(LIVE, battery_pct=12))
    assert app.icon.sent == ["Batería baja: 15 %", "Batería baja: 12 %"]


def test_full_and_disconnect():
    app = make_app()
    app._notify(replace(LIVE, charging=True), replace(LIVE, charging=True, charged=True))
    assert app.icon.sent == ["Carga completa"]
    app._notify(LIVE, replace(LIVE, connected=False))
    assert app.icon.sent == ["Carga completa"]                           # off by default
    app.cfg["notify_disconnect"] = True
    app._notify(LIVE, replace(LIVE, connected=False))
    assert app.icon.sent[-1] == "Mando desconectado"
