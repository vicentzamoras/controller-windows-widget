"""Flyout panel shown on left click: level, charge, link, signal and the 24 h history.

Tkinter, on the main thread. Shapes are drawn with Pillow (Tk's canvas has no
antialiasing) into one background image; text stays on the canvas so it keeps
ClearType. Other threads talk to it only through `call`.
"""
import ctypes
import queue
import time
import tkinter as tk
from ctypes import wintypes
from tkinter import font as tkfont

from PIL import Image, ImageDraw, ImageTk

from . import config, icons, text
from . import protocol as p
from .state import HISTORY_SPAN

W, H = 360, 500             # card size in px at 96 dpi; everything below is in these units
PAD = 20
SS = 4                      # supersampling for the shapes
MARGIN = 12                 # gap to the taskbar and the screen edge
POLL_MS = 100               # cross-thread calls and the "did we lose the foreground" check
REOPEN_GUARD = 0.4          # s: a tray click that just closed the panel must not reopen it
CHART_MIN_SPAN = 1800       # s of history before the chart is drawn (less is a sliver at the edge)

HEAD_Y = 33                 # centre of the title row
BASELINE = 110              # baseline of the big number
BAR_Y = 128                 # level bar, 10 tall
STATUS_Y = 158
ROWS_Y = 188                # three 40 px rows
CHART_HEAD_Y = 336
CHART_Y = 352               # chart, 64 tall: lines at +4, +32, +60
BTN_Y = 436                 # buttons, 44 tall
MORE_X = W - PAD - 44

DARK = {
    "bg": "#202020", "border": "#3F3F3F", "text": "#FFFFFF", "text2": "#E0E0E0", "text3": "#A8A8A8",
    "unit": "#C5C5C5", "line": "#333333", "track": "#3A3A3A", "chip": "#2D2D2D", "chip_border": "#454545",
    "bar_off": "#4A4A4A", "neutral": "#E6E6E6", "off": "#8A8A8A", "off_num": "#9E9E9E",
    "accent": "#4CC2FF", "accent_hover": "#47B1E8", "on_accent": "#0B1A24", "low": "#FFB454",
    "btn": "#2D2D2D", "btn_hover": "#383838", "disabled": "#333333", "disabled_text": "#7A7A7A",
}
LIGHT = {
    "bg": "#F9F9F9", "border": "#D6D6D6", "text": "#1A1A1A", "text2": "#3B3B3B", "text3": "#616161",
    "unit": "#5C5C5C", "line": "#E5E5E5", "track": "#E0E0E0", "chip": "#FFFFFF", "chip_border": "#D6D6D6",
    "bar_off": "#C8C8C8", "neutral": "#3B3B3B", "off": "#9A9A9A", "off_num": "#8A8A8A",
    "accent": "#005FB8", "accent_hover": "#1A6FC0", "on_accent": "#FFFFFF", "low": "#B35900",
    "btn": "#FFFFFF", "btn_hover": "#F3F3F3", "disabled": "#E5E5E5", "disabled_text": "#9A9A9A",
}

user32 = ctypes.windll.user32
dwmapi = ctypes.windll.dwmapi
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWCP_ROUND = 2
MONITOR_DEFAULTTONEAREST = 2


class MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]


user32.MonitorFromPoint.argtypes = [wintypes.POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HMONITOR
user32.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MONITORINFO)]


# --- what to show (pure, tested) ------------------------------------------------

def tone(st, low_threshold):
    """Colour role of the number, bar and chart."""
    kind = icons.kind_of(st, low_threshold)
    if kind == icons.OFF:
        return "off"
    if kind == icons.LOW:
        return "low"
    return "accent" if kind in (icons.CHARGING, icons.FULL, icons.DOCK) else "neutral"


def chart_points(history, now, current=None):
    """History as (x, y) in 0..1 (x: 24 h ago -> now, y: 0 % -> 100 %), oldest first.

    `current` (the live level) extends the line to "now". Empty while there is
    too little history to draw.
    """
    pts = [((t - now) / HISTORY_SPAN + 1, pct / 100) for t, pct, _ in history if now - t <= HISTORY_SPAN]
    if current is not None and current >= 0:
        pts.append((1.0, current / 100))
    if len(pts) < 2 or (pts[-1][0] - pts[0][0]) * HISTORY_SPAN < CHART_MIN_SPAN:
        return []
    return pts


# --- the window -----------------------------------------------------------------

def _family(*names):
    have = set(tkfont.families())
    return next((n for n in names if n in have), "Segoe UI")


class Panel:
    def __init__(self, app):
        self.app = app
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.title("SC2Tray")
        self.s = self.root.winfo_fpixels("1i") / 96
        self.canvas = tk.Canvas(self.root, width=self.u(W), height=self.u(H), highlightthickness=0, bd=0)
        self.canvas.pack()
        self.pal = DARK
        self.visible = False
        self._active = False        # has had the foreground since it was shown
        self._hidden_at = 0
        self._menu_open = False
        self._images = {}
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
        self.f_title = px(semi, 16)
        self.f_small = px(text_f, 12)
        self.f_body = px(text_f, 14)
        self.f_button = px(semi, 14)
        self.f_number = px(display, 48)
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
        self.pal = LIGHT if config.apps_use_light() else DARK
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
        """Windows 11 rounded corners and a hairline border."""
        border = int(self.pal["border"][1:], 16)
        colorref = ctypes.c_uint((border & 0xFF) << 16 | (border & 0xFF00) | border >> 16)
        corner = ctypes.c_int(DWMWCP_ROUND)
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
        app, pal, c = self.app, self.pal, self.canvas
        st = app.state
        low = app.cfg["low_threshold"]
        role = tone(st, low)
        color = pal[role]
        awake = app.monitor.live_path is not None
        chip = text.chip(st)
        signal = text.signal(st)
        bars = p.signal_bars(st.signal_dbm) if st.signal_dbm is not None else 0
        pts = chart_points(app.monitor.history(), time.time(), st.battery_pct if st.connected else None)

        c.delete("all")
        bg = self._background(pal, color, st.battery_pct, chip, signal, bars, pts)
        c.create_image(0, 0, image=bg, anchor="nw")
        u = self.u

        c.create_text(u(PAD), u(HEAD_Y), text="Steam Controller 2", font=self.f_title, fill=pal["text"], anchor="w")
        c.create_text(u(W - PAD - 11), u(HEAD_Y), text=chip, font=self.f_small, fill=pal["text2"], anchor="e")

        number = str(st.battery_pct) if st.battery_pct >= 0 else "—"
        num_color = pal["off_num"] if role == "off" else pal["text"] if role == "neutral" else color
        top = u(BASELINE) - self.f_number.metrics("ascent")
        c.create_text(u(PAD), top, text=number, font=self.f_number, fill=num_color, anchor="nw")
        c.create_text(u(PAD) + self.f_number.measure(number) + u(10), u(BASELINE) - self.f_unit.metrics("ascent"),
                      text="%", font=self.f_unit, fill=pal["unit"], anchor="nw")
        low_now = st.connected and 0 <= st.battery_pct <= low
        c.create_text(u(PAD), u(STATUS_Y), text=text.panel_status(st, low_now), font=self.f_body,
                      fill=pal["text2"], anchor="w")

        rows = [("Conexión", text.link(st)), ("Señal", signal), ("Último dato", st.last_seen or "—")]
        for i, (label, value) in enumerate(rows):
            y = u(ROWS_Y + 40 * i + 20)
            c.create_text(u(PAD), y, text=label, font=self.f_body, fill=pal["text3"], anchor="w")
            c.create_text(u(W - PAD), y, text=value, font=self.f_body, fill=pal["text"], anchor="e")

        c.create_text(u(PAD), u(CHART_HEAD_Y), text="Últimas 24 h", font=self.f_small, fill=pal["text3"], anchor="w")
        c.create_text(u(W - PAD), u(CHART_HEAD_Y), text="ahora", font=self.f_small, fill=pal["text3"], anchor="e")
        if not pts:
            c.create_text(u(W / 2), u(CHART_Y + 32), text="Recopilando historial…", font=self.f_small,
                          fill=pal["text3"])

        self._buttons(awake)

    def _layer(self):
        s = self.s * SS
        img = Image.new("RGBA", (round(W * s), round(H * s)), (0, 0, 0, 0))
        return img, ImageDraw.Draw(img), (lambda *v: [x * s for x in v])

    def _finish(self, img, key):
        photo = ImageTk.PhotoImage(img.resize((self.u(img.width / self.s / SS), self.u(img.height / self.s / SS)),
                                              Image.LANCZOS))
        self._images[key] = photo   # Tk keeps no reference of its own
        return photo

    def _background(self, pal, color, pct, chip, signal, bars, pts):
        s = self.s * SS
        img, d, r = self._layer()
        d.rectangle(r(0, 0, W, H), fill=pal["bg"])
        line = max(1, round(s))

        # Connection chip, right of the title
        cw = (self.f_small.measure(chip) / self.s) + 10 + 12 + 6 + 10
        x1, x0 = W - PAD, W - PAD - cw
        d.rounded_rectangle(r(x0, HEAD_Y - 12, x1, HEAD_Y + 12), radius=12 * s, fill=pal["chip"],
                            outline=pal["chip_border"], width=line)
        cx = x0 + 10 + 6
        d.ellipse(r(cx - 4.7, HEAD_Y - 4.7, cx + 4.7, HEAD_Y + 4.7), outline=pal["text2"], width=round(1.5 * s))
        d.ellipse(r(cx - 1.5, HEAD_Y - 1.5, cx + 1.5, HEAD_Y + 1.5), fill=pal["text2"])

        # Level bar
        d.rounded_rectangle(r(PAD, BAR_Y, W - PAD, BAR_Y + 10), radius=5 * s, fill=pal["track"])
        if pct > 0:
            d.rounded_rectangle(r(PAD, BAR_Y, PAD + max(10, (W - 2 * PAD) * pct / 100), BAR_Y + 10),
                                radius=5 * s, fill=color)

        # Row separators
        for i in range(4):
            y = ROWS_Y + 40 * i
            d.rectangle([PAD * s, y * s, (W - PAD) * s, y * s + line - 1], fill=pal["line"])

        # Signal bars, left of the dBm text
        bx = W - PAD - self.f_body.measure(signal) / self.s - 10 - 22
        by = ROWS_Y + 40 + 20 - 7
        for i in range(4):
            h = 4 + 3 * i
            d.rounded_rectangle(r(bx + 6 * i, by + 14 - h, bx + 6 * i + 4, by + 14), radius=1 * s,
                                fill=pal["text"] if bars > i else pal["bar_off"])

        # 24 h chart
        for dy in (4, 32, 60):
            d.rectangle([PAD * s, (CHART_Y + dy) * s, (W - PAD) * s, (CHART_Y + dy) * s + line - 1], fill=pal["line"])
        if pts:
            xy = [((PAD + x * (W - 2 * PAD)) * s, (CHART_Y + 60 - y * 56) * s) for x, y in pts]
            area = Image.new("RGBA", img.size, (0, 0, 0, 0))
            rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
            ImageDraw.Draw(area).polygon(xy + [(xy[-1][0], (CHART_Y + 64) * s), (xy[0][0], (CHART_Y + 64) * s)],
                                         fill=rgb + (41,))
            img.alpha_composite(area)
            d.line(xy, fill=color, width=round(2 * s), joint="curve")
            for x, y in (xy[0], xy[-1]):
                d.ellipse([x - s, y - s, x + s, y + s], fill=color)

        return self._finish(img, "bg")

    # --- buttons ---------------------------------------------------------

    def _button_image(self, w, fill, outline, glyph, glyph_color, key):
        s = self.s * SS
        img = Image.new("RGBA", (round(w * s), round(44 * s)), self.pal["bg"])
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=6 * s, fill=fill,
                            outline=outline, width=max(1, round(s)) if outline else 0)
        if glyph == "more":
            for gx in (-7, 0, 7):
                cx, cy = (w / 2 + gx) * s, 22 * s
                d.ellipse([cx - 1.4 * s, cy - 1.4 * s, cx + 1.4 * s, cy + 1.4 * s], fill=glyph_color)
        else:   # magnifier, left of the label (gx = its centre)
            gx = glyph
            d.ellipse([(gx - 5) * s, (22 - 5) * s, (gx + 3) * s, (22 + 3) * s], outline=glyph_color, width=round(1.4 * s))
            d.line([(gx + 2.3) * s, (22 + 2.3) * s, (gx + 5.5) * s, (22 + 5.5) * s], fill=glyph_color, width=round(1.6 * s))
        return self._finish(img, key)

    def _buttons(self, awake):
        pal, c, u = self.pal, self.canvas, self.u
        fw = MORE_X - 8 - PAD
        label = "Buscar mando"
        content = 16 + 8 + self.f_button.measure(label) / self.s
        gx = fw / 2 - content / 2 + 8
        if awake:
            normal = self._button_image(fw, pal["accent"], None, gx, pal["on_accent"], "find")
            hover = self._button_image(fw, pal["accent_hover"], None, gx, pal["on_accent"], "find_hover")
        else:
            normal = hover = self._button_image(fw, pal["disabled"], None, gx, pal["disabled_text"], "find")
        find = c.create_image(u(PAD), u(BTN_Y), image=normal, anchor="nw", tags=("find",))
        c.create_text(u(PAD + gx + 8 + 8), u(BTN_Y + 22), text=label, font=self.f_button, anchor="w",
                      fill=pal["on_accent"] if awake else pal["disabled_text"], tags=("find",))
        more_n = self._button_image(44, pal["btn"], pal["chip_border"], "more", pal["text"], "more")
        more_h = self._button_image(44, pal["btn_hover"], pal["chip_border"], "more", pal["text"], "more_hover")
        more = c.create_image(u(MORE_X), u(BTN_Y), image=more_n, anchor="nw", tags=("more",))

        for tag, item, n, h, action in (("find", find, normal, hover, self._find if awake else None),
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
        m = tk.Menu(self.root, tearoff=0)
        tunes = tk.Menu(m, tearoff=0)
        for name, label in app.MELODIES:
            tunes.add_command(label=label, command=lambda n=name: app.find(n))
        m.add_cascade(label="Buscar con melodía", menu=tunes, state="normal" if awake else "disabled")
        m.add_separator()
        self._vars = []
        for key, label in app.toggles():
            var = tk.BooleanVar(value=cfg[key])
            self._vars.append(var)
            m.add_checkbutton(label=label, variable=var, command=lambda k=key: cfg.toggle(k))
        auto = tk.BooleanVar(value=config.autostart_enabled())
        self._vars.append(auto)
        m.add_checkbutton(label="Iniciar con Windows", variable=auto, command=app.toggle_autostart)
        m.add_separator()
        m.add_command(label="Salir", command=app.quit)
        self._menu_open = True
        try:
            m.tk_popup(self.root.winfo_rootx() + self.u(MORE_X), self.root.winfo_rooty() + self.u(BTN_Y))
        finally:
            m.grab_release()
            self._menu_open = False
            if self.visible:
                user32.SetForegroundWindow(self.hwnd)
