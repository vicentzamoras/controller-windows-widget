"""Lists the Steam Controller 2 HID collections Windows exposes and samples their reports.

    python tools/hid_probe.py [seconds-per-collection]

For every vendor-defined collection (usage page 0xFF00) it reads for a few
seconds, counts the reports per Report ID and prints the first 0x43 / 0x7b
seen. It then asks the puck's dock interface (MI_06) for its link state
(feature report 2, command 0xB4).
"""
import sys
import time
from collections import Counter

import hid

SC_VID = 0x28DE
SAMPLE_IDS = (0x43, 0x7B)


def fmt(path):
    return path.decode(errors="replace") if isinstance(path, bytes) else str(path)


def list_all():
    devs = hid.enumerate(SC_VID, 0)
    print(f"{len(devs)} collections with VID 28de:\n")
    for d in sorted(devs, key=lambda d: (d["product_id"], d["interface_number"], d["usage_page"], d["usage"])):
        print(f"  pid={d['product_id']:04x} if={d['interface_number']:>2} "
              f"page=0x{d['usage_page']:04x} usage=0x{d['usage']:04x} bus={d.get('bus_type', '?')} "
              f"product={d['product_string']!r}")
        print(f"      {fmt(d['path'])}")
    return devs


def sample(d, seconds):
    dev = hid.device()
    try:
        dev.open_path(d["path"])
    except OSError as e:
        print(f"  if={d['interface_number']}: cannot open ({e})")
        return
    ids, first = Counter(), {}
    end = time.time() + seconds
    try:
        while time.time() < end:
            data = dev.read(64, 200)
            if not data:
                continue
            ids[data[0]] += 1
            if data[0] in SAMPLE_IDS and data[0] not in first:
                first[data[0]] = bytes(data).hex()
    finally:
        dev.close()
    summary = ", ".join(f"0x{k:02x}×{v}" for k, v in sorted(ids.items())) or "silent"
    print(f"  if={d['interface_number']} usage=0x{d['usage']:04x}: {summary}")
    for rid, hx in first.items():
        print(f"      first 0x{rid:02x}: {hx}")


def dock(devs):
    nodes = [d for d in devs if d["product_id"] == 0x1304 and d["interface_number"] == 6]
    if not nodes:
        print("\nno dock interface (MI_06)")
        return
    dev = hid.device()
    try:
        dev.open_path(nodes[0]["path"])
        out = bytes([0x02, 0xB4]) + bytes(62)
        n = dev.send_feature_report(out)
        time.sleep(0.05)
        ans = bytes(dev.get_feature_report(0x02, 65))
        print(f"\ndock: sent {n} bytes, answer {ans[:8].hex()} -> "
              f"{'docked' if len(ans) > 3 and ans[1] == 0xB4 and ans[3] == 2 else 'not docked / other'}")
    except OSError as e:
        print(f"\ndock query failed: {e}")
    finally:
        dev.close()


def main():
    seconds = float(sys.argv[1]) if len(sys.argv) > 1 else 6
    devs = list_all()
    print(f"\nSampling vendor collections for {seconds:g} s each:")
    for d in devs:
        if d["usage_page"] >= 0xFF00:
            sample(d, seconds)
    dock(devs)


if __name__ == "__main__":
    main()
