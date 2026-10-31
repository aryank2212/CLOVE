"""Clove' on-screen cursor: a glowing pointer that glides to things and highlights them.

On a Mac the same frames are shown by helpers/mac_overlay.py (transparent, click-through Cocoa windows).

GNOME on Wayland doesn't let apps draw over other windows, but XWayland windows can: this uses transparent,
click-through, override-redirect X11 windows (the user's own mouse and clicks pass straight through).
It never moves or clicks the real mouse."""
import logging
import math
import queue
import subprocess
import threading
import time

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

log = logging.getLogger("clove.pointer")


def sys_executable() -> str:
    import sys
    return sys.executable
FPS = 50
CYAN = (34, 211, 238)
INK = (8, 12, 28)


def _font(size: int) -> ImageFont.FreeTypeFont:
    import sys
    if sys.platform.startswith("win"):
        for path in ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/calibri.ttf"):
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                pass
    for path in ("/System/Library/Fonts/SFNS.ttf", "/System/Library/Fonts/HelveticaNeue.ttc",
                 "/System/Library/Fonts/Helvetica.ttc"):                               # macOS
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    for q in ("Cantarell:bold", "Inter:bold", "Noto Sans:bold", "DejaVu Sans:bold"):
        try:
            path = subprocess.run(["fc-match", "-f", "%{file}", q], capture_output=True, text=True, timeout=3).stdout
            if path:
                return ImageFont.truetype(path, size)
        except (OSError, subprocess.SubprocessError):
            pass
    return ImageFont.load_default(size)


def _bgra(img: Image.Image, alpha: float = 1.0) -> bytes:
    """RGBA PIL image -> premultiplied BGRA bytes (what a 32-bit X11 ARGB window expects)."""
    a = np.asarray(img, dtype=np.float32)
    a[..., 3] *= alpha
    a[..., :3] *= a[..., 3:4] / 255.0
    return a[..., [2, 1, 0, 3]].astype(np.uint8).tobytes()


class Overlay:
    """One transparent click-through ARGB window."""

    def __init__(self, display, screen, visual, cmap, shape):
        self.d, self.screen, self.visual, self.cmap = display, screen, visual, cmap
        self.win = None
        self.gc = None
        self.geom = (0, 0, 0, 0)
        self.shape = shape

    def show(self, x: int, y: int, w: int, h: int, img: Image.Image, alpha: float = 1.0):
        from Xlib import X
        w, h = max(1, w), max(1, h)
        if self.win is None:
            self.win = self.screen.root.create_window(
                x, y, w, h, 0, 32, X.InputOutput, self.visual.visual_id, background_pixel=0, border_pixel=0,
                colormap=self.cmap, override_redirect=1)
            if self.shape:      # empty input region: every click and hover passes through to what's below
                from Xlib.ext import shape
                self.win.shape_rectangles(shape.SO.Set, shape.SK.Input, 0, 0, 0, [])
            self.gc = self.win.create_gc()
            self.win.map()
            self.geom = (x, y, w, h)
        elif self.geom != (x, y, w, h):
            self.win.configure(x=x, y=y, width=w, height=h)
            self.geom = (x, y, w, h)
        data = _bgra(img, alpha)
        stride = w * 4
        rows_per = max(1, 200_000 // stride)                 # stay under the X request size limit
        for r in range(0, h, rows_per):
            n = min(rows_per, h - r)
            self.win.put_image(self.gc, 0, r, w, n, X.ZPixmap, 32, 0, data[r * stride:(r + n) * stride])
        self.d.flush()

    def hide(self):
        if self.win is not None:
            self.win.unmap()
            self.d.flush()
            self.geom = (0, 0, 0, 0)
            self.win.destroy()
            self.win = self.gc = None

    def raise_(self):
        if self.win is not None:
            self.win.configure(stack_mode=0)       # X.Above
            self.d.flush()


class MacOverlay:
    """The Mac twin of Overlay: one window in the helper process, drawn from the same PIL frames."""

    def __init__(self, helper, wid: str):
        self.p, self.wid = helper, wid
        self.shown = False

    def _send(self, line: str, data: bytes = b""):
        try:
            self.p.stdin.write(line.encode() + b"\n" + data)
            self.p.stdin.flush()
        except (OSError, ValueError):
            pass

    def show(self, x: int, y: int, w: int, h: int, img: Image.Image, alpha: float = 1.0):
        import io
        buf = io.BytesIO()
        img.save(buf, "PNG", compress_level=1)
        data = buf.getvalue()
        self._send(f"show {self.wid} {int(x)} {int(y)} {max(1, w)} {max(1, h)} {alpha:.3f} {len(data)}", data)
        self.shown = True

    def hide(self):
        if self.shown:
            self._send(f"hide {self.wid}")
            self.shown = False

    def raise_(self):
        self._send(f"raise {self.wid}")



class WindowsOverlay:
    """A transparent, click-through, topmost layered window on Windows showing a PIL RGBA image."""

    def __init__(self):
        self.hwnd = None
        self._register()
        self.shown = False

    def _register(self):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        self.user32 = user32
        self.gdi32 = ctypes.windll.gdi32
        # window class
        class WNDCLASSEXW(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT),
                        ("lpfnWndProc", ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)),
                        ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int),
                        ("hInstance", wintypes.HINSTANCE), ("hIcon", wintypes.HICON),
                        ("hCursor", wintypes.HCURSOR), ("hbrBackground", wintypes.HBRUSH),
                        ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR),
                        ("hIconSm", wintypes.HICON)]
        self._wndproc = ctypes.WINFUNCTYPE(wintypes.LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)(self._proc)
        wc = WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(WNDCLASSEXW)
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = kernel32.GetModuleHandleW(None)
        wc.lpszClassName = "CloveOverlay"
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            # maybe already registered
            pass

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == 0x0002:  # WM_DESTROY
            self.user32.PostQuitMessage(0)
            return 0
        return self.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def show(self, x, y, w, h, img, alpha=1.0):
        import ctypes
        from ctypes import wintypes
        user32 = self.user32
        gdi32 = self.gdi32
        w, h = max(1, w), max(1, h)
        if self.hwnd is None:
            WS_EX_LAYERED = 0x00080000
            WS_EX_TOPMOST = 0x00000008
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_TOOLWINDOW = 0x00000080
            WS_EX_NOACTIVATE = 0x08000000
            WS_POPUP = 0x80000000
            hwnd = user32.CreateWindowExW(
                WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE,
                "CloveOverlay", None, WS_POPUP, x, y, w, h, None, None, ctypes.windll.kernel32.GetModuleHandleW(None), None)
            self.hwnd = hwnd
            user32.ShowWindow(hwnd, 4)  # SW_SHOWNOACTIVATE
        else:
            user32.SetWindowPos(self.hwnd, -1, x, y, w, h, 0x0010)  # HWND_TOPMOST, SWP_NOACTIVATE
        # update layered window with image
        self._last_x = x
        self._last_y = y
        self._update(w, h, img, alpha)
        self.shown = True

    def _update(self, w, h, img, alpha):
        import ctypes
        from ctypes import wintypes
        user32 = self.user32
        gdi32 = self.gdi32
        # convert PIL image to 32-bit premul BGRA
        import numpy as np
        im = img.convert("RGBA").resize((w, h))
        arr = np.asarray(im, dtype=np.float32)
        a = arr[..., 3] * float(alpha)
        arr[..., 3] = a
        arr[..., 0] = arr[..., 0] * a / 255.0
        arr[..., 1] = arr[..., 1] * a / 255.0
        arr[..., 2] = arr[..., 2] * a / 255.0
        bgra = arr[..., [2, 1, 0, 3]].astype("uint8")
        # create DIB section
        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [("biSize", wintypes.DWORD), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD),
                        ("biCompression", wintypes.DWORD), ("biSizeImage", wintypes.DWORD),
                        ("biXPelsPerMeter", ctypes.c_long), ("biYPelsPerMeter", ctypes.c_long),
                        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD)]
        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0  # BI_RGB
        bits = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(None, ctypes.byref(bmi), 0, ctypes.byref(bits), None, 0)
        ctypes.memmove(bits.value, bgra.tobytes(), w * h * 4)
        # memory dc
        hdc_screen = user32.GetDC(None)
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        gdi32.SelectObject(hdc_mem, hbmp)
        # blend
        class BLENDFUNCTION(ctypes.Structure):
            _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                        ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]
        blend = BLENDFUNCTION()
        blend.BlendOp = 0  # AC_SRC_OVER
        blend.SourceConstantAlpha = 255
        blend.AlphaFormat = 1  # AC_SRC_ALPHA
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        class SIZE(ctypes.Structure):
            _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]
        pt_src = POINT(0, 0)
        pt_dst = POINT(self._last_x if hasattr(self, "_last_x") else 0, self._last_y if hasattr(self, "_last_y") else 0)
        # need dst pos; store
        size = SIZE(w, h)
        user32.UpdateLayeredWindow(self.hwnd, hdc_screen, None, ctypes.byref(size),
                                 hdc_mem, ctypes.byref(pt_src), 0, ctypes.byref(blend), 2)  # ULW_ALPHA
        gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)

    def hide(self):
        if self.hwnd is not None and self.shown:
            self.user32.ShowWindow(self.hwnd, 0)  # SW_HIDE
            self.shown = False

    def raise_(self):
        if self.hwnd is not None:
            self.user32.SetWindowPos(self.hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)  # SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE... actually includes NOZORDER? no


class Pointer:
    """Thread-owned overlay: point(x, y, label, box) from any thread."""

    def __init__(self):
        self.q: queue.Queue = queue.Queue()
        self.thread = threading.Thread(target=self._run, name="pointer", daemon=True)
        self.ok = False
        self.error = ""
        self.screen_w, self.screen_h = 2560, 1440
        self.ready = threading.Event()
        self.thread.start()
        self.ready.wait(5)

    # ---- public API ------------------------------------------------------------------
    def point(self, x: float, y: float, label: str = "", box: tuple | None = None, hold: float = 6.0):
        self.q.put(("point", float(x), float(y), label, box, hold))

    def hide(self, now: bool = False):
        self.q.put(("hide_now",) if now else ("hide",))

    def stop(self):
        self.q.put(("quit",))

    # ---- thread ---------------------------------------------------------------------
    def _run(self):
        import sys
        if sys.platform == "darwin":
            try:
                self._start_mac()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                log.warning("pointer unavailable: %s", self.error)
                self.ready.set()
                return
            self.ready.set()
            self._loop()
            return
        if sys.platform.startswith("win"):
            try:
                self._start_windows()
            except Exception as e:
                self.error = f"{type(e).__name__}: {e}"
                log.warning("pointer unavailable: %s", self.error)
                self.ready.set()
                return
            self.ready.set()
            self._loop()
            return
        try:
            from Xlib import X, display
            d = display.Display()
            screen = d.screen()
            self.screen_w, self.screen_h = screen.width_in_pixels, screen.height_in_pixels
            visual = next((v for dp in screen.allowed_depths if dp.depth == 32 for v in dp.visuals
                           if v.visual_class == X.TrueColor), None)
            if visual is None:
                raise RuntimeError("no 32-bit ARGB visual (compositor without alpha support)")
            cmap = screen.root.create_colormap(visual.visual_id, X.AllocNone)
            has_shape = d.has_extension("SHAPE")
            self.cursor = Overlay(d, screen, visual, cmap, has_shape)
            self.box = Overlay(d, screen, visual, cmap, has_shape)
            self.font = _font(26 * 2)             # drawn on a 2x supersampled canvas
            self.sprite_cache: dict = {}
            self.ok = True
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            log.warning("pointer unavailable: %s", self.error)
            self.ready.set()
            return
        self.ready.set()
        self._loop()

    def _start_mac(self):
        import config
        helper = subprocess.Popen([sys_executable(), str(config.ROOT / "helpers" / "mac_overlay.py")],
                                  stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        first = helper.stdout.readline().decode().split()
        if len(first) != 3 or first[0] != "ready":
            err = helper.stderr.read(400).decode(errors="replace") if helper.poll() is not None else ""
            raise RuntimeError("the overlay helper didn't start (needs pyobjc) " + err.strip()[-200:])
        self.screen_w, self.screen_h = int(first[1]), int(first[2])
        self.cursor, self.box = MacOverlay(helper, "cursor"), MacOverlay(helper, "box")
        self.font = _font(26 * 2)
        self.sprite_cache = {}
        self.ok = True


    def _start_windows(self):
        import ctypes
        self.screen_w = ctypes.windll.user32.GetSystemMetrics(0)
        self.screen_h = ctypes.windll.user32.GetSystemMetrics(1)
        self.cursor = WindowsOverlay()
        self.box = WindowsOverlay()
        self.font = _font(26 * 2)
        self.sprite_cache = {}
        self.ok = True

    def _loop(self):
        pos = None                      # current tip position (x, y)
        state = None                    # active animation
        while True:
            try:
                cmd = self.q.get(timeout=0.2 if state is None else 1 / FPS)
            except queue.Empty:
                cmd = None
            if cmd:
                if cmd[0] == "quit":
                    self.cursor.hide(); self.box.hide()
                    return
                if cmd[0] == "hide":
                    if state:
                        state["t_fade"] = time.monotonic()
                elif cmd[0] == "hide_now":
                    self.cursor.hide(); self.box.hide()
                    state, pos = None, None
                elif cmd[0] == "point":
                    _, x, y, label, box, hold = cmd
                    x = min(max(x, 4), self.screen_w - 4)
                    y = min(max(y, 4), self.screen_h - 4)
                    now = time.monotonic()
                    start = pos or (min(max(x - 320, 0), self.screen_w), min(max(y - 200, 0), self.screen_h))
                    state = {"from": start, "to": (x, y), "t0": now, "glide": 0.75 if pos else 0.6, "label": label,
                             "box": box, "hold": hold, "t_fade": None, "born": pos is None or state is None,
                             "boxed": False}
                    self.box.hide()
            if state is None:
                continue
            try:
                done = self._frame(state)
                pos = state.get("pos", pos)
            except Exception as e:
                log.warning("pointer frame failed: %s", e)
                done = True
            if done:
                self.cursor.hide(); self.box.hide()
                state, pos = None, None

    # ---- drawing ---------------------------------------------------------------------
    def _frame(self, s: dict) -> bool:
        now = time.monotonic()
        t = now - s["t0"]
        g = min(1.0, t / s["glide"])
        e = g * g * (3 - 2 * g)                                             # ease in-out
        (x0, y0), (x1, y1) = s["from"], s["to"]
        # a gentle arc so the cursor sweeps instead of sliding in a straight line
        arc = math.sin(math.pi * e) * min(60.0, math.hypot(x1 - x0, y1 - y0) * 0.12)
        x = x0 + (x1 - x0) * e + arc * -(y1 - y0) / (math.hypot(x1 - x0, y1 - y0) or 1)
        y = y0 + (y1 - y0) * e + arc * (x1 - x0) / (math.hypot(x1 - x0, y1 - y0) or 1)
        s["pos"] = (x1, y1) if g >= 1 else (x, y)
        alpha = min(1.0, t / 0.25) if s["born"] else 1.0
        if s["t_fade"] is not None or t > s["glide"] + s["hold"]:
            f0 = s["t_fade"] if s["t_fade"] is not None else s["t0"] + s["glide"] + s["hold"]
            fade = (now - f0) / 0.45
            if fade >= 1:
                return True
            alpha *= 1 - fade
        if g >= 1 and s["box"] and not s["boxed"]:
            self._draw_box(s["box"], alpha)
            s["boxed"] = True
        img, ox, oy, (w, h) = self._sprite(s["label"], x1 > self.screen_w - 420, y1 > self.screen_h - 140,
                                           max(0.0, t - s["glide"]))
        self.cursor.show(int(x - ox), int(y - oy), w, h, img, alpha)
        if s["boxed"]:
            self.box.raise_()
            self.cursor.raise_()
        return False

    def _sprite(self, label: str, flip_x: bool, flip_y: bool, since_arrival: float):
        """Cursor + ripple + label on one transparent canvas. Returns (image, tip_x, tip_y, (w, h))."""
        S = 2                                                               # supersample for smooth edges
        font = self.font
        text_w = int(ImageDraw.Draw(Image.new("L", (1, 1))).textlength(label[:60], font=font) / S) if label else 0
        pill_w = min(520, text_w + 34) if label else 0
        W = max(190, pill_w + 90)
        H = 190
        tip = (W - 60, 60) if flip_x else (60, 60)
        ty = H - 60 if flip_y else 60
        tip = (tip[0], ty)
        img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        gd, d = ImageDraw.Draw(glow), ImageDraw.Draw(img)
        tx, ty = tip[0] * S, tip[1] * S
        # ripples that keep pulsing once the cursor has arrived
        for k in range(2):
            p = ((since_arrival * 0.9) + k * 0.5) % 1.0 if since_arrival > 0 else 0.0
            if since_arrival > 0:
                r = (14 + 46 * p) * S
                a = int(190 * (1 - p) ** 1.5)
                d.ellipse([tx - r, ty - r, tx + r, ty + r], outline=CYAN + (a,), width=3 * S)
        # arrow (classic cursor outline), tip at (tx, ty)
        pts = [(0, 0), (0, 29), (7.2, 22.5), (12.3, 34), (18, 31.2), (12.8, 20), (22, 20)]
        poly = [(tx + px * S * 1.15, ty + py * S * 1.15) for px, py in pts]
        gd.polygon(poly, fill=CYAN + (255,))
        d.polygon(poly, fill=CYAN + (255,), outline=(255, 255, 255, 255), width=2 * S)
        if label:
            x0 = (tip[0] - 24 - pill_w) if flip_x else (tip[0] + 22)
            y0 = (tip[1] - 62) if flip_y else (tip[1] + 34)
            box = [x0 * S, y0 * S, (x0 + pill_w) * S, (y0 + 38) * S]
            gd.rounded_rectangle(box, radius=19 * S, fill=CYAN + (170,))
            d.rounded_rectangle(box, radius=19 * S, fill=INK + (225,), outline=CYAN + (255,), width=2 * S)
            d.text(((x0 + 17) * S, (y0 + 19) * S), label[:60], font=font, fill=(235, 245, 255, 255), anchor="lm")
        glow = glow.filter(ImageFilter.GaussianBlur(9 * S))
        out = Image.alpha_composite(glow, img).resize((W, H), Image.LANCZOS)
        return out, tip[0], tip[1], (W, H)

    def _draw_box(self, box: tuple, alpha: float):
        """Highlight rectangle (x0, y0, x1, y1) in screen pixels."""
        x0, y0, x1, y1 = (int(v) for v in box)
        x0, y0 = max(0, x0), max(0, y0)
        x1, y1 = min(self.screen_w, x1), min(self.screen_h, y1)
        if x1 - x0 < 8 or y1 - y0 < 8:
            return
        pad = 14
        w, h = x1 - x0 + 2 * pad, y1 - y0 + 2 * pad
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        r = min(14, (x1 - x0) // 4, (y1 - y0) // 4)
        ImageDraw.Draw(glow).rounded_rectangle([pad, pad, w - pad, h - pad], radius=r, outline=CYAN + (255,), width=6)
        glow = glow.filter(ImageFilter.GaussianBlur(7))
        d = ImageDraw.Draw(img)
        d.rounded_rectangle([pad, pad, w - pad, h - pad], radius=r, fill=CYAN + (28,), outline=CYAN + (255,), width=3)
        self.box.show(x0 - pad, y0 - pad, w, h, Image.alpha_composite(glow, img), alpha)
