from dataclasses import replace

from sc2tray import panel, text
from sc2tray.state import ControllerState

LIVE = ControllerState(battery_pct=78, connected=True, provisional=False, connection="receiver",
                       receiver=True, signal_dbm=-52, eta_min=190, last_seen="14:32")
OFF = replace(LIVE, connected=False, provisional=True, connection="", signal_dbm=None, eta_min=None)


def test_headline_and_detail():
    assert text.headline(LIVE, False) == "Conectado"
    assert text.detail(LIVE) == ("hourglass", "Quedan ~3 h 10 min")
    assert text.headline(replace(LIVE, battery_pct=12), True) == "Baja — conéctalo"
    charging = replace(LIVE, charging=True, eta_min=80)
    assert (text.headline(charging, False), text.detail(charging)) == ("Cargando", ("hourglass", "Lleno en ~1 h 20 min"))
    full = replace(LIVE, charging=True, charged=True, eta_min=None)
    assert (text.headline(full, False), text.detail(full)) == ("Cargado", None)
    assert text.headline(replace(LIVE, provisional=True), False) == "Leyendo batería…"
    assert text.headline(OFF, False) == "Apagado o fuera de alcance"
    assert text.detail(OFF) == ("clock", "Último dato 14:32")
    assert text.detail(replace(OFF, last_seen="")) == ("clock", "Último valor conocido")
    assert text.headline(replace(OFF, docked=True), False) == "Apagado en el dock"
    assert text.headline(replace(OFF, battery_pct=-1, receiver=False), False) == "Receptor no conectado"
    assert text.detail(replace(OFF, battery_pct=-1, last_seen="")) is None
    assert (text.signal(LIVE), text.signal(OFF)) == ("−52 dBm", "—")


def test_status_lines():
    assert panel.status_lines(LIVE, "puck") == [("dot", "Conectado"), ("bars", "−52 dBm"),
                                                ("hourglass", "Quedan ~3 h 10 min")]
    bt = replace(LIVE, connection="bluetooth", signal_dbm=None, eta_min=None)
    assert panel.status_lines(bt, "bluetooth") == [("bluetooth", "Conectado")]
    usb = replace(LIVE, connection="usb", charging=True, signal_dbm=None, eta_min=40)
    assert panel.status_lines(usb, "usb") == [("bolt", "Cargando"), ("hourglass", "Lleno en ~40 min")]
    assert panel.status_lines(replace(LIVE, battery_pct=12), "low")[0] == ("dot", "Baja — conéctalo")
    assert panel.status_lines(replace(OFF, docked=True), "dock") == [("bolt", "Apagado en el dock"),
                                                                    ("clock", "Último dato 14:32")]


def test_layout():
    bottom2, h2 = panel.layout(2)
    assert panel.layout(1) == (bottom2, h2)         # room for the link icon beside two lines
    bottom3, h3 = panel.layout(3)
    assert bottom3 - bottom2 == h3 - h2 == panel.LINE_STEP
    assert h2 == bottom2 + panel.BTN_GAP + panel.BTN_H + panel.PAD


def test_link_box():
    bottom, _ = panel.layout(2)
    for name in ("puck", "steam-machine", "bluetooth", "usb-c"):
        x, y, size = panel.link_box(name, bottom)
        left, top, right, foot = panel._ink(name)
        assert abs(y + foot * size - bottom) < 1e-6                         # foot on the battery's
        assert abs(x + right * size - (panel.BAT_X[0] - panel.LINK_GAP)) < 1e-6
        assert y + top * size > panel.ART[1] + panel.ART[3] - 30           # beside the info block
    assert panel.link_box("puck", bottom)[2] == round(50 * 1.3)
    assert 120 <= panel.text_room("puck") < panel.text_room(None)


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
