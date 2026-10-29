"""User-facing wording shared by the tooltip, the menu and the panel."""
from . import protocol as p

TOOLTIP_MAX = 127           # Windows truncates NOTIFYICONDATA.szTip beyond this

SIGNAL_LABELS = {4: "excelente", 3: "buena", 2: "regular", 1: "débil"}


def connection_label(st):
    if st.connection == "receiver":
        return "Steam Machine" if st.internal else "Puck"
    return {"bluetooth": "Bluetooth", "usb": "USB-C"}.get(st.connection, "")


def duration(minutes):
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def header(st):
    if st.connected and st.battery_pct >= 0 and not st.provisional:
        return f"Steam Controller 2: {st.battery_pct} %"
    if st.connected:
        return "Steam Controller 2: leyendo batería…"
    return "Steam Controller 2: sin conexión"


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


# --- panel -------------------------------------------------------------------
# Short: the lines sit beside the link icon, as on the reference widget's card

def headline(st, low):
    """First status line; `low` = the level is at or below the warning threshold."""
    if not st.connected:
        if st.docked:
            return "En el dock"
        return "Sin conexión" if st.receiver else "Receptor no conectado"
    if st.provisional or st.battery_pct < 0:
        return "Leyendo…"
    if st.charged:
        return "Cargado"
    if st.charging:
        return "Cargando"
    return "Batería baja" if low else "Conectado"


def detail(st):
    """Second status line for a pad that is off, as (icon, text): the age of the reading
    shown, or None. Time left stays in the tooltip, so the card keeps one height."""
    if not st.connected and st.battery_pct >= 0:
        return "clock", f"Dato de {st.last_seen}" if st.last_seen else "Último valor"
    return None


def signal(st):
    return f"{st.signal_dbm} dBm".replace("-", "−") if st.signal_dbm is not None else "—"
