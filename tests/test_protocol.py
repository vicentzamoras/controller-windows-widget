from sc2tray import protocol as p


def b(hexstr):
    return bytes.fromhex(hexstr)


# Raw reports from the reference project's PROTOCOL_NOTES.md and from a puck on Windows
BATTERY_4 = b("4301046c0e740e000000000000df68")
BATTERY_44 = b("43012ce20e000f000000000000225c")
BATTERY_92_WINDOWS = b("43015cfb0f04100000000000005f62ffc3040000000000000000000000005130fc01eeff12f8f83f")
RADIO_PUCK_WINDOWS = b("7bf501840000000400ec001e0207bbfe6704")


def test_battery_levels():
    assert p.parse_battery(BATTERY_4) == p.BatteryStatus(1, 4)
    assert p.parse_battery(BATTERY_44).level == 44
    assert p.parse_battery(BATTERY_92_WINDOWS).level == 92


def test_charge_states():
    assert not p.parse_battery(BATTERY_4).on_power
    charging = p.parse_battery(b("43023c"))
    assert charging.on_power and not charging.full
    done = p.parse_battery(b("430464"))
    assert done.on_power and done.full


def test_battery_rejects_garbage():
    assert p.parse_battery(b("4300")) is None          # too short
    assert p.parse_battery(b("430550")) is None        # unknown charge state
    assert p.parse_battery(b("4301ff")) is None        # level > 100
    assert p.parse_battery(b("7b0150")) is None        # other report


def test_signal():
    assert p.parse_signal(RADIO_PUCK_WINDOWS) == -20
    assert p.parse_signal(b("7bf801880000000300dd003002")) == -35
    assert p.parse_signal(b("7bf80188000000030000003002")) is None   # 0 = no reading
    assert p.parse_signal(b("7bf8")) is None


def test_signal_bars():
    assert [p.signal_bars(d) for d in (None, -20, -55, -60, -70, -80)] == [0, 4, 4, 3, 2, 1]


def test_dock_answer():
    assert p.parse_dock_answer(b("02b40102")) is True
    assert p.parse_dock_answer(b("02b40101")) is False
    assert p.parse_dock_answer(b("02b50102")) is None   # Steam's command, not ours
    assert len(p.DOCK_QUERY) == 64


def test_output_reports():
    # id, type, intensity u16, left speed u16 + gain, right speed u16 + gain
    assert p.rumble(65535) == b("80" "00" "0000" "ffff00" "ffff00")
    assert p.tone(1, 1319, 40)[:2] == b("8301")
