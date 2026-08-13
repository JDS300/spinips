"""Tests for the X11 + Tesseract backend that Linux screen scans use.

The pure parsing and packing tests run everywhere, including a headless
Windows or CI runner.  The round-trip tests need a live X display and a
tesseract that can load the configured language, so they announce themselves
as skipped rather than silently passing when either is missing.
"""

import ctypes
import os
import struct
import sys
import threading
import time
import unittest
from difflib import SequenceMatcher
from pathlib import Path
from unittest import mock


LOREMASTER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(LOREMASTER_DIR))

import hover_ocr  # noqa: E402
import linux_capture  # noqa: E402
from linux_capture import (  # noqa: E402
    LinuxCaptureError,
    LinuxOcrCancelled,
    ProcessIdentity,
    bgr_from_bmp,
    ocr_language,
    ocr_page_segmentation,
    ppm_from_bgr,
    process_identity,
)


KNOWN_LINES = ("Cloak of Flames", "Adaptive Cazic-Thule", "6d 23h 14m 05s Group 4")

# Latin-script text models, best first.  The shipped default is always "eng";
# a substitute is used only so the round trip can still prove capture -> PPM ->
# tesseract -> parsed lines on a machine that lacks the English model.  "osd"
# is script detection rather than a text model, so it can never stand in.
LATIN_SCRIPT_LANGUAGES = ("eng", "afr", "deu", "nld", "fra", "spa", "ita",
                          "por", "cat", "dan", "nor", "swe", "lat")
# A wrong-language Latin model still reads Latin glyphs, just less well: the
# measured worst case for these lines under "afr" was 0.73 similarity ("6d 23h
# 14m 05s Group 4" came back as "Ed 22h 1dm OEs Broup 4").  0.65 keeps margin
# under that while still failing on genuinely wrong text, which scores far
# lower.  With "eng" the assertions below demand exact recognition instead.
FALLBACK_SIMILARITY = 0.65


def _usable_ocr_language() -> str:
    """The best Latin-script model installed, or "" when there is none."""
    if not linux_capture.tesseract_executable():
        return ""
    installed = linux_capture.tesseract_languages()
    return next((code for code in LATIN_SCRIPT_LANGUAGES if code in installed), "")


# These tests create a real, mapped X11 window. That is unavoidable -- XGetImage
# needs one -- but it means running the suite on a desktop pops windows onto
# whatever the user is doing, and the sample text ends in "Group 4", which
# looks alarmingly like a real overlay. They are therefore opt-in: CI and
# anyone deliberately verifying the capture path set LOREMASTER_X11_WINDOW_TESTS=1.
WINDOW_TESTS_ALLOWED = os.environ.get("LOREMASTER_X11_WINDOW_TESTS") == "1"

X11_READY = os.name != "nt" and linux_capture.x11_available()
OCR_LANGUAGE = _usable_ocr_language()
TESSERACT_READY = bool(OCR_LANGUAGE)
ENGLISH_READY = OCR_LANGUAGE == linux_capture.DEFAULT_OCR_LANGUAGE


def tsv_row(level, block, paragraph, line, word, left, top, width, height, text):
    return "\t".join(str(cell) for cell in (
        level, 1, block, paragraph, line, word, left, top, width, height,
        90.0, text))


def make_bgr(width, height, colour=(11, 22, 33)):
    """Packed BGR rows with the 4-byte aligned stride the capture layer uses."""
    stride = (width * 3 + 3) & ~3
    pixels = bytearray(stride * height)
    for row in range(height):
        for column in range(width):
            offset = row * stride + column * 3
            pixels[offset:offset + 3] = bytes((
                (colour[0] + row) % 256, (colour[1] + column) % 256,
                (colour[2] + row + column) % 256))
    return bytes(pixels), stride


class ProcessIdentityTests(unittest.TestCase):
    def test_either_public_name_satisfies_the_expected_process(self):
        wine_loader = ProcessIdentity(pid=7, comm="eqgame.exe", argv0="wine-preloader")
        wine_argv = ProcessIdentity(pid=7, comm="wine", argv0="eqgame.exe")
        for identity in (wine_loader, wine_argv):
            self.assertTrue(identity.matches("eqgame.exe"))
            self.assertTrue(identity.matches("EQGame.EXE"))
            self.assertFalse(identity.matches("firefox"))
            self.assertFalse(identity.matches(""))

    def test_windows_style_command_lines_reduce_to_the_executable(self):
        self.assertEqual(linux_capture._basename(r"C:\EQ\eqgame.exe"), "eqgame.exe")
        self.assertEqual(linux_capture._basename("/opt/wine/bin/wine"), "wine")
        self.assertEqual(linux_capture._basename("Z:\\games\\EQ\\eqgame.exe "), "eqgame.exe")

    def test_description_never_leaks_an_empty_string_into_an_error(self):
        self.assertEqual(ProcessIdentity(9, "", "").described, "pid 9")
        self.assertEqual(ProcessIdentity(9, "", "eqgame.exe").described, "eqgame.exe")

    @unittest.skipUnless(os.name == "posix", "/proc identity requires Linux")
    def test_this_process_identifies_itself_from_proc(self):
        identity = process_identity(os.getpid())
        self.assertEqual(identity.pid, os.getpid())
        self.assertTrue(identity.comm)
        self.assertTrue(identity.matches(identity.comm))

    def test_impossible_pid_fails_without_touching_the_filesystem(self):
        with self.assertRaises(LinuxCaptureError) as caught:
            process_identity(0)
        self.assertIn("process id", str(caught.exception))


class BitmapHandoffTests(unittest.TestCase):
    def test_round_trips_the_top_down_bmp_the_capture_layer_produces(self):
        pixels, stride = make_bgr(7, 5)
        bmp = hover_ocr._bmp_from_bgr(pixels, 7, 5, stride)
        recovered, width, height, recovered_stride = bgr_from_bmp(bmp)
        self.assertEqual((width, height, recovered_stride), (7, 5, stride))
        self.assertEqual(recovered, pixels)

    def test_bottom_up_bitmaps_are_flipped_into_top_down_rows(self):
        pixels, stride = make_bgr(4, 3)
        rows = [pixels[index * stride:(index + 1) * stride] for index in range(3)]
        body = b"".join(reversed(rows))
        header = struct.pack("<2sIHHI", b"BM", 54 + len(body), 0, 0, 54)
        # A positive biHeight is the bottom-up convention.
        info = struct.pack("<IiiHHIIiiII", 40, 4, 3, 1, 24, 0, len(body),
                           3780, 3780, 0, 0)
        recovered, width, height, _stride = bgr_from_bmp(header + info + body)
        self.assertEqual((width, height), (4, 3))
        self.assertEqual(recovered, pixels)

    def test_unsupported_bitmaps_fail_with_a_specific_message(self):
        pixels, stride = make_bgr(4, 3)
        good = hover_ocr._bmp_from_bgr(pixels, 4, 3, stride)
        for label, payload in (
                ("truncated", good[:40]),
                ("not a bitmap", b"PNG" + good[3:]),
                ("compressed", good[:30] + struct.pack("<I", 3) + good[34:]),
                ("32-bit", good[:28] + struct.pack("<H", 32) + good[30:]),
                ("short body", good[:len(good) - 8])):
            with self.subTest(label), self.assertRaises(LinuxCaptureError):
                bgr_from_bmp(payload)


class PpmScalingTests(unittest.TestCase):
    def test_unscaled_ppm_reorders_bgr_into_rgb_without_padding(self):
        pixels, stride = make_bgr(3, 2)
        ppm = ppm_from_bgr(pixels, 3, 2, stride, 1)
        self.assertTrue(ppm.startswith(b"P6\n3 2\n255\n"))
        body = ppm[len(b"P6\n3 2\n255\n"):]
        self.assertEqual(len(body), 3 * 2 * 3)
        for row in range(2):
            for column in range(3):
                source = pixels[row * stride + column * 3:row * stride + column * 3 + 3]
                target = body[(row * 3 + column) * 3:(row * 3 + column) * 3 + 3]
                self.assertEqual(target, bytes(reversed(source)))

    def test_integer_upscale_replicates_every_pixel_exactly(self):
        pixels, stride = make_bgr(2, 2)
        ppm = ppm_from_bgr(pixels, 2, 2, stride, 3)
        header = b"P6\n6 6\n255\n"
        self.assertTrue(ppm.startswith(header))
        body = ppm[len(header):]
        self.assertEqual(len(body), 6 * 6 * 3)
        for row in range(2):
            for column in range(2):
                blue, green, red = pixels[
                    row * stride + column * 3:row * stride + column * 3 + 3]
                for dy in range(3):
                    for dx in range(3):
                        index = ((row * 3 + dy) * 6 + column * 3 + dx) * 3
                        self.assertEqual(body[index:index + 3],
                                         bytes((red, green, blue)))

    def test_unusable_dimensions_are_refused_instead_of_guessed(self):
        pixels, stride = make_bgr(4, 2)
        for label, args in (
                ("zero width", (pixels, 0, 2, stride)),
                ("stride below row", (pixels, 4, 2, 6)),
                ("short buffer", (pixels[:8], 4, 2, stride))):
            with self.subTest(label), self.assertRaises(LinuxCaptureError):
                ppm_from_bgr(*args)


class ChannelLayoutTests(unittest.TestCase):
    def _image(self, **overrides):
        fields = dict(depth=24, bits_per_pixel=32, byte_order=0,
                      blue_mask=0x0000FF, green_mask=0x00FF00, red_mask=0xFF0000)
        fields.update(overrides)
        return linux_capture._XImage(**fields)

    def test_little_endian_truecolor_is_read_as_bgrx(self):
        self.assertEqual(linux_capture._channel_offsets(self._image()), (0, 1, 2))

    def test_big_endian_server_counts_channels_from_the_other_end(self):
        self.assertEqual(
            linux_capture._channel_offsets(self._image(byte_order=1)), (3, 2, 1))

    def test_packed_24_bit_rows_need_no_padding_byte(self):
        self.assertEqual(
            linux_capture._channel_offsets(self._image(bits_per_pixel=24)), (0, 1, 2))

    def test_reversed_channel_order_is_followed_not_assumed(self):
        self.assertEqual(linux_capture._channel_offsets(self._image(
            blue_mask=0xFF0000, green_mask=0x00FF00, red_mask=0x0000FF)), (2, 1, 0))

    def test_low_colour_and_odd_layouts_fail_with_an_honest_message(self):
        with self.assertRaises(LinuxCaptureError) as caught:
            linux_capture._channel_offsets(self._image(depth=16, bits_per_pixel=16))
        self.assertIn("16-bit", str(caught.exception))
        with self.assertRaises(LinuxCaptureError):
            linux_capture._channel_offsets(self._image(red_mask=0x0F0000))


class TsvParsingTests(unittest.TestCase):
    HEADER = ("level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\t"
              "left\ttop\twidth\theight\tconf\ttext")

    def test_words_become_one_line_with_the_union_of_their_boxes(self):
        payload = "\n".join((
            self.HEADER,
            tsv_row(1, 0, 0, 0, 0, 0, 0, 400, 200, ""),
            tsv_row(4, 1, 1, 1, 0, 40, 60, 200, 24, ""),
            tsv_row(5, 1, 1, 1, 1, 40, 60, 90, 24, "Cloak"),
            tsv_row(5, 1, 1, 1, 2, 140, 62, 30, 20, "of"),
            tsv_row(5, 1, 1, 1, 3, 180, 60, 120, 26, "Flames"),
            tsv_row(5, 1, 1, 2, 1, 40, 120, 100, 22, "No"),
            tsv_row(5, 1, 1, 2, 2, 150, 120, 90, 22, "Trade"),
        ))
        lines = linux_capture._lines_from_tsv(payload, 2)
        self.assertEqual([line.text for line in lines], ["Cloak of Flames", "No Trade"])
        # Boxes divide back down by the OCR upscale so ranking sees native pixels.
        self.assertEqual((lines[0].x, lines[0].y), (20.0, 30.0))
        self.assertEqual((lines[0].width, lines[0].height), (130.0, 13.0))
        self.assertEqual((lines[1].x, lines[1].y), (20.0, 60.0))

    def test_blank_words_unparsable_boxes_and_header_are_ignored(self):
        payload = "\n".join((
            self.HEADER,
            tsv_row(5, 1, 1, 1, 1, 10, 10, 20, 10, "   "),
            tsv_row(5, 1, 1, 1, 2, "x", 10, 20, 10, "Skipped"),
            tsv_row(5, 1, 1, 1, 3, 40, 10, 20, 10, "Kept"),
            "short\trow",
        ))
        lines = linux_capture._lines_from_tsv(payload, 1)
        self.assertEqual([line.text for line in lines], ["Kept"])

    def test_line_and_character_caps_bound_a_hostile_payload(self):
        rows = [self.HEADER]
        for index in range(linux_capture.MAX_TESSERACT_LINES + 40):
            rows.append(tsv_row(5, 1, 1, index, 1, 0, index * 10, 20, 10, "Row"))
        rows.append(tsv_row(5, 1, 1, 0, 2, 30, 0, 20, 10, "x" * 400))
        lines = linux_capture._lines_from_tsv("\n".join(rows), 1)
        self.assertEqual(len(lines), linux_capture.MAX_TESSERACT_LINES)
        self.assertLessEqual(
            max(len(line.text) for line in lines),
            linux_capture.MAX_TESSERACT_LINE_CHARS)

    def test_empty_output_yields_no_invented_lines(self):
        self.assertEqual(linux_capture._lines_from_tsv("", 2), [])
        self.assertEqual(linux_capture._lines_from_tsv(self.HEADER, 2), [])


class OcrConfigurationTests(unittest.TestCase):
    def test_language_defaults_to_english_and_accepts_explicit_codes(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(linux_capture.OCR_LANGUAGE_ENV, None)
            self.assertEqual(ocr_language(), "eng")
        with mock.patch.dict(os.environ, {linux_capture.OCR_LANGUAGE_ENV: "eng+deu"}):
            self.assertEqual(ocr_language(), "eng+deu")

    def test_hostile_language_and_mode_overrides_are_refused(self):
        with mock.patch.dict(os.environ, {linux_capture.OCR_LANGUAGE_ENV: "eng; rm -rf /"}):
            with self.assertRaises(LinuxCaptureError) as caught:
                ocr_language()
            self.assertIn(linux_capture.OCR_LANGUAGE_ENV, str(caught.exception))
        with mock.patch.dict(os.environ, {linux_capture.OCR_PSM_ENV: "99"}):
            with self.assertRaises(LinuxCaptureError):
                ocr_page_segmentation()

    def test_page_segmentation_defaults_to_tesseracts_own_choice(self):
        # What is under test is how the arguments are assembled, so the
        # executable is pinned: whether this machine has tesseract installed
        # is a different fact, covered by the readiness tests.
        installed = mock.patch.object(
            linux_capture, "tesseract_executable", lambda: "/usr/bin/tesseract")
        with installed, mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(linux_capture.OCR_PSM_ENV, None)
            self.assertEqual(ocr_page_segmentation(), "")
            self.assertNotIn("--psm", linux_capture._tesseract_arguments())
        with installed, mock.patch.dict(os.environ, {linux_capture.OCR_PSM_ENV: "11"}):
            arguments = linux_capture._tesseract_arguments()
        self.assertEqual(arguments[-2:], ["-c", "tessedit_create_tsv=1"])
        self.assertIn("--psm", arguments)
        self.assertIn("11", arguments)


def _x11_library_loads() -> bool:
    """Whether libX11 is present, independent of any display being open."""
    try:
        linux_capture._load_x11()
    except LinuxCaptureError:
        return False
    return True


class FailureShapeTests(unittest.TestCase):
    @unittest.skipUnless(_x11_library_loads(),
                         "the DISPLAY check is only reached once libX11 loads")
    def test_missing_display_is_reported_not_crashed(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            self.assertEqual(linux_capture.x11_display_name(), "")
            self.assertFalse(linux_capture.x11_available())
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture.capture_active_window_region(
                    64, 64, expected_process="eqgame.exe")
        self.assertIn("DISPLAY", str(caught.exception))

    def test_empty_region_request_is_refused_before_opening_a_display(self):
        with self.assertRaises(LinuxCaptureError):
            linux_capture.capture_active_window_region(
                0, 64, expected_process="eqgame.exe")

    def test_missing_tesseract_names_the_package_to_install(self):
        with mock.patch.object(linux_capture, "tesseract_executable", lambda: ""):
            self.assertFalse(linux_capture.tesseract_available())
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture._tesseract_arguments()
        self.assertIn("tesseract", str(caught.exception).casefold())

    def test_already_cancelled_work_never_starts_a_process(self):
        cancelled = threading.Event()
        cancelled.set()
        with mock.patch.object(linux_capture.subprocess, "Popen") as popen:
            with self.assertRaises(LinuxOcrCancelled):
                linux_capture._run_tesseract(
                    b"P6\n1 1\n255\n\x00\x00\x00", cancel_event=cancelled,
                    timeout=1.0)
        popen.assert_not_called()

    def test_a_missing_language_is_explained_before_tesseracts_own_stderr(self):
        with mock.patch.object(linux_capture, "tesseract_languages",
                               lambda: frozenset({"afr", "osd"})):
            detail = linux_capture._language_failure()
        self.assertIn("eng", detail)
        self.assertIn(linux_capture.OCR_LANGUAGE_ENV, detail)
        # "tesseract is installed" and "OCR works" are different facts, so the
        # message has to name the package that closes the gap.
        for package in ("tesseract-data-eng", "tesseract-ocr-eng",
                        "tesseract-langpack-eng"):
            self.assertIn(package, detail)
        # The engine truncates reported errors at 240 characters.
        self.assertLessEqual(len(detail), 240)

    def test_readiness_reports_each_missing_piece_before_a_scan_is_tried(self):
        with mock.patch.object(linux_capture, "tesseract_executable", lambda: ""):
            missing_tool = linux_capture.readiness_problem()
        self.assertIn("not installed", missing_tool)
        self.assertIn("tesseract", missing_tool.casefold())

        with mock.patch.object(linux_capture, "tesseract_executable",
                               lambda: "/usr/bin/tesseract"), \
                mock.patch.object(linux_capture, "tesseract_languages",
                                  lambda: frozenset({"afr"})):
            missing_language = linux_capture.readiness_problem()
        self.assertIn("tesseract-data-eng", missing_language)

        with mock.patch.object(linux_capture, "tesseract_executable",
                               lambda: "/usr/bin/tesseract"), \
                mock.patch.object(linux_capture, "tesseract_languages",
                                  lambda: frozenset({"eng"})), \
                mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("DISPLAY", None)
            self.assertIn("DISPLAY", linux_capture.readiness_problem())
            os.environ["DISPLAY"] = ":0"
            self.assertEqual(linux_capture.readiness_problem(), "")

    @unittest.skipUnless(os.name == "posix", "process guardrails need a POSIX shell")
    def test_a_wedged_recogniser_is_killed_at_the_deadline(self):
        # Stand in for tesseract with a process that consumes the image and then
        # hangs, so the timeout guardrail is exercised rather than assumed.
        # The sleeper is backgrounded so the shell keeps a child alive whatever
        # /bin/sh is: bash exec-replaces itself with a trailing simple command,
        # dash forks for it, and the fork is the case that used to wedge the
        # cleanup.  Hard-coding the fork keeps this test honest on both.
        stalling = ["/bin/sh", "-c", "cat >/dev/null; sleep 30 & wait"]
        with mock.patch.object(linux_capture, "_tesseract_arguments",
                               lambda: stalling):
            started = time.monotonic()
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture._run_tesseract(
                    b"P6\n1 1\n255\n\x00\x00\x00", cancel_event=None, timeout=1.0)
        self.assertIn("timed out", str(caught.exception))
        self.assertLess(time.monotonic() - started, 10.0)

    @unittest.skipUnless(os.name == "posix", "process guardrails need a POSIX shell")
    def test_an_oversized_output_is_refused_rather_than_parsed(self):
        flood = ["/bin/sh", "-c",
                 f"cat >/dev/null; head -c {linux_capture.MAX_TESSERACT_STDOUT_BYTES + 4096} /dev/zero | tr '\\0' 'a'"]
        with mock.patch.object(linux_capture, "_tesseract_arguments", lambda: flood):
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture._run_tesseract(
                    b"P6\n1 1\n255\n\x00\x00\x00", cancel_event=None, timeout=10.0)
        self.assertIn("more text", str(caught.exception))

    @unittest.skipUnless(os.name == "posix", "process guardrails need a POSIX shell")
    def test_a_failing_recogniser_surfaces_its_own_diagnostic(self):
        failing = ["/bin/sh", "-c", "cat >/dev/null; echo 'no such data file' >&2; exit 1"]
        with mock.patch.object(linux_capture, "_tesseract_arguments", lambda: failing), \
                mock.patch.object(linux_capture, "tesseract_languages",
                                  lambda: frozenset({"eng"})):
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture._run_tesseract(
                    b"P6\n1 1\n255\n\x00\x00\x00", cancel_event=None, timeout=10.0)
        self.assertIn("no such data file", str(caught.exception))

    def test_language_failure_stays_silent_when_the_language_is_present(self):
        with mock.patch.object(linux_capture, "tesseract_languages",
                               lambda: frozenset({"eng"})):
            self.assertEqual(linux_capture._language_failure(), "")


class _KnownTextWindow:
    """A real X11 window painted with known text, for round-trip proof.

    It draws with the core ``fixed`` font through the same libX11 handle the
    capture path uses.  Nothing here synthesises input: the window is created,
    mapped and painted by its owner, which is this test process.
    """

    XA_CARDINAL = 6
    PROP_MODE_REPLACE = 0

    # Xlib's XSetWindowAttributes, needed only for override_redirect. The
    # preceding members must be declared so the field lands at the right
    # offset; CWOverrideRedirect tells the server to read only that one.
    class _XSetWindowAttributes(ctypes.Structure):
        _fields_ = [
            ("background_pixmap", ctypes.c_ulong),
            ("background_pixel", ctypes.c_ulong),
            ("border_pixmap", ctypes.c_ulong),
            ("border_pixel", ctypes.c_ulong),
            ("bit_gravity", ctypes.c_int),
            ("win_gravity", ctypes.c_int),
            ("backing_store", ctypes.c_int),
            ("backing_planes", ctypes.c_ulong),
            ("backing_pixel", ctypes.c_ulong),
            ("save_under", ctypes.c_int),
            ("event_mask", ctypes.c_long),
            ("do_not_propagate_mask", ctypes.c_long),
            ("override_redirect", ctypes.c_int),
            ("colormap", ctypes.c_ulong),
            ("cursor", ctypes.c_ulong),
        ]

    CW_OVERRIDE_REDIRECT = 1 << 9

    def __init__(self, width=700, height=260, lines=KNOWN_LINES,
                 override_redirect=True):
        self.width = width
        self.height = height
        self.lines = lines
        # Managed by default would mean the window manager raises this window
        # and can hand it focus, which on a desktop that is also running the
        # game pulls focus out of it mid-fight. Only the test that needs this
        # window to *be* the active window asks for a managed one.
        self.override_redirect = override_redirect
        self.window = 0
        self._display = 0

    def __enter__(self):
        x11 = linux_capture._load_x11()
        self._x11 = x11
        self._declare(x11)
        self._display = x11.XOpenDisplay(
            linux_capture.x11_display_name().encode("utf-8"))
        if not self._display:
            raise unittest.SkipTest("the X display could not be opened")
        root = x11.XDefaultRootWindow(self._display)
        self.window = x11.XCreateSimpleWindow(
            self._display, root, 60, 60, self.width, self.height, 0, 0,
            0x00101018)
        if self.override_redirect:
            attributes = self._XSetWindowAttributes(override_redirect=1)
            x11.XChangeWindowAttributes(
                self._display, self.window, self.CW_OVERRIDE_REDIRECT,
                ctypes.byref(attributes))
        x11.XStoreName(self._display, self.window, b"SpinLoremasterCaptureTest")
        # The capture path verifies _NET_WM_PID, so the window must publish it
        # exactly as Wine does for eqgame.exe.
        owner = ctypes.c_ulong(os.getpid())
        x11.XChangeProperty(
            self._display, self.window,
            x11.XInternAtom(self._display, b"_NET_WM_PID", 0),
            self.XA_CARDINAL, 32, self.PROP_MODE_REPLACE,
            ctypes.byref(owner), 1)
        x11.XMapRaised(self._display, self.window)
        x11.XSync(self._display, 0)
        self._await_viewable(x11)
        self.paint()
        return self

    def __exit__(self, *_exc):
        if self.window:
            self._x11.XDestroyWindow(self._display, self.window)
        if self._display:
            self._x11.XSync(self._display, 0)
            self._x11.XCloseDisplay(self._display)

    def paint(self) -> None:
        """Repaint the known text; X11 windows own their own contents."""
        x11 = self._x11
        graphics = x11.XCreateGC(self._display, self.window, 0, None)
        try:
            x11.XSetForeground(self._display, graphics, 0x00101018)
            x11.XFillRectangle(self._display, self.window, graphics, 0, 0,
                               self.width, self.height)
            font = x11.XLoadFont(self._display, b"fixed")
            if not font:
                raise unittest.SkipTest("no core X font is available to draw with")
            x11.XSetFont(self._display, graphics, font)
            x11.XSetForeground(self._display, graphics, 0x00F0E6C8)
            for index, text in enumerate(self.lines):
                encoded = text.encode("ascii")
                x11.XDrawString(self._display, self.window, graphics, 30,
                                50 + index * 45, encoded, len(encoded))
        finally:
            x11.XFreeGC(self._display, graphics)
        x11.XSync(self._display, 0)
        # Give the compositor a moment to make the painted content readable.
        time.sleep(0.35)

    def is_active(self) -> bool:
        active = linux_capture._window_property(
            self._x11, self._display,
            self._x11.XDefaultRootWindow(self._display), "_NET_ACTIVE_WINDOW")
        return bool(active) and int(active) == int(self.window)

    def _await_viewable(self, x11, timeout=3.0) -> None:
        attributes = linux_capture._XWindowAttributes()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (x11.XGetWindowAttributes(self._display, self.window,
                                         ctypes.byref(attributes))
                    and attributes.map_state == linux_capture._IS_VIEWABLE):
                return
            time.sleep(0.05)
        raise unittest.SkipTest("the window manager never made the window viewable")

    @staticmethod
    def _declare(x11) -> None:
        ulong, int_, uint, void_p, char_p = (
            ctypes.c_ulong, ctypes.c_int, ctypes.c_uint, ctypes.c_void_p,
            ctypes.c_char_p)
        x11.XCreateSimpleWindow.restype = ulong
        x11.XCreateSimpleWindow.argtypes = [
            void_p, ulong, int_, int_, uint, uint, uint, ulong, ulong]
        x11.XStoreName.argtypes = [void_p, ulong, char_p]
        x11.XChangeProperty.argtypes = [
            void_p, ulong, ulong, ulong, int_, int_, void_p, int_]
        x11.XChangeWindowAttributes.argtypes = [void_p, ulong, ulong, void_p]
        x11.XMapRaised.argtypes = [void_p, ulong]
        x11.XDestroyWindow.argtypes = [void_p, ulong]
        x11.XCreateGC.restype = void_p
        x11.XCreateGC.argtypes = [void_p, ulong, ulong, void_p]
        x11.XFreeGC.argtypes = [void_p, void_p]
        x11.XSetForeground.argtypes = [void_p, void_p, ulong]
        x11.XFillRectangle.argtypes = [void_p, ulong, void_p, int_, int_, uint, uint]
        x11.XLoadFont.restype = ulong
        x11.XLoadFont.argtypes = [void_p, char_p]
        x11.XSetFont.argtypes = [void_p, void_p, ulong]
        x11.XDrawString.argtypes = [void_p, ulong, void_p, int_, int_, char_p, int_]


@unittest.skipUnless(
    X11_READY and WINDOW_TESTS_ALLOWED,
    "set LOREMASTER_X11_WINDOW_TESTS=1 to run tests that open a window")
class X11CaptureSmokeTests(unittest.TestCase):
    def test_region_is_clamped_to_the_verified_window_and_pixels_are_real(self):
        with _KnownTextWindow() as target:
            region = linux_capture.capture_window_region(
                target.window, hover_ocr.ROI_WIDTH, hover_ocr.ROI_HEIGHT,
                expected_process=process_identity(os.getpid()).comm,
                cursor=(0, 0))
        # The ROI is never widened past the window it was verified against.
        self.assertEqual(
            (region.region_width, region.region_height), (700, 260))
        self.assertEqual(region.pid, os.getpid())
        self.assertEqual(region.window, target.window)
        self.assertEqual(region.stride, (700 * 3 + 3) & ~3)
        self.assertEqual(len(region.pixels), region.stride * 260)
        self.assertGreater(region.screen_width, 0)
        self.assertGreater(
            hover_ocr._luminance_range(region.pixels, region.region_width,
                                       region.region_height, region.stride),
            hover_ocr.MIN_LUMINANCE_RANGE)

    def test_capture_refuses_a_window_owned_by_another_process(self):
        with _KnownTextWindow(width=200, height=120) as target:
            with self.assertRaises(LinuxCaptureError) as caught:
                linux_capture.capture_window_region(
                    target.window, 200, 120, expected_process="eqgame.exe")
        message = str(caught.exception)
        self.assertIn("eqgame.exe", message)
        self.assertIn(process_identity(os.getpid()).comm, message)

    def test_active_window_capture_agrees_with_the_window_manager(self):
        with _KnownTextWindow(override_redirect=False, width=320, height=200) as target:
            if not target.is_active():
                raise unittest.SkipTest(
                    "the window manager did not focus the test window")
            region = linux_capture.capture_active_window_region(
                320, 200, expected_process=process_identity(os.getpid()).comm)
        self.assertEqual(region.window, target.window)
        self.assertEqual(region.pid, os.getpid())


@unittest.skipUnless(X11_READY and TESSERACT_READY and WINDOW_TESTS_ALLOWED,
                     "capture-and-OCR round trip requires X11 and tesseract "
                     "with at least one Latin-script language model")
class X11OcrRoundTripTests(unittest.TestCase):
    """Real pixels from a real window, through the real tesseract binary."""

    def setUp(self):
        # Production always asks for DEFAULT_OCR_LANGUAGE; the override exists
        # so this proof still runs where only another Latin model is installed.
        patch = mock.patch.dict(
            os.environ, {linux_capture.OCR_LANGUAGE_ENV: OCR_LANGUAGE})
        patch.start()
        self.addCleanup(patch.stop)

    def capture_known_text(self, **window):
        with _KnownTextWindow(**window) as target:
            return linux_capture.capture_window_region(
                target.window, hover_ocr.ROI_WIDTH, hover_ocr.ROI_HEIGHT,
                expected_process=process_identity(os.getpid()).comm,
                cursor=(0, 0))

    def report(self, recognised):
        """Make the evidence self-documenting in the test output."""
        print(f"\n[linux_capture] tesseract language {OCR_LANGUAGE!r} "
              f"recognised {recognised!r}")

    def assert_recognised(self, expected, recognised):
        """Exact for alphabetic text; close enough for ambiguous digit glyphs.

        Strictness follows the rendered string rather than the installed model.
        The only font guaranteed to exist on any X server is the core "fixed"
        6x13 bitmap, whose digits are genuinely ambiguous at that size -- 6/B,
        4/d and s/z differ by a pixel or two -- so exact recognition of the
        timer line is not a property tesseract guarantees for any model, and it
        does in fact vary between English traineddata builds. Demanding it made
        this test a measure of which eng package happened to be installed.
        Alphabetic lines carry the real proof and are still required to be
        exact.
        """
        if ENGLISH_READY and not any(char.isdigit() for char in expected):
            self.assertIn(expected, recognised,
                          msg=f"{OCR_LANGUAGE} OCR returned {recognised!r}")
            return
        best, closest = max(
            (SequenceMatcher(None, expected.casefold(), text.casefold()).ratio(),
             text) for text in recognised or [""])
        self.assertGreaterEqual(
            best, FALLBACK_SIMILARITY,
            msg=(f"the {OCR_LANGUAGE} model read {expected!r} as {closest!r} "
                 f"(similarity {best:.2f}); all lines were {recognised!r}"))

    def test_tesseract_reads_back_the_text_drawn_into_a_real_window(self):
        region = self.capture_known_text()
        lines = linux_capture.recognize_lines(
            region.pixels, region.region_width, region.region_height,
            region.stride, scale=hover_ocr.OCR_SCALE)
        recognised = [line.text for line in lines]
        self.report(recognised)
        self.assertEqual(len(recognised), len(KNOWN_LINES))
        for expected in KNOWN_LINES:
            self.assert_recognised(expected, recognised)
        for line in lines:
            self.assertGreaterEqual(line.x, 0.0)
            self.assertLessEqual(line.x + line.width, float(region.region_width))
            self.assertLessEqual(line.y + line.height, float(region.region_height))
            self.assertGreater(line.height, 0.0)

    def test_hover_scan_seam_produces_candidates_from_a_real_capture(self):
        region = self.capture_known_text()
        capture = hover_ocr.HoverCapture(
            metadata=hover_ocr.CaptureMetadata(
                cursor_x=region.cursor_x, cursor_y=region.cursor_y,
                region_left=region.region_left, region_top=region.region_top,
                region_width=region.region_width,
                region_height=region.region_height,
                foreground_hwnd=region.window, foreground_pid=region.pid,
                captured_at=time.time()),
            bmp_bytes=hover_ocr._bmp_from_bgr(
                region.pixels, region.region_width, region.region_height,
                region.stride),
            luminance_range=1)
        candidates, lines = hover_ocr.scan_hovered_tooltip(capture)
        self.report(candidates)
        self.assert_recognised("Cloak of Flames", [line.text for line in lines])
        self.assert_recognised("Cloak of Flames", candidates)

    def test_cancellation_stops_a_running_scan_without_a_result(self):
        pixels, stride = make_bgr(320, 240)
        cancelled = threading.Event()
        timer = threading.Timer(0.05, cancelled.set)
        timer.start()
        self.addCleanup(timer.cancel)
        with self.assertRaises(LinuxOcrCancelled):
            linux_capture.recognize_lines(
                pixels, 320, 240, stride, scale=4, cancel_event=cancelled,
                timeout=20.0)


if __name__ == "__main__":
    unittest.main()
