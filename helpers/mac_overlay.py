"""macOS overlay windows for CLOVE's on-screen pointer (pointer.py), in their own process because Cocoa windows
must live on a main thread and CLOVE's main thread runs asyncio.

Reads commands on stdin, one per line:
    show <id> <x> <y> <w> <h> <alpha> <n>\\n  followed by n bytes: the picture as PNG
    hide <id> | raise <id> | quit
Coordinates and sizes are in screenshot pixels (top-left origin); they are turned into points here, so the pointer
lands exactly where the vision model found the thing on a Retina screen too. Windows are transparent, float above
everything (full-screen apps too) and let every click pass through. Needs: pip install pyobjc."""
import sys
import threading

import objc  # noqa: F401
from AppKit import (NSApplication, NSApplicationActivationPolicyAccessory, NSBackingStoreBuffered, NSColor, NSImage, NSImageView, NSScreen, NSScreenSaverWindowLevel, NSWindow,
                    NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorFullScreenAuxiliary,
                    NSWindowCollectionBehaviorStationary, NSWindowStyleMaskBorderless)
from Foundation import NSData, NSMakeRect, NSMakeSize
from PyObjCTools import AppHelper

app = NSApplication.sharedApplication()
app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)      # no Dock icon, never takes focus
screen = NSScreen.mainScreen()
SCALE = screen.backingScaleFactor()
HEIGHT = screen.frame().size.height
windows: dict[str, tuple] = {}


def _window(wid: str):
    if wid not in windows:
        w = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, 10, 10), NSWindowStyleMaskBorderless, NSBackingStoreBuffered, False)
        w.setOpaque_(False)
        w.setBackgroundColor_(NSColor.clearColor())
        w.setHasShadow_(False)
        w.setIgnoresMouseEvents_(True)
        w.setLevel_(NSScreenSaverWindowLevel)
        w.setCollectionBehavior_(NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
                                 | NSWindowCollectionBehaviorFullScreenAuxiliary)
        view = NSImageView.alloc().initWithFrame_(NSMakeRect(0, 0, 10, 10))
        w.setContentView_(view)
        windows[wid] = (w, view)
    return windows[wid]


def show(wid: str, x: int, y: int, w: int, h: int, alpha: float, png: bytes):
    win, view = _window(wid)
    pw, ph = w / SCALE, h / SCALE
    img = NSImage.alloc().initWithData_(NSData.dataWithBytes_length_(png, len(png)))
    if img is None:
        return
    img.setSize_(NSMakeSize(pw, ph))
    view.setImage_(img)
    view.setFrame_(NSMakeRect(0, 0, pw, ph))
    win.setFrame_display_(NSMakeRect(x / SCALE, HEIGHT - (y + h) / SCALE, pw, ph), True)
    win.setAlphaValue_(max(0.0, min(1.0, alpha)))
    win.orderFrontRegardless()


def hide(wid: str):
    if wid in windows:
        windows[wid][0].orderOut_(None)


def lift(wid: str):
    if wid in windows:
        windows[wid][0].orderFrontRegardless()


def reader():
    inp = sys.stdin.buffer
    while True:
        line = inp.readline()
        if not line:
            break
        parts = line.decode().split()
        if not parts:
            continue
        if parts[0] == "show" and len(parts) == 8:
            wid, (x, y, w, h), alpha = parts[1], map(int, parts[2:6]), float(parts[6])
            data = inp.read(int(parts[7]))
            AppHelper.callAfter(show, wid, x, y, w, h, alpha, data)
        elif parts[0] == "hide" and len(parts) == 2:
            AppHelper.callAfter(hide, parts[1])
        elif parts[0] == "raise" and len(parts) == 2:
            AppHelper.callAfter(lift, parts[1])
        elif parts[0] == "quit":
            break
    AppHelper.callAfter(AppHelper.stopEventLoop)


print(f"ready {int(screen.frame().size.width * SCALE)} {int(HEIGHT * SCALE)}", flush=True)
threading.Thread(target=reader, daemon=True).start()
AppHelper.runEventLoop(installInterrupt=True)
