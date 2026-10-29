from dataclasses import replace

from sc2tray import panel, text
from sc2tray.state import ControllerState

LIVE = ControllerState(battery_pct=78, connected=True, provisional=False, connection="receiver",
                       receiver=True, signal_dbm=-52, eta_min=190, last_seen="14:32")
OFF = replace(LIVE, connected=False, provisional=True, connection="", signal_dbm=None, eta_min=None)


def test_panel_status():
    assert text.panel_status(LIVE, False) == "Con batería · quedan ~3 h 10 min"
    assert text.panel_status(replace(LIVE, battery_pct=12, eta_min=25), True) == "Batería baja · quedan ~25 min"
    assert text.panel_status(replace(LIVE, charging=True, eta_min=80), False) == "Cargando · lleno en ~1 h 20 min"
    assert text.panel_status(replace(LIVE, charging=True, charged=True, eta_min=None), False) == "Cargado"
    assert text.panel_status(replace(LIVE, provisional=True), False) == "Leyendo batería…"
    assert text.panel_status(OFF, False) == "Desconectado · último valor conocido"
    assert text.panel_status(replace(OFF, docked=True), False) == "Apagado en el dock · cargando"
    assert text.panel_status(replace(OFF, battery_pct=-1, receiver=False), False) == "Receptor no conectado"


def test_link_chip_signal():
    assert (text.chip(LIVE), text.link(LIVE), text.signal(LIVE)) == ("Puck", "Puck (receptor)", "−52 dBm")
    docked = replace(LIVE, docked=True)
    assert (text.chip(docked), text.link(docked)) == ("En el dock", "Puck · en el dock")
    assert text.link(replace(LIVE, internal=True)) == "Steam Machine"
    bt = replace(LIVE, connection="bluetooth", signal_dbm=None)
    assert (text.chip(bt), text.link(bt), text.signal(bt)) == ("Bluetooth", "Bluetooth", "sin lectura")
    assert text.link(replace(LIVE, connection="usb")) == "USB-C (cable)"
    assert (text.chip(OFF), text.link(OFF)) == ("Sin conexión", "—")


def test_tone():
    assert panel.tone(LIVE, 15) == "neutral"
    assert panel.tone(replace(LIVE, battery_pct=15), 15) == "low"
    assert panel.tone(replace(LIVE, charging=True), 15) == "accent"
    assert panel.tone(replace(OFF, docked=True), 15) == "accent"
    assert panel.tone(OFF, 15) == "off"


def test_chart_points():
    now = 100_000
    hist = [[now - 30 * 3600, 99, 0], [now - 24 * 3600, 90, 0], [now - 12 * 3600, 60, 0]]
    assert panel.chart_points(hist, now) == [(0.0, 0.9), (0.5, 0.6)]
    assert panel.chart_points(hist, now, current=40)[-1] == (1.0, 0.4)
    assert panel.chart_points(hist, now, current=-1) == [(0.0, 0.9), (0.5, 0.6)]
    assert panel.chart_points([[now - 600, 80, 0]], now, current=79) == []     # 10 min: too little
