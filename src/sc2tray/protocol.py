"""Steam Controller 2 ("Triton") HID protocol: device IDs, report decoding, output reports.

Reverse engineered in jahrekza/steam-controller-plasma-widget (MIT, see NOTICE.md),
with report layouts from SDL's SDL_hidapi_steam_triton.c. Pure functions only:
no I/O, so everything here is testable without a controller.
"""
import struct
from dataclasses import dataclass

VID = 0x28DE
PID_USB = 0x1302            # pad on a USB-C cable
PID_BLUETOOTH = 0x1303      # pad paired over Bluetooth LE
PID_PUCK = 0x1304           # standalone wireless receiver ("puck") with charging dock
PID_PUCK_INTERNAL = 0x1305  # receiver built into the Steam Machine (no dock)
RECEIVER_PIDS = (PID_PUCK, PID_PUCK_INTERNAL)
ALL_PIDS = RECEIVER_PIDS + (PID_USB, PID_BLUETOOTH)

VENDOR_USAGE_PAGE = 0xFF00  # Windows splits each interface; only this collection carries our reports
DOCK_INTERFACE = 6          # puck interface that answers the dock query (the only one without OUTPUT reports)

REPORT_BATTERY = 0x43       # ID_TRITON_BATTERY_STATUS, ~every 3.5-6 s
REPORT_RADIO = 0x7B         # radio event, byte[9] = signal dBm (receiver links only)

# byte[1] of 0x43 (SDL's ucChargeState)
CHARGE_DISCHARGING = 1
CHARGE_CHARGING = 2
CHARGE_VALIDATING = 3       # checking the charger
CHARGE_DONE = 4             # still on power, battery full
CHARGE_STATES = (CHARGE_DISCHARGING, CHARGE_CHARGING, CHARGE_VALIDATING, CHARGE_DONE)


@dataclass(frozen=True)
class BatteryStatus:
    charge_state: int
    level: int              # %

    @property
    def on_power(self):
        return self.charge_state != CHARGE_DISCHARGING

    @property
    def full(self):
        return self.charge_state == CHARGE_DONE


def parse_battery(data):
    """BatteryStatus from a 0x43 report, or None if it isn't a valid one."""
    if len(data) < 3 or data[0] != REPORT_BATTERY:
        return None
    if data[1] not in CHARGE_STATES or data[2] > 100:
        return None
    return BatteryStatus(data[1], data[2])


def parse_signal(data):
    """Pad <-> receiver signal in dBm from a 0x7b report, or None.

    Range test from the reference project: -20 at the puck (the ceiling)
    down to about -80 at the far end of a house; 0 means no reading.
    """
    if len(data) < 10 or data[0] != REPORT_RADIO or not data[9]:
        return None
    dbm = data[9] - 256 if data[9] > 127 else data[9]
    return dbm if -110 <= dbm <= -5 else None


def signal_bars(dbm):
    """1-4 bars, thresholds from the reference widget."""
    if dbm is None:
        return 0
    if dbm >= -55:
        return 4
    if dbm >= -65:
        return 3
    if dbm >= -75:
        return 2
    return 1


# Dock query: SET feature report 2 with command 0xB4, then GET it back.
# Answer 02 b4 01 <state>: 2 = a pad sits on the dock, 1 = it doesn't.
# Feature report 2 is a buffer shared with Steam, so an answer to someone
# else's command must be ignored.
DOCK_FEATURE_ID = 0x02
DOCK_COMMAND = 0xB4
DOCK_QUERY = bytes([DOCK_FEATURE_ID, DOCK_COMMAND]) + bytes(62)


def parse_dock_answer(answer):
    """True/False = pad on/off the dock, None = not an answer to our query."""
    if len(answer) < 4 or answer[0] != DOCK_FEATURE_ID or answer[1] != DOCK_COMMAND:
        return None
    return answer[3] == 2


# Rumble, output report 0x80: id, type u8, intensity u16, left speed u16,
# left gain s8, right speed u16, right gain s8. The pad stops on its own after
# ~50 ms, so it has to be resent every ~40 ms.
_RUMBLE = struct.Struct("<BBHHbHb")
RUMBLE_PERIOD = 0.04


def rumble(speed):
    return _RUMBLE.pack(0x80, 0, 0, speed, 0, speed, 0)


# Tone on a haptic actuator, output report 0x83: id, side, gain dB, frequency Hz,
# duration ms, LFO Hz, LFO depth. The actuators are loudest around 1.3 kHz.
_TONE = struct.Struct("<BBbHHHB")
TONE_GAIN, TONE_LFO, TONE_DEPTH = 60, 31, 20


def tone(side, freq, ms):
    return _TONE.pack(0x83, side, TONE_GAIN, freq, ms, TONE_LFO, TONE_DEPTH)


# "Find controller": strong pulses, (speed, seconds)
FIND_PATTERN = [(65535, 0.3), (0, 0.2)] * 6

C6, E6, F6, G6, A6 = 1047, 1319, 1397, 1568, 1760
MELODIES = {   # (Hz, ms), 0 Hz = rest
    "ticktock": [(E6, 40), (0, 460), (C6, 40), (0, 460)] * 3,
    "bird":     [(G6, 50), (A6, 50), (G6, 50), (0, 150)] * 3,
    "ringing":  ([(E6, 40), (G6, 40)] * 10 + [(0, 400)]) * 2,
    "sos":      [(E6, 100), (0, 100)] * 3 + [(0, 200)] + [(E6, 300), (0, 100)] * 3 + [(0, 200)]
                + [(E6, 100), (0, 100)] * 3,
    "alarm":    [(E6, 120), (G6, 120)] * 4,
}
