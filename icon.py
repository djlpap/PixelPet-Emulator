# icon.py — MicroPython + Desktop Emulator Compatible
# Enhancements:
# 1) Per-sprite auto-clear in Animate.animate() to prevent trails.
# 2) Toolbar.show() clears the 16px toolbar band (y=0..15) before redrawing, so selection changes don't smear.
# 3) Event.popup() clears its 128x48 area before and after display.

import gc, os
from time import sleep
from os import listdir

# -------- Optional MicroPython modules (guarded for desktop) --------
try:
    import framebuf as _mp_framebuf   # MicroPython framebuf
    _HAVE_FRAMEBUF = True
except Exception:
    _mp_framebuf = None
    _HAVE_FRAMEBUF = False

try:
    from machine import Pin as _MP_Pin
    _HAVE_MACHINE = True
except Exception:
    _MP_Pin = None
    _HAVE_MACHINE = False

# Root folder for assets (where main.py sits)
try:
    _ROOT = os.path.dirname(__file__)
except Exception:
    _ROOT = os.getcwd()

# -------- Desktop fallback: simple image classes + software blit --------
class _PBMImage:
    """Minimal 1-bit (P4) PBM image for desktop use."""
    def __init__(self, path, width=None, height=None):
        self._w = width or 0
        self._h = height or 0
        self._buf = None
        self._load_pbm(path)

    @property
    def width(self):  return self._w
    @property
    def height(self): return self._h

    def _load_pbm(self, path):
        with open(path, 'rb') as f:
            magic = f.readline().strip()
            if magic.startswith(b'\xef\xbb\xbf'):
                magic = magic[3:]
            if magic != b'P4':
                raise ValueError("Only PBM (P4) supported for _PBMImage")
            # Skip comments/blank lines
            line = f.readline()
            while line.startswith(b'#') or line.strip() == b'':
                line = f.readline()
            # Dimensions
            dims = line.split()
            if len(dims) < 2:
                dims = f.readline().split()
            self._w = int(dims[0]); self._h = int(dims[1])
            # Raw bitmap data; each row is padded to byte boundary, MSB first per PBM spec.
            self._buf = bytearray(f.read())

    def _byte_index_bit(self, x, y):
        row_bytes = (self._w + 7) // 8
        idx = y * row_bytes + (x // 8)
        bit = 7 - (x % 8)
        return idx, bit

    def pixel(self, x, y, c=None):
        if x < 0 or y < 0 or x >= self._w or y >= self._h:
            return 0 if c is None else None
        i, b = self._byte_index_bit(x, y)
        mask = (1 << b)
        if c is None:
            return 1 if (self._buf[i] & mask) else 0
        else:
            if c:
                self._buf[i] |= mask
            else:
                self._buf[i] &= ~mask

class _PPMImageAsPBM:
    """Read P6/P3 and convert to 1-bit using luminance threshold for desktop."""
    def __init__(self, path):
        self._w = 0; self._h = 0
        self._buf = None  # 1-bpp packed, PBM-like
        self._load_ppm_as_pbm(path)

    @property
    def width(self):  return self._w
    @property
    def height(self): return self._h

    def _pack_set(self, x, y):
        row_bytes = (self._w + 7)//8
        i = y*row_bytes + (x//8)
        b = 7 - (x%8)
        self._buf[i] |= (1<<b)

    def _load_ppm_as_pbm(self, path):
        with open(path, 'rb') as f:
            magic = f.readline().strip()
            def _read_noncomment():
                line = f.readline()
                while line.startswith(b'#') or line.strip()==b'':
                    line = f.readline()
                return line
            dims_line = _read_noncomment()
            dims = dims_line.split()
            self._w = int(dims[0]); self._h = int(dims[1])
            max_line = _read_noncomment()
            max_val = int(max_line.strip())
            self._buf = bytearray(((self._w+7)//8)*self._h)
            if magic == b'P6':
                raw = f.read(self._w*self._h*3)
                thr = 0.5*max_val
                for y in range(self._h):
                    row_off = y*self._w*3
                    for x in range(self._w):
                        r = raw[row_off+3*x]
                        g = raw[row_off+3*x+1]
                        b = raw[row_off+3*x+2]
                        yv = 0.299*r + 0.587*g + 0.114*b
                        if yv >= thr:
                            self._pack_set(x,y)
            elif magic == b'P3':
                tokens = []
                for line in f:
                    tokens.extend(line.split())
                thr = 0.5*max_val
                it = iter(map(int, tokens))
                for y in range(self._h):
                    for x in range(self._w):
                        r = next(it); g = next(it); b = next(it)
                        yv = 0.299*r + 0.587*g + 0.114*b
                        if yv >= thr:
                            self._pack_set(x,y)
            else:
                raise ValueError('Unsupported PPM magic: %r' % magic)

    def pixel(self, x, y, c=None):
        if x < 0 or y < 0 or x >= self._w or y >= self._h:
            return 0 if c is None else None
        row_bytes = (self._w + 7)//8
        i = y*row_bytes + (x//8)
        b = 7 - (x%8)
        mask = (1<<b)
        if c is None:
            return 1 if (self._buf[i] & mask) else 0
        else:
            if c:
                self._buf[i] |= mask
            else:
                self._buf[i] &= ~mask

# Helper: software blit
def _soft_blit(oled, src_img, dst_x, dst_y):
    get_px = getattr(src_img, "pixel", None)
    w = getattr(src_img, "width", None) or getattr(src_img, "width", 0)
    h = getattr(src_img, "height", None) or getattr(src_img, "height", 0)
    if callable(get_px) and w and h:
        for y in range(h):
            for x in range(w):
                if get_px(x, y):
                    oled.pixel(dst_x + x, dst_y + y, 1)


# =============================================================================
# Icon
# =============================================================================
class Icon:
    __image = None
    __x = 0
    __y = 0
    __invert = False
    __width = 16
    __height = 16
    __name = "Empty"

    def __init__(self, filename=None, width=None, height=None, x=None, y=None, name=None):
        if width  is not None: self.__width  = width
        if height is not None: self.__height = height
        if name   is not None: self.__name   = name
        if x      is not None: self.__x      = x
        if y      is not None: self.__y      = y
        if filename is not None:
            self.__image = self.loadicons(filename)

    @property
    def image(self):
        return self.__image

    @image.setter
    def image(self, buf):
        self.__image = buf

    @property
    def x(self) -> int: return self.__x
    @x.setter
    def x(self, value): self.__x = value

    @property
    def y(self) -> int: return self.__y
    @y.setter
    def y(self, value): self.__y = value

    @property
    def width(self) -> int: return self.__width
    @width.setter
    def width(self, value): self.__width = value

    @property
    def height(self) -> int: return self.__height
    @height.setter
    def height(self, value): self.__height = value

    @property
    def name(self): return self.__name
    @name.setter
    def name(self, value): self.__name = value

    @property
    def invert(self) -> bool:
        return self.__invert

    @invert.setter
    def invert(self, value: bool):
        img = self.__image
        for ix in range(self.width):
            for iy in range(self.height):
                px = img.pixel(ix, iy)
                img.pixel(ix, iy, 0 if px else 1)
        self.__invert = value

    def loadicons(self, file):
        # Build absolute path from project root to avoid CWD/OneDrive issues
        path = os.path.join(_ROOT, file)
        # MicroPython path
        if _HAVE_FRAMEBUF:
            with open(path, 'rb') as f:
                magic = f.readline().strip()
                line = f.readline()
                while line.startswith(b'#') or line.strip()==b'':
                    line = f.readline()
                dims = line.split()
                if not dims:
                    dims = f.readline().split()
                if magic in (b'P6', b'P3'):
                    file_width  = int(dims[0]); file_height = int(dims[1])
                    if magic == b'P6':
                        _ = int(f.readline().strip())
                        data = bytearray(f.read())
                    else:
                        _ = int(f.readline().strip())
                        tokens = []
                        for l in f:
                            tokens.extend(l.split())
                        data = bytearray()
                        for i in range(0, len(tokens), 3):
                            r = int(tokens[i]); g = int(tokens[i+1]); b = int(tokens[i+2])
                            rgb565 = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
                            data.append(rgb565 >> 8); data.append(rgb565 & 0xFF)
                    self.__width, self.__height = file_width, file_height
                    fbuf = _mp_framebuf.FrameBuffer(data, self.__width, self.__height, _mp_framebuf.RGB565)
                else:
                    if dims and len(dims) >= 2:
                        self.__width  = int(dims[0])
                        self.__height = int(dims[1])
                    data = bytearray(f.read())
                    fbuf = _mp_framebuf.FrameBuffer(data, self.__width, self.__height, _mp_framebuf.MONO_HLSB)
            return fbuf
        # Desktop fallback: support PBM and PPM
        try:
            return _PBMImage(path, width=self.__width, height=self.__height)
        except Exception:
            return _PPMImageAsPBM(path)


# =============================================================================
# Toolbar — now clears its 16px band at y=0 before drawing
# =============================================================================
class Toolbar:
    __icon_array = []
    __spacer = 1
    __selected_item = None
    __selected_index = -1

    def __init__(self):
        if _HAVE_FRAMEBUF:
            self.__framebuf = _mp_framebuf.FrameBuffer(bytearray(160 * 16 // 8), 160, 16, _mp_framebuf.MONO_HLSB)
        else:
            self.__framebuf = None

    def additem(self, icon): self.__icon_array.append(icon)
    def remove(self, icon):  self.__icon_array.remove(icon)

    @property
    def spacer(self): return self.__spacer
    @spacer.setter
    def spacer(self, value): self.__spacer = value

    def _render_to_fb(self):
        fb = self.__framebuf
        for x in range(160):
            for y in range(16):
                fb.pixel(x, y, 0)
        x = 0
        for icon in self.__icon_array:
            img = icon.image
            try:
                fb.blit(img, x, 0)
            except Exception:
                for iy in range(icon.height):
                    for ix in range(icon.width):
                        if img.pixel(ix, iy):
                            fb.pixel(x + ix, iy, 1)
            x += icon.width + self.spacer
        return fb

    def show(self, oled):
        # Clear the toolbar band at y=0..15 before redrawing so navigation doesn't smear
        try:
            oled.fill_rect(0, 0, 128, 16, 0)
        except Exception:
            # fallback via pixels if needed
            for yy in range(16):
                for xx in range(128):
                    oled.pixel(xx, yy, 0)

        if _HAVE_FRAMEBUF and hasattr(oled, "blit"):
            fb = self._render_to_fb()
            oled.blit(fb, 0, 0)
        else:
            x = 0
            for icon in self.__icon_array:
                _soft_blit(oled, icon.image, x, 0)
                x += icon.width + self.spacer

    def select(self, index, oled):
        self.__icon_array[index].invert = True
        self.__selected_index = index
        self.show(oled)

    def unselect(self, index, oled):
        self.__icon_array[index].invert = False
        self.__selected_index = -1
        self.show(oled)

    @property
    def selected_item(self):
        self.__selected_item = self.__icon_array[self.__selected_index].name
        return self.__selected_item


# =============================================================================
# Animate (with per-sprite auto-clear)
# =============================================================================
class Animate:
    __frames = []
    __current_frame = 0
    __speed = "normal"
    __speed_value = 0
    __done = False
    __loop_count = 0
    __bouncing = False
    __animation_type = "default"
    __pause = 0
    __set = False
    __x = 0
    __y = 0
    __width = 16
    __height = 16
    __cached = False
    __filename = None
    __last_bbox = None  # (x,y,w,h) of last drawn frame for auto-clear

    @property
    def set(self) -> bool: return self.__set
    @set.setter
    def set(self, value: bool):
        self.__set = value
        if value: self.load()
        else:     self.unload()

    @property
    def speed(self): return self.__speed
    @speed.setter
    def speed(self, value: str):
        if value in ['very slow', 'slow', 'normal', 'fast']:
            self.__speed = value
            if value == 'very slow':
                self.__pause = 10; self.__speed_value = 10
            elif value == 'slow':
                self.__pause = 1;  self.__speed_value = 1
            elif value == "normal":
                self.__pause = 0;  self.__speed_value = 0
        else:
            print(value, "is not a valid value, try 'fast','normal' or 'slow'")

    @property
    def animation_type(self): return self.__animation_type
    @animation_type.setter
    def animation_type(self, value):
        if value in ['default', 'loop', 'bounce', 'reverse', 'bouncing']:
            self.__animation_type = value
        else:
            print(value, "is not a valid Animation type - try 'loop','bounce','reverse','default'")

    def __init__(self, frames=None, animation_type: str=None, x: int=None, y: int=None,
                 width: int=None, height: int=None, filename=None):
        if x      is not None: self.__x = x
        if y      is not None: self.__y = y
        if width  is not None: self.__width = width
        if height is not None: self.__height = height
        self.__current_frame = 0
        if frames is not None:
            self.__frames = frames
            self.__done = False
            self.__loop_count = 1
        if animation_type is not None:
            self.animation_type = animation_type
        if filename:
            self.__filename = filename

    @property
    def filename(self): return self.__filename
    @filename.setter
    def filename(self, value): self.__filename = value

    def forward(self):
        if self.__speed == 'normal':
            self.__current_frame += 1
        elif self.__speed in ['very slow', 'slow']:
            if self.__pause > 0:
                self.__pause -= 1
            else:
                self.__current_frame += 1
                self.__pause = self.__speed_value
        elif self.__speed == 'fast':
            self.__current_frame += 2 if self.__current_frame < self.frame_count + 2 else 1

    def reverse(self):
        if self.__speed == 'normal':
            self.__current_frame -= 1
        elif self.__speed in ['very slow', 'slow']:
            if self.__pause > 0:
                self.__pause -= 1
            else:
                self.__current_frame -= 1
                self.__pause = self.__speed_value
        elif self.__speed == 'fast':
            self.__current_frame -= 2 if self.__current_frame < self.frame_count + 2 else 1

    def load(self):
        if not self.__cached:
            try:
                files = listdir(_ROOT)
            except Exception:
                files = listdir()
            array = []
            prefix = (self.__filename or "").lower()
            found = []
            for file in files:
                path = os.path.join(_ROOT, file)
                if not os.path.isfile(path):
                    continue
                lf = file.lower()
                if lf.startswith(prefix) and (lf.endswith('.pbm') or lf.endswith('.ppm')):
                    found.append(file)
                    try:
                        array.append(Icon(filename=file, width=self.__width, height=self.__height,
                                          x=self.__x, y=self.__y, name=file))
                    except Exception as e:
                        print("[Animate.load] Skipping frame:", file, "-", e)
                        continue
            if not array:
                print("[Animate.load] No frames loaded for prefix:", self.__filename)
                print("  Files found starting with that prefix:", found or "none")
                print("  Working folder:", _ROOT)
            self.__frames = array
            self.__cached = True

    def unload(self):
        """Free frames and reset cache/state."""
        self.__frames = None
        self.__cached = False
        self.__last_bbox = None
        gc.collect()

    def _clear_last_bbox(self, oled):
        if self.__last_bbox is None:
            return
        lx, ly, lw, lh = self.__last_bbox
        if lw > 0 and lh > 0:
            try:
                oled.fill_rect(max(0,lx), max(0,ly), lw, lh, 0)
            except Exception:
                for yy in range(lh):
                    for xx in range(lw):
                        oled.pixel(lx+xx, ly+yy, 0)

    def animate(self, oled):
        if not self.__frames:
            self.__cached = False
            self.load()
            if not self.__frames:
                return
        if self.__current_frame < 0 or self.__current_frame >= len(self.__frames):
            self.__current_frame = 0

        frame = self.__frames[self.__current_frame]

        # --- Auto-clear previous drawn area ---
        self._clear_last_bbox(oled)

        # Draw this frame
        if hasattr(oled, "blit"):
            try:
                oled.blit(frame.image, frame.x, frame.y)
            except Exception:
                _soft_blit(oled, frame.image, frame.x, frame.y)
        else:
            _soft_blit(oled, frame.image, frame.x, frame.y)

        # Remember last bbox for the next tick
        self.__last_bbox = (frame.x, frame.y, self.__width, self.__height)

        # Advance according to animation_type
        if self.__animation_type == "loop":
            self.forward()
            if self.__current_frame > self.frame_count:
                self.__current_frame = 0
                self.__loop_count -= 1
                if self.__loop_count == 0:
                    self.__done = True

        elif self.__animation_type == "bouncing":
            if self.__bouncing:
                if self.__current_frame == 0:
                    if self.__loop_count == 0:
                        self.__done = True
                    else:
                        if self.__loop_count > 0:
                            self.__loop_count -= 1
                        self.forward(); self.__bouncing = False
                elif self.__loop_count == -1:
                    self.forward(); self.__bouncing = False
                elif (self.__current_frame < self.frame_count) and (self.__current_frame > 0):
                    self.reverse()
                else:
                    if self.__current_frame == 0:
                        if self.__loop_count == 0:
                            self.__done = True
                        elif self.__loop_count == -1:
                            self.forward()
                        else:
                            self.forward(); self.__loop_count -= 1
                    elif self.__current_frame == self.frame_count:
                        self.reverse(); self.__bouncing = True
                    else:
                        self.forward()
            else:
                if self.__current_frame == self.frame_count:
                    self.reverse(); self.__bouncing = True
                else:
                    self.forward()
        else:  # default
            if self.__current_frame == self.frame_count:
                self.__current_frame = 0
                self.__done = True
            else:
                self.forward()

    @property
    def frame_count(self): return len(self.__frames) - 1

    @property
    def done(self):
        if self.__done:
            self.__done = False
            return True
        return False

    def loop(self, no: int=None):
        self.__loop_count = -1 if no is None else no
        self.__animation_type = "loop"

    def stop(self):
        self.__loop_count = 0
        self.__bouncing = False
        self.__done = True

    def bounce(self, no: int=None):
        self.__animation_type = "bouncing"
        self.__loop_count = -1 if no is None else no

    @property
    def width(self): return self.__width
    @width.setter
    def width(self, value): self.__width = value

    @property
    def height(self): return self.__height
    @height.setter
    def height(self, value): self.__height = value


# =============================================================================
# Button (unused by your main loop; keep Pico behaviour, stub on desktop)
# =============================================================================
class Button:
    __pin = None
    __button_down = False

    def __init__(self, pin: int):
        if _HAVE_MACHINE:
            self.__pin = _MP_Pin(pin, _MP_Pin.IN, _MP_Pin.PULL_DOWN)
        else:
            self.__pin = None

    @property
    def is_pressed(self) -> bool:
        if not _HAVE_MACHINE or self.__pin is None:
            return False
        if self.__pin.value() == 0:
            self.__button_down = False
            return False
        if self.__pin.value() == 1:
            if not self.__button_down:
                self.__button_down = True
                return True
            else:
                return False


# =============================================================================
# Event — clears popup area before and after showing
# =============================================================================
class Event:
    __name = ""
    __value = 0
    __sprite = None
    __timer = -1
    __timer_ms = 0
    __callback = None
    __message = ""

    def __init__(self, name=None, sprite=None, value=None, callback=None):
        if name:   self.__name = name
        if sprite: self.__sprite = sprite
        if value:  self.__value = value
        if callback is not None: self.__callback = callback

    @property
    def name(self): return self.__name
    @name.setter
    def name(self, value): self.__name = value

    @property
    def value(self): return self.__value
    @value.setter
    def value(self, value): self.__value = value

    @property
    def sprite(self): return self.__sprite
    @sprite.setter
    def sprite(self, value): self.__value = value

    @property
    def message(self): return self.__message
    @message.setter
    def message(self, value): self.__message = value

    def popup(self, oled):
        # 1) Clear area BEFORE drawing (avoid stacking)
        oled.fill_rect(0, 16, 128, 48, 0)
        # 2) Border + content
        oled.rect(0, 16, 128, 48, 1)
        if self.__sprite is not None and self.__sprite.image is not None:
            if hasattr(oled, "blit"):
                try:
                    oled.blit(self.__sprite.image, 5, 26)
                except Exception:
                    _soft_blit(oled, self.__sprite.image, 5, 26)
            else:
                _soft_blit(oled, self.__sprite.image, 5, 26)
        oled.text(self.__message, 32, 34)
        oled.show()
        sleep(2)
        # 3) Clear area AFTER showing (restore playfield)
        oled.fill_rect(0, 16, 128, 48, 0)

