"""User-facing wording shared by the tooltip, the menu and the panel."""
from . import protocol as p
from .i18n import t

TOOLTIP_MAX = 127           # Windows truncates NOTIFYICONDATA.szTip beyond this


def connection_label(st):
    if st.connection == "receiver":
        return "Steam Machine" if st.internal else "Puck"
    return {"bluetooth": "Bluetooth", "usb": "USB-C"}.get(st.connection, "")


def duration(minutes):
    h, m = divmod(minutes, 60)
    return f"{h} h {m} min" if h else f"{m} min"


def header(st):
    if st.connected and st.battery_pct >= 0 and not st.provisional:
        return t("header", n=st.battery_pct)
    if st.connected:
        return t("header_reading")
    return t("header_off")


def status(st):
    if not st.connected:
        if st.docked:
            return t("status_dock_off")
        if st.receiver:
            return t("status_off")
        return t("status_no_receiver")
    parts = [t("charged") if st.charged else t("charging") if st.charging else t("status_on_battery"),
             connection_label(st)]
    if st.docked:
        parts.append(t("status_on_dock"))
    return " · ".join(x for x in parts if x)


def tooltip(st):
    lines = [header(st), status(st)]
    if st.signal_dbm is not None:
        lines.append(t(f"signal_{p.signal_bars(st.signal_dbm)}", dbm=st.signal_dbm).replace("-", "−"))
    if st.eta_min is not None:
        lines.append(t("full_in" if st.charging else "time_left", time=duration(st.eta_min)))
    elif not st.connected and st.battery_pct >= 0:
        lines.append(t("last_level", n=st.battery_pct) + (f" ({st.last_seen})" if st.last_seen else ""))
    return "\n".join(lines)[:TOOLTIP_MAX]


# --- panel -------------------------------------------------------------------
# Short: the lines sit beside the link icon, as on the reference widget's card

def headline(st, low):
    """First status line; `low` = the level is at or below the warning threshold."""
    if not st.connected:
        if st.docked:
            return t("on_dock")
        return t("disconnected") if st.receiver else t("status_no_receiver")
    if st.provisional or st.battery_pct < 0:
        return t("reading")
    if st.charged:
        return t("charged")
    if st.charging:
        return t("charging")
    return t("low_battery") if low else t("connected")


def detail(st):
    """Second status line for a pad that is off, as (icon, text): the age of the reading
    shown, or None. Time left stays in the tooltip, so the card keeps one height."""
    if not st.connected and st.battery_pct >= 0:
        return "clock", t("data_from", time=st.last_seen) if st.last_seen else t("last_value")
    return None


def signal(st):
    return f"{st.signal_dbm} dBm".replace("-", "−") if st.signal_dbm is not None else "—"
