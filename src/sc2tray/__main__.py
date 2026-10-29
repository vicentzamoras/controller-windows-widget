"""Entry point: the tray app, or a headless JSON stream for debugging.

    python -m sc2tray              tray icon
    python -m sc2tray --headless   print every state change as JSON
    python -m sc2tray --find [MELODY]
"""
import argparse
import json
import sys
from dataclasses import asdict

from . import protocol


def headless():
    from .monitor import Monitor

    mon = Monitor(lambda st: print(json.dumps(asdict(st), ensure_ascii=False), flush=True))
    mon.start()
    try:
        while mon.is_alive():
            mon.join(0.5)
    except KeyboardInterrupt:
        mon.stop()


def find(melody):
    from . import device

    coll, dev, _ = device.find_live()
    if dev is None:
        print("no controller is awake", file=sys.stderr)
        return 1
    dev.close()
    device.find_controller(coll.path, protocol.MELODIES.get(melody) if melody else None)
    return 0


def main():
    ap = argparse.ArgumentParser(prog="sc2tray", description="Steam Controller 2 battery in the Windows tray")
    ap.add_argument("--headless", action="store_true", help="print state changes as JSON instead of showing the tray icon")
    ap.add_argument("--find", nargs="?", const="", metavar="MELODY",
                    help=f"make the controller findable (melodies: {', '.join(protocol.MELODIES)})")
    args = ap.parse_args()
    if args.headless:
        if sys.stdout is None:  # windowed exe: nowhere to print
            return 2
        return headless()
    if args.find is not None:
        return find(args.find)
    from .tray import run
    return run()


if __name__ == "__main__":
    sys.exit(main())
