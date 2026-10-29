"""Tray icon, design variant A ("level bar"): a battery outline with a fill bar,
a bolt while charging, a check when full, dimmed when the pad is off.

Drawn on a 16-unit grid so it lands on whole pixels at 16 px (100 % scaling)
and 32 px (200 %), supersampled for anti-aliased edges at other sizes.
"""
from PIL import Image, ImageDraw

SUPERSAMPLE = 8
CLEAR = (0, 0, 0, 0)

DARK = {"fg": "#FFFFFF", "dim": "#9E9E9E", "ghost": "#6E6E6E", "accent": "#4CC2FF", "low": "#FFB454"}
LIGHT = {"fg": "#1A1A1A", "dim": "#6B6B6B", "ghost": "#9A9A9A", "accent": "#005FB8", "low": "#B35900"}

# Geometry in 16 units, boxes as [x0, y0, x1, y1) like pixels
BODY, BODY_R = (1, 4, 14, 12), 2
NUB = (14, 6, 15, 10)
FILL = (3, 6, 12, 10)
BOLT = [(8.4, 1.8), (4.6, 8.6), (7.3, 8.6), (6.4, 14.2), (10.4, 7.2), (7.6, 7.2)]
CHECK = [(5.2, 8.0), (6.9, 9.6), (10.0, 6.4)]
DASH_X = (4, 7, 10)

NORMAL, LOW, CHARGING, FULL, DOCK, OFF = "normal", "low", "charging", "full", "dock", "off"


def kind_of(st, low_threshold):
    if not st.connected:
        return DOCK if st.docked else OFF
    if st.charged:
        return FULL
    if st.charging:
        return CHARGING
    if 0 <= st.battery_pct <= low_threshold:
        return LOW
    return NORMAL


def render(kind, pct, light, size):
    pal = LIGHT if light else DARK
    big = size * SUPERSAMPLE
    k = big / 16
    img = Image.new("RGBA", (big, big), CLEAR)
    d = ImageDraw.Draw(img)

    def box(b):
        return [b[0] * k, b[1] * k, b[2] * k - 1, b[3] * k - 1]

    def pts(ps):
        return [(x * k, y * k) for x, y in ps]

    fg, fill, bolt = pal["fg"], pal["fg"], pal["accent"]
    if kind == LOW:
        fill = pal["low"]
    elif kind in (CHARGING, FULL):
        fill = pal["accent"]
    elif kind == DOCK:
        fg, bolt = pal["dim"], pal["low"]
    elif kind == OFF:
        fg, fill = pal["dim"], pal["ghost"]

    d.rounded_rectangle(box(BODY), radius=BODY_R * k, outline=fg, width=round(k))
    d.rectangle(box(NUB), fill=fg)
    if kind == OFF:                     # dashed outline
        for x in DASH_X:
            d.rectangle(box((x, BODY[1], x + 1, BODY[1] + 1)), fill=CLEAR)
            d.rectangle(box((x, BODY[3] - 1, x + 1, BODY[3])), fill=CLEAR)

    if kind != DOCK and pct >= 0:
        w = max(1, (FILL[2] - FILL[0]) * min(pct, 100) / 100)
        d.rounded_rectangle(box((FILL[0], FILL[1], FILL[0] + w, FILL[3])), radius=0.6 * k, fill=fill)

    if kind in (CHARGING, DOCK):        # bolt, cut out of what lies beneath
        outline = pts(BOLT)
        d.line(outline + outline[:1], fill=CLEAR, width=round(1.2 * k), joint="curve")
        d.polygon(outline, fill=bolt)
    elif kind == FULL:
        d.line(pts(CHECK), fill=CLEAR, width=round(1.3 * k), joint="curve")

    return img.resize((size, size), Image.BOX)
