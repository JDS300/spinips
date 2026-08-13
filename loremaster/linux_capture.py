"""X11 window capture and Tesseract OCR for the Linux build of Loremaster.

Windows freezes pixels with typed GDI calls and recognises them with
Windows.Media.Ocr.  Linux players run EverQuest through Wine, so those two
steps need a native backend.  This module is deliberately the only platform
surface Linux adds: it loads ``libX11`` through :mod:`ctypes` because the
engine ships no third-party Python dependencies, and it shells out to the
``tesseract`` CLI with the same timeout, cancellation and output-size
guardrails the PowerShell worker already uses.

Nothing here injects into, or reads memory from, ``eqgame.exe``.  Window
identity comes from the public EWMH properties ``_NET_ACTIVE_WINDOW`` and
``_NET_WM_PID`` plus ``/proc/<pid>``, and pixels are read from the verified
window's own drawable rather than from the root window.  Reading the window
instead of the root is the safety property that matters: even a bug in the
region maths cannot capture an unrelated application, and it also keeps the
capture correct under XWayland, where the X root window is not the composited
desktop.

Wayland sessions are supported only through XWayland, which is how the desktop
app runs (it forces ``ozone-platform=x11``).  When no X display exists at all
the functions here raise :class:`LinuxCaptureError` with an honest, actionable
message; they never return an empty or invented result.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass


# Tesseract page segmentation and language are overridable because the tuning
# that suits EverQuest's compact UI font cannot be confirmed without the client
# installed; a player can retune without a code change.
OCR_LANGUAGE_ENV = "SPIN_LOREMASTER_TESSERACT_LANG"
OCR_PSM_ENV = "SPIN_LOREMASTER_TESSERACT_PSM"
DEFAULT_OCR_LANGUAGE = "eng"
TESSERACT_TIMEOUT_SECONDS = 8.0
# How long a killed recogniser gets to be reaped before its pipes are dropped.
KILL_REAP_SECONDS = 2.0
MAX_TESSERACT_STDOUT_BYTES = 256 * 1024
MAX_TESSERACT_LINES = 200
MAX_TESSERACT_LINE_CHARS = 160
LIST_LANGS_TIMEOUT_SECONDS = 3.0


class LinuxCaptureError(RuntimeError):
    """A safe, short failure from the synchronous X11 or Tesseract boundary."""


class LinuxOcrCancelled(RuntimeError):
    """The caller cancelled a Tesseract run before it produced output."""


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    """What ``/proc`` says a window's owning process is called."""

    pid: int
    comm: str
    argv0: str

    def matches(self, expected: str) -> bool:
        """True when either public name equals ``expected``, case-folded.

        Wine reports the Windows executable in both places, but which one is
        authoritative varies by launcher: a Proton/umu style wrapper leaves
        ``argv[0]`` pointing at the wine loader while ``comm`` becomes
        ``eqgame.exe``, and a plain ``wine eqgame.exe`` invocation does the
        opposite.  Accepting either keeps the Windows identity guarantee
        without inventing a third source of truth.
        """
        wanted = (expected or "").casefold()
        if not wanted:
            return False
        return wanted in {self.comm.casefold(), self.argv0.casefold()}

    @property
    def described(self) -> str:
        """A short, non-blaming description for error messages."""
        return self.comm or self.argv0 or f"pid {self.pid}"


@dataclass(frozen=True, slots=True)
class WindowRegionCapture:
    """Immutable pixels plus the exact window and screen they came from.

    ``pixels`` is packed 24-bit BGR in top-down row order with ``stride``
    rounded up to a 4-byte boundary, which is exactly what the Windows GDI
    path produces, so the shared BMP writer accepts it unchanged.
    """

    cursor_x: int
    cursor_y: int
    region_left: int
    region_top: int
    region_width: int
    region_height: int
    window: int
    pid: int
    screen_left: int
    screen_top: int
    screen_width: int
    screen_height: int
    pixels: bytes
    stride: int


@dataclass(frozen=True, slots=True)
class TesseractLine:
    """One recognised text line with a bounding box in captured pixels."""

    text: str
    x: float
    y: float
    width: float
    height: float


# --------------------------------------------------------------------------
# libX11 through ctypes
# --------------------------------------------------------------------------

_Z_PIXMAP = 2
_ALL_PLANES = ctypes.c_ulong(-1).value
_IS_VIEWABLE = 2
_ANY_PROPERTY_TYPE = 0
_LSB_FIRST = 0
_SUCCESS = 0


class _XImageFuncs(ctypes.Structure):
    # Xlib exposes image helpers as function pointers on the image itself;
    # XDestroyImage is a macro over destroy_image, so ctypes must call it here.
    _fields_ = [(name, ctypes.c_void_p) for name in (
        "create_image", "destroy_image", "get_pixel", "put_pixel",
        "sub_image", "add_pixel")]


class _XImage(ctypes.Structure):
    _fields_ = [
        ("width", ctypes.c_int),
        ("height", ctypes.c_int),
        ("xoffset", ctypes.c_int),
        ("format", ctypes.c_int),
        ("data", ctypes.c_void_p),
        ("byte_order", ctypes.c_int),
        ("bitmap_unit", ctypes.c_int),
        ("bitmap_bit_order", ctypes.c_int),
        ("bitmap_pad", ctypes.c_int),
        ("depth", ctypes.c_int),
        ("bytes_per_line", ctypes.c_int),
        ("bits_per_pixel", ctypes.c_int),
        ("red_mask", ctypes.c_ulong),
        ("green_mask", ctypes.c_ulong),
        ("blue_mask", ctypes.c_ulong),
        ("obdata", ctypes.c_void_p),
        ("f", _XImageFuncs),
    ]


class _XWindowAttributes(ctypes.Structure):
    _fields_ = [
        ("x", ctypes.c_int), ("y", ctypes.c_int),
        ("width", ctypes.c_int), ("height", ctypes.c_int),
        ("border_width", ctypes.c_int), ("depth", ctypes.c_int),
        ("visual", ctypes.c_void_p), ("root", ctypes.c_ulong),
        ("window_class", ctypes.c_int), ("bit_gravity", ctypes.c_int),
        ("win_gravity", ctypes.c_int), ("backing_store", ctypes.c_int),
        ("backing_planes", ctypes.c_ulong), ("backing_pixel", ctypes.c_ulong),
        ("save_under", ctypes.c_int), ("colormap", ctypes.c_ulong),
        ("map_installed", ctypes.c_int), ("map_state", ctypes.c_int),
        ("all_event_masks", ctypes.c_long), ("your_event_mask", ctypes.c_long),
        ("do_not_propagate_mask", ctypes.c_long),
        ("override_redirect", ctypes.c_int), ("screen", ctypes.c_void_p),
    ]


class _XErrorEvent(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_int),
        ("display", ctypes.c_void_p),
        ("resourceid", ctypes.c_ulong),
        ("serial", ctypes.c_ulong),
        ("error_code", ctypes.c_ubyte),
        ("request_code", ctypes.c_ubyte),
        ("minor_code", ctypes.c_ubyte),
    ]


_ERROR_HANDLER = ctypes.CFUNCTYPE(
    ctypes.c_int, ctypes.c_void_p, ctypes.POINTER(_XErrorEvent))

_library_lock = threading.Lock()
_library: ctypes.CDLL | None = None
# Xlib's error handler is process-global, so only one capture runs at a time.
_capture_lock = threading.Lock()


def _declare(x11: ctypes.CDLL) -> None:
    """Give every call we make an explicit signature, as the Win32 path does."""
    ulong, long_, int_, uint, void_p, char_p = (
        ctypes.c_ulong, ctypes.c_long, ctypes.c_int, ctypes.c_uint,
        ctypes.c_void_p, ctypes.c_char_p)

    x11.XOpenDisplay.argtypes = [char_p]
    x11.XOpenDisplay.restype = void_p
    x11.XCloseDisplay.argtypes = [void_p]
    x11.XCloseDisplay.restype = int_
    x11.XDefaultRootWindow.argtypes = [void_p]
    x11.XDefaultRootWindow.restype = ulong
    x11.XDefaultScreen.argtypes = [void_p]
    x11.XDefaultScreen.restype = int_
    x11.XDisplayWidth.argtypes = [void_p, int_]
    x11.XDisplayWidth.restype = int_
    x11.XDisplayHeight.argtypes = [void_p, int_]
    x11.XDisplayHeight.restype = int_
    x11.XSync.argtypes = [void_p, int_]
    x11.XSync.restype = int_
    x11.XFree.argtypes = [void_p]
    x11.XFree.restype = int_
    x11.XSetErrorHandler.argtypes = [_ERROR_HANDLER]
    x11.XSetErrorHandler.restype = _ERROR_HANDLER
    x11.XInternAtom.argtypes = [void_p, char_p, int_]
    x11.XInternAtom.restype = ulong
    x11.XGetWindowProperty.argtypes = [
        void_p, ulong, ulong, long_, long_, int_, ulong,
        ctypes.POINTER(ulong), ctypes.POINTER(int_), ctypes.POINTER(ulong),
        ctypes.POINTER(ulong), ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte))]
    x11.XGetWindowProperty.restype = int_
    x11.XGetWindowAttributes.argtypes = [
        void_p, ulong, ctypes.POINTER(_XWindowAttributes)]
    x11.XGetWindowAttributes.restype = int_
    x11.XTranslateCoordinates.argtypes = [
        void_p, ulong, ulong, int_, int_, ctypes.POINTER(int_),
        ctypes.POINTER(int_), ctypes.POINTER(ulong)]
    x11.XTranslateCoordinates.restype = int_
    x11.XQueryPointer.argtypes = [
        void_p, ulong, ctypes.POINTER(ulong), ctypes.POINTER(ulong),
        ctypes.POINTER(int_), ctypes.POINTER(int_), ctypes.POINTER(int_),
        ctypes.POINTER(int_), ctypes.POINTER(uint)]
    x11.XQueryPointer.restype = int_
    x11.XGetImage.argtypes = [void_p, ulong, int_, int_, uint, uint, ulong, int_]
    x11.XGetImage.restype = ctypes.POINTER(_XImage)


def _load_x11() -> ctypes.CDLL:
    """Load libX11 once per process with typed signatures attached."""
    global _library
    with _library_lock:
        if _library is not None:
            return _library
        name = ctypes.util.find_library("X11") or "libX11.so.6"
        try:
            library = ctypes.CDLL(name)
        except OSError as exc:
            raise LinuxCaptureError(
                "libX11 could not be loaded, so screen scans are unavailable; "
                "install the X11 client library (for example libx11-6)."
            ) from exc
        try:
            _declare(library)
        except AttributeError as exc:  # pragma: no cover - ancient libX11
            raise LinuxCaptureError(
                "The installed libX11 is missing calls the screen scan needs."
            ) from exc
        _library = library
        return library


class _XErrorTrap:
    """Record Xlib protocol errors instead of letting Xlib end the process.

    Xlib's default error handler prints to stderr and calls ``exit()``.  A
    BadMatch from ``XGetImage`` on a window that was closed mid-scan would
    therefore take the whole engine down, so a handler is installed for the
    duration of one capture and the previous one is restored afterwards.

    The handler is process-global state, so :data:`_capture_lock` serialises
    captures rather than letting two of them install handlers over each other.
    """

    def __init__(self, x11: ctypes.CDLL, display: int) -> None:
        self._x11 = x11
        self._display = display
        self._callback = _ERROR_HANDLER(self._record)
        self._previous: object | None = None
        self.error_code = 0
        self.request_code = 0

    def _record(self, _display, event) -> int:
        if not self.error_code and event:
            self.error_code = int(event.contents.error_code)
            self.request_code = int(event.contents.request_code)
        return 0

    def __enter__(self) -> "_XErrorTrap":
        self._previous = self._x11.XSetErrorHandler(self._callback)
        return self

    def __exit__(self, *_exc) -> None:
        # Flush first: Xlib reports protocol errors asynchronously, so pending
        # errors must reach our handler before the old one is restored.
        try:
            self._x11.XSync(self._display, 0)
        except OSError:  # pragma: no cover - display already torn down
            pass
        self._x11.XSetErrorHandler(self._previous)

    def check(self, message: str) -> None:
        if self.error_code:
            raise LinuxCaptureError(
                f"{message} (X11 error {self.error_code} on request "
                f"{self.request_code})")

    def sync(self) -> None:
        self._x11.XSync(self._display, 0)


def x11_display_name() -> str:
    """The DISPLAY the scan will use, or an empty string when there is none."""
    return (os.environ.get("DISPLAY") or "").strip()


def x11_available() -> bool:
    """True when libX11 loads and its display actually opens."""
    if not x11_display_name():
        return False
    try:
        x11 = _load_x11()
    except LinuxCaptureError:
        return False
    display = x11.XOpenDisplay(x11_display_name().encode("utf-8"))
    if not display:
        return False
    x11.XCloseDisplay(display)
    return True


def _open_display(x11: ctypes.CDLL) -> int:
    name = x11_display_name()
    if not name:
        raise LinuxCaptureError(
            "No X display is available (DISPLAY is unset), so the screen scan "
            "cannot run; start EverQuest in an X11 or XWayland session.")
    display = x11.XOpenDisplay(name.encode("utf-8"))
    if not display:
        raise LinuxCaptureError(
            f"The X display {name} refused the connection needed for a "
            "screen scan; check DISPLAY and Xauthority.")
    return int(display)


def _window_property(x11: ctypes.CDLL, display: int, window: int,
                     name: str) -> int | None:
    """Read one 32-bit EWMH property, or None when the window lacks it."""
    atom = x11.XInternAtom(display, name.encode("ascii"), 1)
    if not atom:
        return None
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    items = ctypes.c_ulong()
    remaining = ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    status = x11.XGetWindowProperty(
        display, window, atom, 0, 1, 0, _ANY_PROPERTY_TYPE,
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(items), ctypes.byref(remaining), ctypes.byref(data))
    if status != _SUCCESS or not data:
        return None
    try:
        # Format 32 properties are delivered as an array of C long, not of
        # int32, which matters on 64-bit builds.
        if actual_format.value != 32 or items.value < 1:
            return None
        return int(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0])
    finally:
        x11.XFree(data)


def _window_property_list(x11: ctypes.CDLL, display: int, window: int,
                          name: str, limit: int = 256) -> list[int]:
    """Read a 32-bit EWMH window-list property such as _NET_CLIENT_LIST."""
    atom = x11.XInternAtom(display, name.encode("ascii"), 1)
    if not atom:
        return []
    actual_type = ctypes.c_ulong()
    actual_format = ctypes.c_int()
    items = ctypes.c_ulong()
    remaining = ctypes.c_ulong()
    data = ctypes.POINTER(ctypes.c_ubyte)()
    status = x11.XGetWindowProperty(
        display, window, atom, 0, limit, 0, _ANY_PROPERTY_TYPE,
        ctypes.byref(actual_type), ctypes.byref(actual_format),
        ctypes.byref(items), ctypes.byref(remaining), ctypes.byref(data))
    if status != _SUCCESS or not data:
        return []
    try:
        if actual_format.value != 32:
            return []
        values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
        return [int(values[index]) for index in range(min(items.value, limit))]
    finally:
        x11.XFree(data)


def _find_process_window(x11: ctypes.CDLL, display: int, root: int,
                         expected_process: str) -> int | None:
    """Find a managed window owned by ``expected_process``, or None.

    The scan can be started from Loremaster's own window, which makes the game
    the background window rather than the focused one. Searching the window
    manager's client list finds it anyway, and every candidate is still checked
    against /proc before any pixels are read, so this widens where the game may
    be without widening what may be captured.
    """
    for window in _window_property_list(x11, display, root, "_NET_CLIENT_LIST"):
        pid = _window_property(x11, display, window, "_NET_WM_PID")
        if not pid:
            continue
        try:
            if process_identity(int(pid)).matches(expected_process):
                return window
        except LinuxCaptureError:
            continue
    return None


def process_identity(pid: int) -> ProcessIdentity:
    """Read the public names of a process from ``/proc``.

    ``/proc/<pid>/comm`` is truncated at 15 bytes by the kernel, which is why
    ``argv[0]`` is read too; ``eqgame.exe`` fits in both.
    """
    pid = int(pid)
    if pid <= 0:
        raise LinuxCaptureError("The focused window reported an invalid process id.")
    try:
        with open(f"/proc/{pid}/comm", "rb") as handle:
            comm = handle.read(64).decode("utf-8", "replace").strip()
    except OSError as exc:
        raise LinuxCaptureError(
            "The focused window's process could not be identified; it may have "
            "already exited.") from exc
    argv0 = ""
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as handle:
            raw = handle.read(4096).split(b"\0")[0]
        argv0 = _basename(raw.decode("utf-8", "replace"))
    except OSError:
        argv0 = ""
    return ProcessIdentity(pid=pid, comm=_basename(comm), argv0=argv0)


def _basename(value: str) -> str:
    """Last path element, accepting Windows separators seen under Wine."""
    return re.split(r"[\\/]", value.strip())[-1].strip()


def _channel_offsets(image: _XImage) -> tuple[int, int, int]:
    """Byte position of blue, green and red inside one packed pixel."""
    bytes_per_pixel = image.bits_per_pixel // 8
    if image.depth < 24 or bytes_per_pixel not in (3, 4):
        raise LinuxCaptureError(
            f"The X display uses a {image.depth}-bit colour depth that is too "
            "coarse for text recognition; use a 24- or 32-bit display.")

    def offset(mask: int) -> int:
        if mask <= 0 or mask.bit_length() % 8 or (mask >> (mask.bit_length() - 8)) != 0xFF:
            raise LinuxCaptureError(
                "The X display uses an unsupported pixel layout for text "
                "recognition.")
        index = mask.bit_length() // 8 - 1
        # An MSBFirst server stores the most significant byte first, so the
        # channel index counts in from the opposite end of the pixel.
        if image.byte_order != _LSB_FIRST:
            return bytes_per_pixel - 1 - index
        return index

    return offset(image.blue_mask), offset(image.green_mask), offset(image.red_mask)


def _bgr_rows_from_ximage(image: _XImage) -> tuple[bytes, int]:
    """Repack an XImage into 4-byte-aligned top-down 24-bit BGR rows."""
    width, height = int(image.width), int(image.height)
    bytes_per_pixel = image.bits_per_pixel // 8
    blue, green, red = _channel_offsets(image)
    source_stride = int(image.bytes_per_line)
    if width <= 0 or height <= 0 or source_stride < width * bytes_per_pixel:
        raise LinuxCaptureError("The captured window returned an unusable image.")
    raw = ctypes.string_at(image.data, source_stride * height)
    stride = (width * 3 + 3) & ~3
    packed = bytearray(stride * height)
    destination = memoryview(packed)
    span = width * bytes_per_pixel
    for row in range(height):
        source = raw[row * source_stride:row * source_stride + span]
        target = destination[row * stride:row * stride + width * 3]
        # Strided slice assignment keeps the per-pixel work inside CPython's
        # C layer; a Python loop over 700k pixels would blow the OCR budget.
        target[0::3] = source[blue::bytes_per_pixel]
        target[1::3] = source[green::bytes_per_pixel]
        target[2::3] = source[red::bytes_per_pixel]
    return bytes(packed), stride


def capture_active_window_region(
        width: int, height: int, *, expected_process: str,
        cursor: tuple[int, int] | None = None) -> WindowRegionCapture:
    """Freeze a cursor-centred region of the verified active X11 window.

    The region is clamped to the window, never widened to the desktop, so the
    returned pixels always belong to ``expected_process`` and to nothing else.
    ``cursor`` exists for tests; production reads the pointer with
    XQueryPointer.
    """
    with _capture_session(width, height) as (x11, display, trap):
        root = x11.XDefaultRootWindow(display)
        active = _window_property(x11, display, root, "_NET_ACTIVE_WINDOW")
        trap.check("The focused window could not be read")
        if active:
            try:
                return _capture_verified_region(
                    x11, display, trap, int(active), expected_process, width,
                    height, cursor)
            except LinuxCaptureError:
                # The focused window is not the game. That is the normal case
                # when the scan is started from a button rather than a hotkey,
                # so look for the game instead of giving up.
                pass
        target = _find_process_window(x11, display, root, expected_process)
        if target is None:
            raise LinuxCaptureError(
                f"No {expected_process} window was found on this display. "
                "Start EverQuest under Wine or Proton on X11 or XWayland, open "
                "the Alt+Z window, and scan again.")
        return _capture_verified_region(
            x11, display, trap, target, expected_process, width, height,
            cursor)


def capture_window_region(window: int, width: int, height: int, *,
                          expected_process: str,
                          cursor: tuple[int, int] | None = None
                          ) -> WindowRegionCapture:
    """Same guarantees as :func:`capture_active_window_region` for a known id.

    A caller that already resolved the window still gets the ``/proc`` identity
    check, so no code path in this module can capture an unverified window.
    """
    with _capture_session(width, height) as (x11, display, trap):
        return _capture_verified_region(
            x11, display, trap, int(window), expected_process, width, height,
            cursor)


@contextmanager
def _capture_session(width: int, height: int):
    """Open a private display with protocol errors trapped, then close it."""
    if width <= 0 or height <= 0:
        raise LinuxCaptureError("The requested screen scan region is empty.")
    x11 = _load_x11()
    # Serialised because the Xlib error handler is process-global; captures are
    # user-triggered and take tens of milliseconds, so queueing costs nothing.
    with _capture_lock:
        display = _open_display(x11)
        try:
            with _XErrorTrap(x11, display) as trap:
                yield x11, display, trap
        finally:
            x11.XCloseDisplay(display)


def _capture_verified_region(x11: ctypes.CDLL, display: int, trap: _XErrorTrap,
                             window: int, expected_process: str, width: int,
                             height: int, cursor: tuple[int, int] | None
                             ) -> WindowRegionCapture:
    """Confirm the window's owning process, then and only then read pixels."""
    pid = _window_property(x11, display, window, "_NET_WM_PID")
    trap.check("The window closed before it could be verified")
    if not pid:
        raise LinuxCaptureError(
            "The focused window is not an X11 window that reports its "
            "process, so it cannot be verified; run EverQuest under Wine on "
            "X11 or XWayland and focus it before scanning.")
    identity = process_identity(pid)
    if not identity.matches(expected_process):
        raise LinuxCaptureError(
            f"Screen scan only captures {expected_process}; the focused window "
            f"belongs to {identity.described}.")
    return _capture_window_region(
        x11, display, trap, window, int(pid), width, height, cursor)


def _capture_window_region(x11: ctypes.CDLL, display: int, trap: _XErrorTrap,
                           window: int, pid: int, width: int, height: int,
                           cursor: tuple[int, int] | None) -> WindowRegionCapture:
    attributes = _XWindowAttributes()
    if not x11.XGetWindowAttributes(display, window, ctypes.byref(attributes)):
        raise LinuxCaptureError("The focused window's geometry is unavailable.")
    trap.check("The focused window's geometry could not be read")
    if attributes.map_state != _IS_VIEWABLE:
        raise LinuxCaptureError(
            "The EverQuest window is minimized or hidden, so there is nothing "
            "to scan; restore it and try again.")
    window_width, window_height = int(attributes.width), int(attributes.height)
    if window_width <= 0 or window_height <= 0:
        raise LinuxCaptureError("The focused window has no drawable area to scan.")

    # XGetWindowAttributes reports x/y against the parent, which is the window
    # manager frame, so ask the server for the real root-space origin.
    origin_x, origin_y = ctypes.c_int(), ctypes.c_int()
    child = ctypes.c_ulong()
    if not x11.XTranslateCoordinates(
            display, window, x11.XDefaultRootWindow(display), 0, 0,
            ctypes.byref(origin_x), ctypes.byref(origin_y), ctypes.byref(child)):
        raise LinuxCaptureError(
            "The focused window is on a different X screen than the pointer.")
    trap.check("The focused window's position could not be read")

    if cursor is None:
        cursor_x, cursor_y = _query_pointer(x11, display, trap)
    else:
        cursor_x, cursor_y = int(cursor[0]), int(cursor[1])

    region_width = min(int(width), window_width)
    region_height = min(int(height), window_height)
    left = origin_x.value + max(0, min(
        cursor_x - origin_x.value - region_width // 2,
        window_width - region_width))
    top = origin_y.value + max(0, min(
        cursor_y - origin_y.value - region_height // 2,
        window_height - region_height))

    image = x11.XGetImage(
        display, window, left - origin_x.value, top - origin_y.value,
        region_width, region_height, _ALL_PLANES, _Z_PIXMAP)
    trap.sync()
    if not image:
        trap.check("The EverQuest window could not be read")
        raise LinuxCaptureError(
            "The EverQuest window could not be read; try windowed or "
            "borderless mode instead of exclusive fullscreen.")
    try:
        pixels, stride = _bgr_rows_from_ximage(image.contents)
    finally:
        destroy = ctypes.cast(
            image.contents.f.destroy_image,
            ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_XImage)))
        destroy(image)

    screen = x11.XDefaultScreen(display)
    return WindowRegionCapture(
        cursor_x=cursor_x, cursor_y=cursor_y,
        region_left=left, region_top=top,
        region_width=region_width, region_height=region_height,
        window=window, pid=pid,
        # An X11 root window always starts at 0,0 even across several monitors,
        # unlike the Windows virtual desktop, which can have negative origins.
        screen_left=0, screen_top=0,
        screen_width=int(x11.XDisplayWidth(display, screen)),
        screen_height=int(x11.XDisplayHeight(display, screen)),
        pixels=pixels, stride=stride)


def _query_pointer(x11: ctypes.CDLL, display: int,
                   trap: _XErrorTrap) -> tuple[int, int]:
    """Read the pointer position. This never moves or synthesises input."""
    root_return, child_return = ctypes.c_ulong(), ctypes.c_ulong()
    root_x, root_y = ctypes.c_int(), ctypes.c_int()
    window_x, window_y = ctypes.c_int(), ctypes.c_int()
    mask = ctypes.c_uint()
    root = x11.XDefaultRootWindow(display)
    if not x11.XQueryPointer(
            display, root, ctypes.byref(root_return), ctypes.byref(child_return),
            ctypes.byref(root_x), ctypes.byref(root_y),
            ctypes.byref(window_x), ctypes.byref(window_y), ctypes.byref(mask)):
        raise LinuxCaptureError(
            "The mouse pointer is on another X screen, so the hovered region "
            "cannot be located.")
    trap.check("The mouse pointer position could not be read")
    return int(root_x.value), int(root_y.value)


# --------------------------------------------------------------------------
# Image handoff and Tesseract
# --------------------------------------------------------------------------

def bgr_from_bmp(bmp_bytes: bytes) -> tuple[bytes, int, int, int]:
    """Recover BGR rows from the 24-bit BMP the capture layer hands around.

    The immutable capture that crosses into the OCR worker carries a BMP
    because that is what Windows' decoder wants.  Tesseract needs an upscaled
    image instead, so the worker unpacks the same bytes rather than the capture
    dataclass growing a second, Linux-only pixel field.
    """
    if len(bmp_bytes) < 54 or bmp_bytes[:2] != b"BM":
        raise LinuxCaptureError("The captured image is not a readable bitmap.")
    offset = int.from_bytes(bmp_bytes[10:14], "little")
    header_size = int.from_bytes(bmp_bytes[14:18], "little")
    width = int.from_bytes(bmp_bytes[18:22], "little", signed=True)
    raw_height = int.from_bytes(bmp_bytes[22:26], "little", signed=True)
    bit_count = int.from_bytes(bmp_bytes[28:30], "little")
    compression = int.from_bytes(bmp_bytes[30:34], "little")
    height = abs(raw_height)
    stride = (width * 3 + 3) & ~3
    if (header_size < 40 or bit_count != 24 or compression != 0
            or width <= 0 or height <= 0
            or offset + stride * height > len(bmp_bytes)):
        raise LinuxCaptureError(
            "The captured image is not the uncompressed 24-bit bitmap the "
            "text recogniser expects.")
    body = bmp_bytes[offset:offset + stride * height]
    if raw_height > 0:
        # Positive height means bottom-up rows; Tesseract needs them top-down.
        body = b"".join(
            body[row * stride:(row + 1) * stride]
            for row in range(height - 1, -1, -1))
    return body, width, height, stride


def ppm_from_bgr(pixels: bytes, width: int, height: int, stride: int,
                 scale: int = 1) -> bytes:
    """Return a binary PPM, optionally nearest-neighbour upscaled.

    Upscaling is not cosmetic: at native size Tesseract misreads EverQuest's
    compact digits (a measured ``14m`` came back as ``Ldn``), and it has no
    resampling of its own, so the same integer factor the Windows path asks
    BitmapTransform for is applied here.  Every inner step is a strided slice
    assignment so a full 960x720 region stays well inside the OCR timeout.
    """
    scale = max(1, int(scale))
    if width <= 0 or height <= 0 or stride < width * 3:
        raise LinuxCaptureError("The captured image has unusable dimensions.")
    if len(pixels) < stride * height:
        raise LinuxCaptureError("The captured image is shorter than its header.")
    row_bytes = width * scale * 3
    body = bytearray(row_bytes * height * scale)
    view = memoryview(body)
    row_buffer = bytearray(row_bytes)
    row_view = memoryview(row_buffer)
    for row in range(height):
        source = pixels[row * stride:row * stride + width * 3]
        blue, green, red = source[0::3], source[1::3], source[2::3]
        for column in range(scale):
            row_view[3 * column::3 * scale] = red
            row_view[3 * column + 1::3 * scale] = green
            row_view[3 * column + 2::3 * scale] = blue
        start = row * scale * row_bytes
        for repeat in range(scale):
            view[start + repeat * row_bytes:start + (repeat + 1) * row_bytes] = row_view
    header = f"P6\n{width * scale} {height * scale}\n255\n".encode("ascii")
    return header + bytes(body)


def tesseract_executable() -> str:
    """Absolute path to the tesseract CLI, or an empty string when absent."""
    return shutil.which("tesseract") or ""


def tesseract_languages() -> frozenset[str]:
    """Language codes tesseract reports as installed; empty when unknown."""
    executable = tesseract_executable()
    if not executable:
        return frozenset()
    try:
        completed = subprocess.run(
            [executable, "--list-langs"], stdin=subprocess.DEVNULL,
            capture_output=True, timeout=LIST_LANGS_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError):
        return frozenset()
    # The banner line goes to stderr on some builds and stdout on others.
    text = (completed.stdout + b"\n" + completed.stderr).decode("utf-8", "replace")
    return frozenset(
        line.strip() for line in text.splitlines()
        if re.fullmatch(r"[A-Za-z_]{3,32}", line.strip()))


def tesseract_available() -> bool:
    """True when tesseract and the configured language data are both present."""
    if not tesseract_executable():
        return False
    try:
        wanted = set(ocr_language().split("+"))
    except LinuxCaptureError:
        return False
    return wanted.issubset(tesseract_languages())


def ocr_language() -> str:
    value = (os.environ.get(OCR_LANGUAGE_ENV) or "").strip()
    if not value:
        return DEFAULT_OCR_LANGUAGE
    if not re.fullmatch(r"[A-Za-z_]{3,32}(?:\+[A-Za-z_]{3,32})*", value):
        raise LinuxCaptureError(
            f"{OCR_LANGUAGE_ENV} must be Tesseract language codes such as "
            "'eng' or 'eng+deu'.")
    return value


def ocr_page_segmentation() -> str:
    """Optional --psm override; empty string means Tesseract's own default."""
    value = (os.environ.get(OCR_PSM_ENV) or "").strip()
    if not value:
        return ""
    if not re.fullmatch(r"(?:[0-9]|1[0-3])", value):
        raise LinuxCaptureError(
            f"{OCR_PSM_ENV} must be a Tesseract page segmentation mode "
            "between 0 and 13.")
    return value


def crop_bgr(pixels: bytes, width: int, height: int, stride: int,
             left: int, top: int, crop_width: int, crop_height: int
             ) -> tuple[bytes, int, int, int]:
    """Return a sub-rectangle of packed BGR rows, clamped to the source."""
    left = max(0, min(int(left), width))
    top = max(0, min(int(top), height))
    crop_width = max(1, min(int(crop_width), width - left))
    crop_height = max(1, min(int(crop_height), height - top))
    out_stride = (crop_width * 3 + 3) & ~3
    out = bytearray(out_stride * crop_height)
    for row in range(crop_height):
        start = (top + row) * stride + left * 3
        out[row * out_stride:row * out_stride + crop_width * 3] = (
            pixels[start:start + crop_width * 3])
    return bytes(out), crop_width, crop_height, out_stride


def recognize_lines(pixels: bytes, width: int, height: int, stride: int, *,
                    scale: int = 2,
                    cancel_event: threading.Event | None = None,
                    timeout: float = TESSERACT_TIMEOUT_SECONDS,
                    ) -> list[TesseractLine]:
    """OCR already-frozen pixels with one bounded tesseract process."""
    scale = max(1, int(scale))
    image = ppm_from_bgr(pixels, width, height, stride, scale)
    payload = _run_tesseract(image, cancel_event=cancel_event, timeout=timeout)
    return _lines_from_tsv(payload, scale)


def _tesseract_arguments() -> list[str]:
    executable = tesseract_executable()
    if not executable:
        raise LinuxCaptureError(
            "Tesseract is not installed, so screen text cannot be read; "
            "install the tesseract OCR package and try again.")
    arguments = [executable, "-", "-", "-l", ocr_language()]
    page_mode = ocr_page_segmentation()
    if page_mode:
        arguments += ["--psm", page_mode]
    # Requesting TSV with -c rather than the "tsv" config file keeps working
    # when a player points TESSDATA_PREFIX at a bare directory of traineddata,
    # which has no configs/ beside it.
    return arguments + ["-c", "tessedit_create_tsv=1"]


def _language_failure() -> str:
    """Turn a missing traineddata file into an actionable sentence.

    "Tesseract is installed" and "screen scans work" are different facts: the
    distributions all ship language models as separate packages, so naming the
    exact package is the difference between a fixable message and a dead end.
    """
    installed = tesseract_languages()
    if not installed:
        return ""
    missing = [code for code in ocr_language().split("+") if code not in installed]
    if not missing:
        return ""
    code = missing[0]
    return (f"Tesseract has no {', '.join(missing)} language data, so screen "
            f"text cannot be read; install it (tesseract-data-{code} on Arch, "
            f"tesseract-ocr-{code} on Debian/Ubuntu, tesseract-langpack-{code} "
            f"on Fedora) or set {OCR_LANGUAGE_ENV} to a language you have.")


def readiness_problem() -> str:
    """One actionable sentence when a Linux scan cannot work yet, else ``""``.

    Cheap enough to call at startup so a player learns that OCR is unavailable
    before pressing the hotkey rather than after.  It reports only what is
    verifiable without capturing anything: the tool, its language data and the
    display.
    """
    if not tesseract_executable():
        return ("Tesseract is not installed, so screen scans are unavailable; "
                "install it with your package manager (tesseract-ocr on "
                "Debian/Ubuntu, tesseract on Arch and Fedora).")
    try:
        missing = _language_failure()
    except LinuxCaptureError as exc:
        return str(exc)
    if missing:
        return missing
    if not x11_display_name():
        return ("No X display is available (DISPLAY is unset), so screen scans "
                "are unavailable; run Loremaster in an X11 or XWayland session.")
    return ""


def _abandon(process: subprocess.Popen) -> None:
    """Kill the recogniser, anything it spawned, and reap it promptly.

    ``Popen.kill()`` signals only the direct child.  A child that spawned its
    own -- a shell wrapper, a distribution's tesseract shim -- leaves a
    grandchild holding the inherited stdout pipe open, so the ``communicate()``
    that follows blocks until that grandchild finishes: the timeout guardrail
    ends up waiting out the very process it just gave up on.  Signalling the
    process group closes every copy of the pipe at once.
    """
    try:
        # The child leads its own session, so its pid is its process group.
        os.killpg(process.pid, signal.SIGKILL)
    except (AttributeError, OSError):
        # Windows has no process groups, and a child that already exited has no
        # group left to signal; the direct kill covers both.
        try:
            process.kill()
        except OSError:
            pass
    try:
        process.communicate(timeout=KILL_REAP_SECONDS)
    except subprocess.TimeoutExpired:
        # Something is unkillable (uninterruptible I/O). Abandoning the pipes
        # still beats blocking the caller that asked us to stop waiting.
        pass


def _run_tesseract(image: bytes, *, cancel_event: threading.Event | None,
                   timeout: float) -> str:
    """Feed one image through tesseract with the PowerShell path's guardrails."""
    if cancel_event is not None and cancel_event.is_set():
        raise LinuxOcrCancelled("Screen text recognition was cancelled.")
    arguments = _tesseract_arguments()
    try:
        process = subprocess.Popen(
            arguments, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            # Its own session, so a wedged recogniser and its children can be
            # killed as one group without ever signalling Loremaster itself.
            start_new_session=True)
    except OSError as exc:
        raise LinuxCaptureError(
            "Tesseract could not be started, so screen text cannot be read."
        ) from exc
    deadline = time.monotonic() + max(1.0, float(timeout))
    pending = image
    try:
        while True:
            if cancel_event is not None and cancel_event.is_set():
                _abandon(process)
                raise LinuxOcrCancelled("Screen text recognition was cancelled.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _abandon(process)
                raise LinuxCaptureError(
                    "Tesseract timed out reading the captured region; type or "
                    "copy the text instead.")
            try:
                # Input may only be supplied once; a timed-out communicate()
                # resumes the unfinished write on the next call.
                stdout, stderr = process.communicate(
                    input=pending, timeout=min(0.05, remaining))
                break
            except subprocess.TimeoutExpired:
                pending = None
                continue
    except LinuxCaptureError:
        raise
    except LinuxOcrCancelled:
        raise
    except (OSError, ValueError) as exc:
        _abandon(process)
        raise LinuxCaptureError(
            "Tesseract could not read the captured region.") from exc
    if process.returncode:
        detail = _language_failure()
        if not detail:
            detail = re.sub(
                r"\s+", " ", stderr.decode("utf-8", "replace").strip())[:180]
        raise LinuxCaptureError(
            detail or "Tesseract could not read the captured region.")
    if len(stdout) > MAX_TESSERACT_STDOUT_BYTES:
        raise LinuxCaptureError("Tesseract returned more text than a screen scan should.")
    return stdout.decode("utf-8", "replace")


def _lines_from_tsv(payload: str, scale: int) -> list[TesseractLine]:
    """Rebuild text lines from tesseract's per-word TSV rows.

    Word-level rows are grouped into their reported line and the bounding box
    is the union of the words, matching how the Windows worker derives a line
    box from OcrWord rectangles.  Boxes are divided back down by ``scale`` so
    downstream ranking still sees native captured pixels.
    """
    scale = max(1, int(scale))
    grouped: dict[tuple[str, str, str], list] = {}
    order: list[tuple[str, str, str]] = []
    for row in payload.splitlines()[1:]:
        cells = row.split("\t")
        if len(cells) < 12 or cells[0] != "5":
            continue
        text = cells[11].strip()
        if not text:
            continue
        try:
            left, top = int(cells[6]), int(cells[7])
            word_width, word_height = int(cells[8]), int(cells[9])
        except ValueError:
            continue
        key = (cells[2], cells[3], cells[4])
        entry = grouped.get(key)
        if entry is None:
            if len(order) >= MAX_TESSERACT_LINES:
                break
            grouped[key] = [left, top, left + word_width, top + word_height, [text]]
            order.append(key)
            continue
        entry[0] = min(entry[0], left)
        entry[1] = min(entry[1], top)
        entry[2] = max(entry[2], left + word_width)
        entry[3] = max(entry[3], top + word_height)
        entry[4].append(text)
    lines: list[TesseractLine] = []
    for key in order:
        left, top, right, bottom, words = grouped[key]
        lines.append(TesseractLine(
            text=" ".join(words)[:MAX_TESSERACT_LINE_CHARS],
            x=left / scale, y=top / scale,
            width=(right - left) / scale, height=(bottom - top) / scale))
    return lines


__all__ = [
    "DEFAULT_OCR_LANGUAGE",
    "LinuxCaptureError",
    "LinuxOcrCancelled",
    "OCR_LANGUAGE_ENV",
    "OCR_PSM_ENV",
    "ProcessIdentity",
    "TESSERACT_TIMEOUT_SECONDS",
    "TesseractLine",
    "WindowRegionCapture",
    "bgr_from_bmp",
    "capture_active_window_region",
    "capture_window_region",
    "ocr_language",
    "ocr_page_segmentation",
    "ppm_from_bgr",
    "process_identity",
    "readiness_problem",
    "recognize_lines",
    "tesseract_available",
    "tesseract_executable",
    "tesseract_languages",
    "x11_available",
    "x11_display_name",
]
