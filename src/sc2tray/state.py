"""Controller state, time-left estimate and the persisted battery history."""
import json
import os
import time
from dataclasses import dataclass, field

from .config import DATA_DIR

HISTORY_FILE = DATA_DIR / "history.json"
HISTORY_STEP = 300          # s between history points (plus one on every charge/link change)
HISTORY_SPAN = 24 * 3600
ETA_MIN_SPAN = 300          # s of readings, and...
ETA_MIN_DELTA = 2           # ...% of change, before a time estimate is given


@dataclass
class ControllerState:
    battery_pct: int = -1       # -1 = never seen
    connected: bool = False     # a pad is streaming reports
    charging: bool = False
    charged: bool = False       # on power and full: the pad says charging is done
    provisional: bool = True    # battery_pct is the last known value, not a live one
    connection: str = ""        # "receiver", "bluetooth", "usb" or ""
    receiver: bool = False      # a puck is plugged in
    docked: bool = False        # pad sits on the puck's charging dock
    internal: bool = False      # linked through the Steam Machine's built-in receiver
    signal_dbm: int | None = None
    eta_min: int | None = None  # minutes until empty (discharging) or full (charging)
    last_seen: str = ""         # HH:MM of the last report


def load_history():
    try:
        with open(HISTORY_FILE) as f:
            h = json.load(f)
        cutoff = time.time() - HISTORY_SPAN
        return [x for x in h if isinstance(x, list) and len(x) == 3 and x[0] >= cutoff]
    except (OSError, ValueError):
        return []


def save_history(history):
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        tmp = HISTORY_FILE.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(history, f)
        os.replace(tmp, HISTORY_FILE)
    except OSError:
        pass


@dataclass
class Tracker:
    """Feeds the time estimate and the history from successive readings."""
    history: list = field(default_factory=load_history)
    _seg: list = field(default_factory=list)    # (time, %) since the charging state / link last changed
    _seg_key: tuple | None = None
    _hist_key: tuple | None = None

    def last_known(self):
        return self.history[-1][1] if self.history else -1

    def update(self, st, now):
        live = st.connected and not st.provisional and st.battery_pct >= 0
        key = (st.charging, st.connection) if live else None
        if key != self._seg_key:
            self._seg, self._seg_key = [], key
        st.eta_min = None
        if not live:
            return
        if not self._seg or self._seg[-1][1] != st.battery_pct:
            self._seg.append((now, st.battery_pct))
        t0, p0 = self._seg[0]
        dp = st.battery_pct - p0
        if now - t0 >= ETA_MIN_SPAN and abs(dp) >= ETA_MIN_DELTA:
            rate = dp / ((now - t0) / 60)                   # % per minute
            if not st.charging and rate < 0:
                st.eta_min = round(st.battery_pct / -rate)
            elif st.charging and rate > 0:
                st.eta_min = round((100 - st.battery_pct) / rate)
            if st.eta_min is not None and st.eta_min > 24 * 60:
                st.eta_min = None
        hkey = (st.charging, st.connection)
        if not self.history or now - self.history[-1][0] >= HISTORY_STEP or hkey != self._hist_key:
            self._hist_key = hkey
            self.history.append([int(now), st.battery_pct, 1 if st.charging else 0])
            self.history = [h for h in self.history if now - h[0] <= HISTORY_SPAN]
            save_history(self.history)
