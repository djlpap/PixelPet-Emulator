# PiicoDev_Unified.py — Desktop emulator shim for Piico:Dev SSD1306 + CAP1203
# - sleep_ms/us with GUI pumping; MicroPython ticks_* monkey-patch
# - SSD1306 (0x3C) & CAP1203 (0x28) emulation
# - Tk window clears each frame; DEFAULT KEYS: Left / Enter / Right

import time

compat_ind = 2

i2c_err_str = "I2C device at 0x{:02X} not responding"

try:
    import tkinter as tk
except Exception:
    tk = None

_oled_window = None

# ---- GUI pump ----
def _pump_gui_once():
    global _oled_window
    if tk is None or _oled_window is None:
        return
    try:
        _oled_window.root.update_idletasks(); _oled_window.root.update()
    except Exception:
        pass

# ---- sleep & ticks (MicroPython compat) ----
_T0 = time.monotonic()

def sleep_ms(ms: int):
    end = time.monotonic() + (ms/1000.0)
    _pump_gui_once()
    step = 0.005
    while time.monotonic() < end:
        time.sleep(step)
        _pump_gui_once()

def sleep_us(us: int):
    target = time.monotonic() + (us/1_000_000.0)
    _pump_gui_once()
    while time.monotonic() < target:
        time.sleep(0.0005)
        _pump_gui_once()

if not hasattr(time, 'ticks_ms'):
    time.ticks_ms = lambda: int((time.monotonic() - _T0) * 1000)
if not hasattr(time, 'ticks_us'):
    time.ticks_us = lambda: int((time.monotonic() - _T0) * 1_000_000)
if not hasattr(time, 'ticks_diff'):
    time.ticks_diff = lambda a, b: int(a) - int(b)

# ---- CAP1203 key state ----
class _KeyState:
    def __init__(self):
        self.cs = [0, 0, 0]
    def set_key(self, which, val):
        if 0 <= which < 3:
            self.cs[which] = 1 if val else 0
    @property
    def any_touched(self):
        return any(self.cs)
    @property
    def sensor_input_status(self):
        return (self.cs[0] << 0) | (self.cs[1] << 1) | (self.cs[2] << 2)

_key_state = _KeyState()

# ---- OLED window ----
class _OLEDWindow:
    def __init__(self, width=128, height=64, scale=4, keymap=("Left","Return","Right")):
        if tk is None:
            raise RuntimeError("Tkinter not available")
        self.w, self.h, self.scale = width, height, scale
        self.root = tk.Tk(); self.root.title("Piico:Dev SSD1306 (emulator)")
        self.canvas = tk.Canvas(self.root, width=width*scale, height=height*scale,
                                bg="black", highlightthickness=0)
        self.canvas.pack(); self.canvas.focus_set()
        self._bind_key(keymap[0], 0)
        self._bind_key(keymap[1], 1)
        self._bind_key(keymap[2], 2)
        self.update_from_buffer(bytearray((self.h//8)*self.w))
    def _bind_key(self, keyname, idx):
        self.root.bind(f"<KeyPress-{keyname}>",  lambda e, i=idx: _key_state.set_key(i, 1))
        self.root.bind(f"<KeyRelease-{keyname}>", lambda e, i=idx: _key_state.set_key(i, 0))
    def update_from_buffer(self, buf: bytes):
        s = self.scale
        try:
            self.canvas.delete("all")
        except Exception:
            pass
        pages = self.h // 8
        for page in range(pages):
            base = page * self.w
            for x in range(self.w):
                b = buf[base + x]
                if b == 0: continue
                for bit in range(8):
                    if b & (1 << bit):
                        y = page*8 + bit
                        x0, y0 = x*s, y*s
                        self.canvas.create_rectangle(x0, y0, x0+s, y0+s, outline="", fill="#FFFFFF")
        _pump_gui_once()

# ---- Emulated I2C bus ----
class _EmulatedI2C:
    def __init__(self):
        self._cap = _CAP1203_Emu(); self._ssd = _SSD1306_Emu()
    def readfrom_mem(self, addr: int, reg: int, nbytes: int) -> bytes:
        if addr == 0x28:
            return self._cap.read(reg, nbytes)
        return bytes([0x00] * nbytes)
    def writeto_mem(self, addr: int, reg: int, data: bytes):
        if addr == 0x3C:
            self._ssd.write(reg, data); return
        if addr == 0x28:
            self._cap.write(reg, data); return

# ---- SSD1306 emulation ----
class _SSD1306_Emu:
    def __init__(self):
        self._last = bytearray(1024)
    def write(self, reg: int, data: bytes):
        global _oled_window
        if reg == 0x80:
            return
        if reg == 0x40:
            if not isinstance(data, (bytes, bytearray)):
                data = bytes(data)
            L = min(len(self._last), len(data))
            self._last[:L] = data[:L]
            if _oled_window is None:
                _oled_window = _OLEDWindow(scale=4, keymap=("Left","Return","Right"))
            _oled_window.update_from_buffer(self._last)

# ---- CAP1203 emulation ----
class _CAP1203_Emu:
    MAIN_CONTROL = 0x00
    GENERAL_STATUS = 0x02
    SENSOR_INPUT_STATUS = 0x03
    SENSOR_INPUT_1_DELTA = 0x10
    SENSOR_INPUT_2_DELTA = 0x11
    SENSOR_INPUT_3_DELTA = 0x12
    def __init__(self):
        self._interrupt = False
    def _refresh(self):
        _pump_gui_once()
        self._interrupt = _key_state.any_touched
    def read(self, reg: int, n: int) -> bytes:
        self._refresh()
        if reg == self.GENERAL_STATUS:
            return bytes([(1 if self._interrupt else 0) & 0x01])
        if reg == self.SENSOR_INPUT_STATUS:
            return bytes([_key_state.sensor_input_status & 0x07])
        if reg in (self.SENSOR_INPUT_1_DELTA, self.SENSOR_INPUT_2_DELTA, self.SENSOR_INPUT_3_DELTA):
            idx = reg - self.SENSOR_INPUT_1_DELTA
            val = 0x20 if _key_state.cs[idx] else 0x02
            return bytes([val])
        return bytes([0x00] * n)
    def write(self, reg: int, data: bytes):
        if reg == self.MAIN_CONTROL:
            self._interrupt = False

_emulated_bus = None

def create_unified_i2c(bus=None, freq=None, sda=None, scl=None):
    global _emulated_bus
    if _emulated_bus is None:
        _emulated_bus = _EmulatedI2C()
    return _emulated_bus

