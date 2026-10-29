"""HID access on Windows through hidapi: the live controller, the dock query, haptics.

Windows splits every interface of the puck into collections (mouse, keyboard,
vendor). Mouse and keyboard are held exclusively by the OS; the reports we
need (0x42/0x43/0x7b) all arrive on the vendor collection (usage page 0xFF00)
of the slot the pad is linked to (interfaces 2-5). Interface 6 is the dock.
Reading is shared with Steam, so the app works with Steam running.
"""
import time
from dataclasses import dataclass

import hid

from . import protocol as p

BUS_BLUETOOTH = 2           # hidapi's HID_API_BUS_BLUETOOTH
PROBE_MS = 150              # an awake pad streams ~260 reports/s, so silence this long = idle slot


@dataclass(frozen=True)
class Collection:
    path: bytes
    pid: int
    interface: int
    bus_type: int

    @property
    def connection(self):
        if self.bus_type == BUS_BLUETOOTH or self.pid == p.PID_BLUETOOTH:
            return "bluetooth"
        if self.pid in p.RECEIVER_PIDS:
            return "receiver"
        return "usb"

    @property
    def is_dock(self):
        return self.pid == p.PID_PUCK and self.interface == p.DOCK_INTERFACE


def vendor_collections():
    return [Collection(d["path"], d["product_id"], d["interface_number"], d.get("bus_type", 0))
            for d in hid.enumerate(p.VID, 0)
            if d["product_id"] in p.ALL_PIDS and d["usage_page"] == p.VENDOR_USAGE_PAGE]


def open_path(path):
    dev = hid.device()
    dev.open_path(path)
    return dev


def find_live():
    """(collection, open device, receiver present) for the slot that is streaming.

    With no pad awake: (None, None, receiver present). The caller owns the device.
    """
    receiver = False
    for c in vendor_collections():
        receiver = receiver or c.connection == "receiver"
        if c.is_dock:
            continue
        try:
            dev = open_path(c.path)
        except OSError:
            continue
        try:
            if dev.read(64, PROBE_MS):
                return c, dev, receiver
        except OSError:
            pass
        dev.close()
    return None, None, receiver


def dock_collection():
    return next((c for c in vendor_collections() if c.is_dock), None)


def query_dock(coll):
    """True/False = pad on/off the puck's dock, None = no answer (busy, unplugged)."""
    try:
        dev = open_path(coll.path)
    except OSError:
        return None
    try:
        if dev.send_feature_report(p.DOCK_QUERY) < 0:
            return None
        time.sleep(0.05)
        return p.parse_dock_answer(bytes(dev.get_feature_report(p.DOCK_FEATURE_ID, 65)))
    except OSError:
        return None
    finally:
        dev.close()


def _rumble_for(dev, speed, secs):
    end = time.time() + secs
    while time.time() < end:
        dev.write(p.rumble(speed))
        time.sleep(p.RUMBLE_PERIOD)


def _play(dev, notes):
    for freq, ms in notes:
        if freq:
            for side in (0, 1):
                dev.write(p.tone(side, freq, ms))
        time.sleep(ms / 1000 + 0.04)


def find_controller(path, melody=None, rounds=3):
    """Makes the pad findable: pulses, or a tune alternated with rumble bursts."""
    dev = open_path(path)
    try:
        if melody:
            for _ in range(rounds):
                _play(dev, melody)
                _rumble_for(dev, 65535, 0.8)
                dev.write(p.rumble(0))
                time.sleep(0.4)
        else:
            for speed, secs in p.FIND_PATTERN:
                _rumble_for(dev, speed, secs)
        dev.write(p.rumble(0))
    finally:
        dev.close()
