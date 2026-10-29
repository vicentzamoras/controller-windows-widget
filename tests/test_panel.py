from dataclasses import replace

from sc2tray import panel, text
from sc2tray.state import ControllerState

LIVE = ControllerState(battery_pct=78, connected=True, provisional=False, connection="receiver",
                       receiver=True, signal_dbm=-52, eta_min=190, last_seen="14:32")
OFF = replace(LIVE, connected=False, provisional=True, connection="", signal_dbm=None, eta_min=None)


def test_headline_and_detail():
    assert text.headline(LIVE, False) == "Conectado"
    assert text.detail(LIVE) == ("hourglass", "Quedan ~3 h 10 min")
    assert text.headline(replace(LIVE, battery_pct=12), True) == "Batería baja — conéctalo"
    charging = replace(LIVE, charging=True, eta_min=80)
    assert (text.headline(charging, False), text.detail(charging)) == ("Cargando", ("hourglass", "Lleno en ~1 h 20 min"))
    full = replace(LIVE, charging=True, charged=True, eta_min=None)
    assert (text.headline(full, False), text.detail(full)) == ("Cargado", ("clock", "Actualizado a las 14:32"))
    assert text.headline(replace(LIVE, provisional=True), False) == "Leyendo batería…"
    assert text.headline(OFF, False) == "Mando apagado o fuera de alcance"
    assert text.detail(OFF) == ("clock", "Último valor conocido · 14:32")
    assert text.headline(replace(OFF, docked=True), False) == "Apagado en el dock"
    assert text.headline(replace(OFF, battery_pct=-1, receiver=False), False) == "Receptor no conectado"
    assert text.detail(replace(OFF, battery_pct=-1, last_seen="")) is None


def test_tiles():
    assert (text.link(LIVE), text.signal(LIVE), text.dock(LIVE)) == ("Puck", "−52 dBm", "No")
    assert text.link(replace(LIVE, internal=True)) == "Steam Machine"
    bt = replace(LIVE, connection="bluetooth", receiver=False, signal_dbm=None)
    assert (text.link(bt), text.signal(bt), text.dock(bt)) == ("Bluetooth", "—", "—")
    assert text.link(replace(LIVE, connection="usb")) == "USB-C"
    assert (text.link(OFF), text.dock(replace(OFF, docked=True))) == ("Sin conexión", "Sí")
    assert text.link(replace(OFF, docked=True)) == "Puck"


def test_state_role():
    assert panel.state_role(LIVE, 15) == "puck"
    assert panel.state_role(replace(LIVE, connection="bluetooth"), 15) == "bluetooth"
    assert panel.state_role(replace(LIVE, connection="usb", charging=True), 15) == "usb"
    assert panel.state_role(replace(LIVE, battery_pct=15), 15) == "low"
    assert panel.state_role(replace(LIVE, battery_pct=15, charging=True), 15) == "puck"
    assert panel.state_role(replace(OFF, docked=True), 15) == "dock"
    assert panel.state_role(OFF, 15) == "off"


def test_icons_and_bolt():
    assert panel.link_icon(LIVE) == "puck"
    assert panel.link_icon(replace(LIVE, internal=True)) == "steam-machine"
    assert panel.link_icon(replace(LIVE, connection="usb")) == "usb-c"
    assert (panel.link_icon(OFF), panel.link_icon(replace(OFF, docked=True))) == (None, "puck")
    assert panel.charging(replace(LIVE, charging=True))
    assert not panel.charging(replace(LIVE, charging=True, charged=True))
    assert panel.charging(replace(OFF, docked=True))
    assert (panel.ink_on(panel.STATE["puck"]), panel.ink_on(panel.STATE["low"])) == ("#23262A", "#FCFCFC")


def test_assets_present():
    for name in ("bluetooth", "bolt", "clock", "hourglass", "locate", "puck", "steam-machine", "usb-c",
                 "steam-controller-body", "steam-controller-lines"):
        assert panel._mask(name).mode == "L"
