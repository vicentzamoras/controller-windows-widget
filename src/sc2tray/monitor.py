"""Background thread that reads the controller and keeps a ControllerState up to date.

Port of the reference daemon's main loop (sc_battery_daemon.py) to hidapi:
find the streaming slot, decode 0x43 (battery % + charge state) and 0x7b
(signal), poll the dock, and treat 2 s of silence as the pad switching off.
"""
import threading
import time
from collections import deque
from dataclasses import replace
from datetime import datetime

from . import device
from . import protocol as p
from .state import ControllerState, Tracker

SILENCE_DISCONNECT = 2      # s without reports -> pad is off (awake it streams ~260 reports/s)
SIGNAL_WINDOW = 6           # 0x7b readings averaged for the signal strength (~2-3 s)
SIGNAL_STALE = 10           # s without a reading -> no signal value (Bluetooth/USB have none)
DOCK_POLL = 3               # s between "is the pad on the dock?" queries
HEARTBEAT = 30              # s: republish even without changes (keeps the ETA moving)


class DockPoller(threading.Thread):
    """Asks the puck every few seconds whether a pad sits on its dock.

    Runs apart from the reader so the ~50 ms query never stalls the report stream.
    """

    def __init__(self, stop):
        super().__init__(name="sc2-dock", daemon=True)
        self._stop = stop
        self.docked = False

    def run(self):
        while not self._stop.is_set():
            coll = device.dock_collection()
            if coll is None:
                self.docked = False
            else:
                v = device.query_dock(coll)
                if v is not None:       # None = Steam's answer or a busy device: keep the last value
                    self.docked = v
            self._stop.wait(DOCK_POLL)


class Monitor(threading.Thread):
    def __init__(self, on_change):
        super().__init__(name="sc2-monitor", daemon=True)
        self._on_change = on_change
        self._stop = threading.Event()
        self._dock = DockPoller(self._stop)
        self._tracker = Tracker()
        self._st = ControllerState(battery_pct=self._tracker.last_known())
        self._published = None
        self._published_at = 0
        self.live_path = None   # HID path of the streaming slot, for haptics

    @property
    def state(self):
        return self._published or replace(self._st)

    def history(self):
        """[time, %, charging] points of the last 24 h (a copy: safe from any thread)."""
        return list(self._tracker.history)

    def stop(self):
        self._stop.set()

    def run(self):
        self._dock.start()
        self._publish()
        while not self._stop.is_set():
            coll, dev, receiver = device.find_live()
            self._st.receiver = receiver
            if dev is None:
                self._idle(receiver)
                self._stop.wait(1)
                continue
            self._stream(coll, dev)

    def _idle(self, receiver):
        st = self._st
        st.connected = False
        st.internal = False
        st.signal_dbm = None
        st.charged = False          # unknown without reports
        st.provisional = True       # battery_pct is now the last known value
        st.docked = receiver and self._dock.docked
        st.charging = st.docked     # off on the dock still charges
        st.connection = "receiver" if st.docked else ""
        self._publish()

    def _stream(self, coll, dev):
        st = self._st
        self.live_path = coll.path
        st.connection = coll.connection
        st.internal = coll.pid == p.PID_PUCK_INTERNAL
        st.charged = False
        st.signal_dbm = None
        charge = None
        rssi, rssi_at = deque(maxlen=SIGNAL_WINDOW), 0
        silent_since = None
        try:
            while not self._stop.is_set():
                data = dev.read(64, 1000)
                now = time.time()
                if not data:
                    silent_since = silent_since or now
                    if now - silent_since >= SILENCE_DISCONNECT:
                        break       # rescan, so a switch to cable/Bluetooth is noticed too
                    continue
                silent_since = None
                st.connected = True
                # The dock charges the pad whatever link it uses (puck radio or Bluetooth)
                st.docked = st.connection != "usb" and self._dock.docked

                battery = p.parse_battery(data)
                if battery:
                    charge = battery
                    st.battery_pct = battery.level
                    st.provisional = False
                if charge:
                    st.charging = charge.on_power or st.docked
                    st.charged = charge.full
                else:
                    st.charging = st.docked or st.connection == "usb"

                dbm = p.parse_signal(data)
                if dbm is not None:
                    rssi.append(dbm)
                    rssi_at = now
                st.signal_dbm = round(sum(rssi) / len(rssi)) if rssi and now - rssi_at < SIGNAL_STALE else None
                st.last_seen = datetime.now().strftime("%H:%M")
                self._publish()
        except OSError:
            pass                    # unplugged / link lost: rescan
        finally:
            dev.close()
            self.live_path = None
            st.connected = False
            st.charged = False
            st.signal_dbm = None
            st.provisional = True

    def _publish(self):
        now = time.time()
        self._tracker.update(self._st, now)
        snap = replace(self._st)
        if snap == self._published and now - self._published_at < HEARTBEAT:
            return
        self._published, self._published_at = snap, now
        self._on_change(snap)
