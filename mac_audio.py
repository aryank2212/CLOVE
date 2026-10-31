"""macOS audio devices, read live from CoreAudio through ctypes (no extra packages).

PortAudio (sounddevice) reads the device list once and never notices headphones connecting or the default output
changing, so on a Mac CLOVE asks CoreAudio which devices are current and re-opens its streams itself
(audio.mac_follow)."""
import ctypes
import ctypes.util
from dataclasses import dataclass

_u32 = ctypes.c_uint32


class _Addr(ctypes.Structure):
    _fields_ = [("selector", _u32), ("scope", _u32), ("element", _u32)]


def _cc(s: str) -> int:
    return int.from_bytes(s.encode(), "big")


_ca = _cf = None


def _libs():
    global _ca, _cf
    if _ca is None:
        _ca = ctypes.CDLL(ctypes.util.find_library("CoreAudio"))
        _cf = ctypes.CDLL(ctypes.util.find_library("CoreFoundation"))
        _ca.AudioObjectGetPropertyData.argtypes = [_u32, ctypes.POINTER(_Addr), _u32, ctypes.c_void_p,
                                                   ctypes.POINTER(_u32), ctypes.c_void_p]
        _ca.AudioObjectGetPropertyData.restype = ctypes.c_int32
        _ca.AudioObjectGetPropertyDataSize.argtypes = [_u32, ctypes.POINTER(_Addr), _u32, ctypes.c_void_p,
                                                       ctypes.POINTER(_u32)]
        _ca.AudioObjectGetPropertyDataSize.restype = ctypes.c_int32
        _cf.CFStringGetCString.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_long, _u32]
        _cf.CFStringGetCString.restype = ctypes.c_bool
        _cf.CFRelease.argtypes = [ctypes.c_void_p]
    return _ca, _cf


SYSTEM = 1
GLOBAL, INPUT, OUTPUT = _cc("glob"), _cc("inpt"), _cc("outp")


def _get(obj: int, selector: str, ctype, scope: int = GLOBAL):
    ca, _ = _libs()
    addr = _Addr(_cc(selector), scope, 0)
    val = ctype()
    size = _u32(ctypes.sizeof(val))
    st = ca.AudioObjectGetPropertyData(obj, ctypes.byref(addr), 0, None, ctypes.byref(size), ctypes.byref(val))
    if st != 0:
        raise OSError(f"CoreAudio {selector}: {st}")
    return val


def _name(dev: int) -> str:
    _, cf = _libs()
    ref = _get(dev, "lnam", ctypes.c_void_p)
    if not ref.value:
        return ""
    buf = ctypes.create_string_buffer(512)
    ok = cf.CFStringGetCString(ref, buf, 512, 0x08000100)       # kCFStringEncodingUTF8
    cf.CFRelease(ref)
    return buf.value.decode("utf-8", "replace") if ok else ""


def _channels(dev: int, scope: int) -> int:
    """Number of channels the device has in a direction (0 = it has none)."""
    ca, _ = _libs()
    addr = _Addr(_cc("slay"), scope, 0)                          # kAudioDevicePropertyStreamConfiguration
    size = _u32(0)
    if ca.AudioObjectGetPropertyDataSize(dev, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0 or size.value < 8:
        return 0
    buf = (ctypes.c_ubyte * size.value)()
    if ca.AudioObjectGetPropertyData(dev, ctypes.byref(addr), 0, None, ctypes.byref(size), buf) != 0:
        return 0
    n = int.from_bytes(bytes(buf[:4]), "little")                 # AudioBufferList: mNumberBuffers, then buffers
    total, off = 0, 8                                            # each AudioBuffer: channels u32, size u32, data ptr
    for _ in range(n):
        total += int.from_bytes(bytes(buf[off:off + 4]), "little")
        off += 8 + ctypes.sizeof(ctypes.c_void_p)
    return total


@dataclass(frozen=True)
class Device:
    id: int
    name: str
    transport: str          # "blue" Bluetooth, "bltn" built-in, "usb ", "virt" virtual (BlackHole), "aggr", ...

    @property
    def bluetooth(self) -> bool:
        return self.transport in ("blue", "blea")

    @property
    def virtual(self) -> bool:
        return self.transport in ("virt", "aggr", "grup") or "blackhole" in self.name.lower()


def _device(dev: int) -> Device:
    try:
        t = _get(dev, "tran", _u32).value.to_bytes(4, "big").decode("ascii", "replace")
    except OSError:
        t = ""
    return Device(dev, _name(dev), t)


def default(kind: str) -> Device | None:
    """The system's current default 'input' or 'output' device."""
    try:
        dev = _get(SYSTEM, "dOut" if kind == "output" else "dIn ", _u32).value
        return _device(dev) if dev else None
    except (OSError, AttributeError, TypeError):
        return None


def devices(kind: str) -> list[Device]:
    """Every device that can do 'input' or 'output'."""
    try:
        ca, _ = _libs()
        addr = _Addr(_cc("dev#"), GLOBAL, 0)
        size = _u32(0)
        if ca.AudioObjectGetPropertyDataSize(SYSTEM, ctypes.byref(addr), 0, None, ctypes.byref(size)) != 0:
            return []
        ids = (_u32 * (size.value // 4))()
        if ca.AudioObjectGetPropertyData(SYSTEM, ctypes.byref(addr), 0, None, ctypes.byref(size), ids) != 0:
            return []
        scope = INPUT if kind == "input" else OUTPUT
        return [_device(i) for i in ids if _channels(i, scope) > 0]
    except (OSError, AttributeError, TypeError):
        return []
