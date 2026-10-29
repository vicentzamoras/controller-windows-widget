"""Flyout panel shown on left click: the controller, its level, link, signal and dock.

A dark card in the style of the reference Plasma widget, with its icons
(assets/: alpha masks rasterized from its SVGs by tools/import_icons.py),
tinted here. Tkinter on the main thread. Shapes and icons are composited with
Pillow (Tk's canvas has no antialiasing) into one background image; text
stays on the canvas so it keeps ClearType. Other threads talk to it only
through `call`.
"""
import ctypes
import functools
import queue
import time
import tkinter as tk
from ctypes import wintypes
from pathlib import Path
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from . import config, text
from . import protocol as p

W, H = 340, 382             # card size in px at 96 dpi; everything below is in these units
PAD = 16
SS = 4                      # supersampling for shapes and icons
MARGIN = 12                 # gap to the taskbar and the screen edge
POLL_MS = 100               # cross-thread calls and the "did we lose the foreground" check
REOPEN_GUARD = 0.4          # s: a tray click that just closed the panel must not reopen it

HEAD_Y = 25                 # centre of the title row
MORE = (W - PAD - 28, 11, W - PAD, 39)          # "..." button
ART = (PAD, 50, 128, 96)                        # controller illustration: x, y, w, h (120:90)
BASELINE = 196              # big number
LINK_ICON = (196, 150, 48)                      # x, y, size
LINE1_Y, LINE2_Y = 218, 240
BATTERY = (W - PAD - 52, 58, W - PAD, 250)      # body; the nub sits on top
TILES_Y, TILE_H, TILE_GAP = 266, 52, 8
TILE_W = (136, 100, 56)     # connection, signal, dock
FIND = (PAD, 330, W - PAD, 366)

PAL = {
    "bg": "#1E2124", "border": "#383D43", "tile": "#272B30", "tile_border": "#32373D",
    "text": "#FCFCFC", "text2": "#C9CDD2", "text3": "#8B9198",
    "outline": "#5A6068", "track": "#3A3F45", "art_fill": "#2C3035",
    "btn": "#30353B", "btn_hover": "#3A4047", "btn_border": "#41474E", "disabled_text": "#61676E",
}
# Colour of the battery fill, like the controller's LED: how it is linked, or why it needs attention
STATE = {"puck": "#FCFCFC", "bluetooth": "#3DAEE9", "usb": "#3EC47A", "dock": "#FF9A3C",
         "low": "#ED4C4C", "off": "#5A6068"}

ASSETS = Path(__file__).with_name("assets")

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUNDSMALL = 3
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


class TPMPARAMS(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("rcExclude", wintypes.RECT)]


user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]
user32.CreatePopupMenu.restype = wintypes.HMENU
user32.AppendMenuW.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.TrackPopupMenuEx.argtypes = [wintypes.HMENU, wintypes.UINT, ctypes.c_int, ctypes.c_int,
                                    wintypes.HWND, ctypes.POINTER(TPMPARAMS)]
user32.DestroyMenu.argtypes = [wintypes.HMENU]

MF_GRAYED, MF_CHECKED, MF_POPUP, MF_SEPARATOR = 0x1, 0x8, 0x10, 0x800
TPM_RIGHTALIGN, TPM_VERTICAL, TPM_RETURNCMD = 0x8, 0x40, 0x100


def popup_menu(owner, entries, x, y, exclude):
    """Shows a native menu with its top-right corner at (x, y), keeping clear
    of `exclude` (a RECT), and runs the chosen entry's action.

    Native like pystray's, so it takes the same dark/light menu theme; Tk draws
    its own menus and ignores it. Entries: None (separator) or
    (label, action or list of entries, checked, enabled).
    """
    actions = []

    def build(items):
        menu = user32.CreatePopupMenu()
        for item in items:
            if item is None:
                user32.AppendMenuW(menu, MF_SEPARATOR, 0, None)
                continue
            label, target, checked, enabled = item
            flags = (MF_CHECKED if checked else 0) | (0 if enabled else MF_GRAYED)
            if isinstance(target, list):
                user32.AppendMenuW(menu, flags | MF_POPUP, build(target), label)
            else:
                actions.append(target)
                user32.AppendMenuW(menu, flags, len(actions), label)
        return menu

    menu = build(entries)
    params = TPMPARAMS(ctypes.sizeof(TPMPARAMS), exclude)
    try:
        cmd = user32.TrackPopupMenuEx(menu, TPM_RETURNCMD | TPM_RIGHTALIGN | TPM_VERTICAL,
                                      x, y, owner, ctypes.byref(params))
    finally:
        user32.DestroyMenu(menu)    # submenus too
    if cmd:
        actions[cmd - 1]()


# --- what to show (pure, tested) ------------------------------------------------

def state_role(st, low_threshold):
    """Key of STATE for the battery fill, the status dot and the big number."""
    if not st.connected:
        return "dock" if st.docked else "off"
    if not st.charging and 0 <= st.battery_pct <= low_threshold:
        return "low"
    return {"usb": "usb", "bluetooth": "bluetooth"}.get(st.connection, "puck")


def link_icon(st):
    """Asset showing how the pad is linked, or None."""
    if not st.connected:
        return "puck" if st.docked else None
    if st.connection == "receiver":
        return "steam-machine" if st.internal else "puck"
    return {"bluetooth": "bluetooth", "usb": "usb-c"}.get(st.connection)


def charging(st):
    """Bolt on the battery: charging awake, or switched off on the dock."""
    return not st.charged and (st.charging or (st.docked and not st.connected))


def ink_on(color):
    """Dark ink on a light fill, white on a dark one (as the reference widget's bolt)."""
    r, g, b = (int(color[i:i + 2], 16) / 255 for i in (1, 3, 5))
    return "#23262A" if 0.299 * r + 0.587 * g + 0.114 * b > 0.6 else "#FCFCFC"


# --- drawing helpers --------------------------------------------------------------

@functools.cache
def _mask(name):
    with Image.open(ASSETS / f"{name}.png") as im:
        return im.convert("L")


def _family(*names):
    have = set(tkfont.families())
    return next((n for n in names if n in have), "Segoe UI")


class Layer:
    """A supersampled RGBA image addressed in card units."""

    def __init__(self, w, h, scale, fill=(0, 0, 0, 0)):
        self.k = scale * SS
        self.img = Image.new("RGBA", (round(w * self.k), round(h * self.k)), fill)
        self.draw = ImageDraw.Draw(self.img)

    def r(self, *v):
        return [x * self.k for x in v]

    def box(self, x0, y0, x1, y1, radius, fill, outline=None, width=1):
        self.draw.rounded_rectangle(self.r(x0, y0, x1, y1), radius=radius * self.k, fill=fill,
                                    outline=outline, width=round(width * self.k) if outline else 0)

    def icon(self, name, x, y, w, h, color):
        m = _mask(name).resize((round(w * self.k), round(h * self.k)), Image.LANCZOS)
        ink = Image.new("RGBA", m.size, color)
        ink.putalpha(m)
        self.img.alpha_composite(ink, (round(x * self.k), round(y * self.k)))

    def photo(self):
        size = (round(self.img.width / SS), round(self.img.height / SS))
        return ImageTk.PhotoImage(self.img.resize(size, Image.LANCZOS))


# --- the window -----------------------------------------------------------------

class Panel:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.title("SC2Tray")
        self.s = self.root.winfo_fpixels("1i") / 96
        self.canvas = tk.Canvas(self.root, width=self.u(W), height=self.u(H), highlightthickness=0, bd=0,
                                bg=PAL["bg"])
        self.canvas.pack()
        self.visible = False
        self._active = False        # has had the foreground since it was shown
        self._hidden_at = 0
        self._menu_open = False
        self._images = {}           # Tk keeps no reference of its own
        self._calls = queue.Queue()
        self._fonts()
        self.root.bind("<Escape>", lambda e: self.hide())
        self.root.after(POLL_MS, self._pump)

    def u(self, v):
        return round(v * self.s)

    def _fonts(self):
        text_f = _family("Segoe UI Variable Text")
        semi = _family("Segoe UI Variable Text Semibold", "Segoe UI Semibold")
        display = _family("Segoe UI Variable Display Semib", "Segoe UI Semibold")
        px = lambda family, size: tkfont.Font(family=family, size=-self.u(size))
        self.f_title = px(semi, 14)
        self.f_label = px(semi, 10)
        self.f_small = px(text_f, 12)
        self.f_body = px(text_f, 13)
        self.f_strong = px(semi, 13)
        self.f_number = px(display, 44)
        self.f_unit = px(text_f, 20)

    # --- threading -------------------------------------------------------

    def call(self, fn, *args):
        """Runs fn on the Tk thread (safe from any thread)."""
        self._calls.put((fn, args))

    def _pump(self):
        while True:
            try:
                fn, args = self._calls.get_nowait()
            except queue.Empty:
                break
            fn(*args)
        if self.visible and not self._menu_open:
            # Close on click-away; only once it has had the foreground, in case Windows refused it
            if user32.GetForegroundWindow() == self.hwnd:
                self._active = True
            elif self._active:
                self.hide()
        self.root.after(POLL_MS, self._pump)

    def mainloop(self):
        self.root.mainloop()

    def quit(self):
        self.root.quit()

    # --- show / hide -----------------------------------------------------

    @property
    def hwnd(self):
        return int(self.root.wm_frame(), 16)

    def toggle(self):
        if self.visible:
            self.hide()
        elif time.monotonic() - self._hidden_at > REOPEN_GUARD:
            self.show()

    def show(self):
        self.render()
        x, y = self._position()
        self.root.geometry(f"{self.u(W)}x{self.u(H)}+{x}+{y}")
        self.root.deiconify()
        self.root.update_idletasks()
        self._decorate()
        self.root.lift()
        self.root.focus_force()
        user32.SetForegroundWindow(self.hwnd)
        self.visible = True
        self._active = False

    def hide(self):
        if self.visible:
            self.visible = False
            self._hidden_at = time.monotonic()
            self.root.withdraw()
            self.canvas.delete("all")
            self._images.clear()    # nothing of the card stays in memory while hidden

    def _position(self):
        """Bottom-right of the work area of the screen under the cursor (where the tray was clicked)."""
        pt = wintypes.POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        info = MONITORINFO(cbSize=ctypes.sizeof(MONITORINFO))
        user32.GetMonitorInfoW(user32.MonitorFromPoint(pt, MONITOR_DEFAULTTONEAREST), ctypes.byref(info))
        work, mon, m = info.rcWork, info.rcMonitor, self.u(MARGIN)
        x = work.left + m if work.left > mon.left else work.right - self.u(W) - m
        y = work.top + m if work.top > mon.top else work.bottom - self.u(H) - m
        return x, y

    def _decorate(self):
        """Windows 11's small corner radius and a hairline border (DWM keeps the shadow)."""
        border = int(PAL["border"][1:], 16)
        colorref = ctypes.c_uint((border & 0xFF) << 16 | (border & 0xFF00) | border >> 16)
        corner = ctypes.c_int(DWMWCP_ROUNDSMALL)
        try:
            dwmapi.DwmSetWindowAttribute(self.hwnd, DWMWA_WINDOW_CORNER_PREFERENCE, ctypes.byref(corner), 4)
            dwmapi.DwmSetWindowAttribute(self.hwnd, DWMWA_BORDER_COLOR, ctypes.byref(colorref), 4)
        except OSError:
            pass

    # --- drawing ---------------------------------------------------------

    def refresh(self):
        if self.visible:
            self.render()

    def render(self):
        app, c, u = self.app, self.canvas, self.u
        st = app.state
        low = app.cfg["low_threshold"]
        role = state_role(st, low)
        color = STATE[role]
        bars = p.signal_bars(st.signal_dbm) if st.signal_dbm is not None else 0

        c.delete("all")
        c.create_image(0, 0, image=self._background(st, role, bars), anchor="nw")

        c.create_text(u(PAD), u(HEAD_Y), text="Steam Controller 2", font=self.f_title, fill=PAL["text"], anchor="w")

        number = str(st.battery_pct) if st.battery_pct >= 0 else "—"
        num_color = STATE["low"] if role == "low" else PAL["text3"] if role == "off" else PAL["text"]
        c.create_text(u(PAD), u(BASELINE) - self.f_number.metrics("ascent"), text=number, font=self.f_number,
                      fill=num_color, anchor="nw")
        if st.battery_pct >= 0:
            c.create_text(u(PAD) + self.f_number.measure(number) + u(3), u(BASELINE) - self.f_unit.metrics("ascent"),
                          text="%", font=self.f_unit, fill=PAL["text2"], anchor="nw")

        c.create_text(u(PAD + 18), u(LINE1_Y), text=text.headline(st, role == "low"), font=self.f_strong,
                      fill=PAL["text3"] if role == "off" else color, anchor="w")
        detail = text.detail(st)
        if detail:
            c.create_text(u(PAD + 18), u(LINE2_Y), text=detail[1], font=self.f_body, fill=PAL["text3"], anchor="w")

        # Tiles: caption, then the value right of its icon (drawn in _background)
        tiles = [("CONEXIÓN", text.link(st), 20 if link_icon(st) else 0), ("SEÑAL", text.signal(st), 21),
                 ("DOCK", text.dock(st), 15 if st.docked else 0)]
        x = PAD
        for (label, value, indent), w in zip(tiles, TILE_W):
            c.create_text(u(x + 10), u(TILES_Y + 16), text=label, font=self.f_label, fill=PAL["text3"], anchor="w")
            muted = value in ("—", "Sin conexión", "No")
            c.create_text(u(x + 10 + indent), u(TILES_Y + 36), text=value, font=self.f_strong, anchor="w",
                          fill=PAL["text3"] if muted else PAL["text"])
            x += w + TILE_GAP

        self._buttons(app.monitor.live_path is not None)

    def _background(self, st, role, bars):
        L = Layer(W, H, self.s, PAL["bg"])
        color = STATE[role]

        # Controller illustration: body fill under the line art
        L.icon("steam-controller-body", *ART, PAL["art_fill"])
        L.icon("steam-controller-lines", *ART, PAL["text"] if st.connected else PAL["text3"])

        # How it is linked, next to the number
        icon = link_icon(st)
        if icon:
            x, y, size = LINK_ICON
            L.icon(icon, x, y, size, size, PAL["text2"])

        # Status lines: dot or bolt in the state colour, then hourglass or clock
        dot = PAL["text3"] if role == "off" else color
        if charging(st):
            L.icon("bolt", PAD, LINE1_Y - 7, 14, 14, dot)
        else:
            L.draw.ellipse(L.r(PAD + 3, LINE1_Y - 4, PAD + 11, LINE1_Y + 4), fill=dot)
        detail = text.detail(st)
        if detail:
            L.icon(detail[0], PAD + 1, LINE2_Y - 6, 12, 12, PAL["text3"])

        self._battery(L, st, role)

        # Tiles: connection, signal, dock
        x = PAD
        for i, w in enumerate(TILE_W):
            L.box(x, TILES_Y, x + w, TILES_Y + TILE_H, 3, PAL["tile"], PAL["tile_border"])
            vy = TILES_Y + 36
            if i == 0 and icon:
                L.icon(icon, x + 10, vy - 8, 16, 16, PAL["text2"])
            elif i == 1:
                for b in range(4):     # rising bars, the weakest level in red
                    h = 4 + 3 * b
                    lit = bars > b
                    ink = (STATE["low"] if bars == 1 else PAL["text"]) if lit else PAL["track"]
                    L.box(x + 10 + 4.5 * b, vy + 6 - h, x + 13 + 4.5 * b, vy + 6, 0.8, ink)
            elif i == 2 and st.docked:
                L.icon("bolt", x + 8, vy - 6, 12, 12, color if charging(st) else PAL["text2"])
            x += w + TILE_GAP

        photo = L.photo()
        self._images["bg"] = photo
        return photo

    def _battery(self, L, st, role):
        x0, y0, x1, y1 = BATTERY
        cx = (x0 + x1) / 2
        L.box(cx - 11, y0 - 7, cx + 11, y0 - 2, 1.5, PAL["outline"])                 # nub
        L.box(x0, y0, x1, y1, 5, None, PAL["outline"], 2)                             # body
        inset = 5
        full = (y1 - y0) - 2 * inset
        top = y1 - inset - full * max(0, min(100, st.battery_pct)) / 100
        if st.battery_pct > 0:
            L.box(x0 + inset, top, x1 - inset, y1 - inset, 2.5, STATE[role])
        if charging(st):
            mid = (y0 + y1) / 2
            ink = ink_on(STATE[role]) if top < mid - 10 else PAL["text"]
            L.icon("bolt", cx - 10, mid - 10, 20, 20, ink)

    # --- buttons ---------------------------------------------------------

    def _button(self, w, h, fill, outline, draw_glyph, key):
        L = Layer(w, h, self.s, PAL["bg"])
        L.box(0, 0, w - 1 / L.k, h - 1 / L.k, 3, fill, outline)
        draw_glyph(L)
        photo = L.photo()
        self._images[key] = photo
        return photo

    def _buttons(self, awake):
        c, u = self.canvas, self.u
        fx0, fy0, fx1, fy1 = FIND
        fw, fh = fx1 - fx0, fy1 - fy0
        label = "Buscar mando"
        gx = fw / 2 - (16 + 8 + self.f_strong.measure(label) / self.s) / 2
        ink = PAL["text"] if awake else PAL["disabled_text"]
        locate = lambda L: L.icon("locate", gx, fh / 2 - 8, 16, 16, ink)
        if awake:
            find_n = self._button(fw, fh, PAL["btn"], PAL["btn_border"], locate, "find")
            find_h = self._button(fw, fh, PAL["btn_hover"], PAL["btn_border"], locate, "find_hover")
        else:
            find_n = find_h = self._button(fw, fh, PAL["tile"], PAL["tile_border"], locate, "find")
        find = c.create_image(u(fx0), u(fy0), image=find_n, anchor="nw", tags=("find",))
        c.create_text(u(fx0 + gx + 24), u(fy0 + fh / 2), text=label, font=self.f_strong, anchor="w",
                      fill=ink, tags=("find",))

        mx0, my0, mx1, my1 = MORE
        mw, mh = mx1 - mx0, my1 - my0

        def dots(L):
            for dx in (-6, 0, 6):
                L.draw.ellipse(L.r(mw / 2 + dx - 1.3, mh / 2 - 1.3, mw / 2 + dx + 1.3, mh / 2 + 1.3), fill=PAL["text2"])

        more_n = self._button(mw, mh, PAL["bg"], None, dots, "more")
        more_h = self._button(mw, mh, PAL["btn_hover"], None, dots, "more_hover")
        more = c.create_image(u(mx0), u(my0), image=more_n, anchor="nw", tags=("more",))

        for tag, item, n, h, action in (("find", find, find_n, find_h, self._find if awake else None),
                                        ("more", more, more_n, more_h, self._more)):
            if action is None:
                continue
            c.tag_bind(tag, "<Enter>", lambda e, i=item, img=h: (c.itemconfigure(i, image=img), c.config(cursor="hand2")))
            c.tag_bind(tag, "<Leave>", lambda e, i=item, img=n: (c.itemconfigure(i, image=img), c.config(cursor="")))
            c.tag_bind(tag, "<ButtonRelease-1>", lambda e, a=action: a())

    def _find(self):
        self.app.find(None)

    def _more(self):
        app, cfg = self.app, self.app.cfg
        awake = app.monitor.live_path is not None
        tunes = [(label, lambda n=name: app.find(n), False, True) for name, label in app.MELODIES]
        entries = [("Buscar con melodía", tunes, False, awake), None,
                   *[(label, lambda k=key: cfg.toggle(k), cfg[key], True) for key, label in app.toggles()],
                   ("Iniciar con Windows", app.toggle_autostart, config.autostart_enabled(), True),
                   None,
                   ("Salir", app.quit, False, True)]
        mx0, my0, mx1, my1 = (self.u(v) for v in MORE)
        x0, y0 = self.root.winfo_rootx(), self.root.winfo_rooty()
        button = wintypes.RECT(x0 + mx0, y0 + my0, x0 + mx1, y0 + my1)
        self._menu_open = True
        try:
            popup_menu(self.hwnd, entries, button.right, button.bottom + self.u(4), button)
        finally:
            self._menu_open = False
            if self.visible:
                user32.SetForegroundWindow(self.hwnd)
