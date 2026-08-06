#!/usr/bin/env python3
"""Windows-only visual smoke test for Loremaster's live Tk surfaces."""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import sys
import tempfile
import time
from ctypes import wintypes
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]


def windows_by_title(title: str):
    user32 = ctypes.windll.user32
    found = []
    callback_type = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)

    @callback_type
    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value == title and user32.IsWindowVisible(hwnd):
                found.append(hwnd)
        return True

    user32.EnumWindows(callback, 0)
    return found


def wait_window(title: str, timeout=8.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        windows = windows_by_title(title)
        if windows:
            return windows[-1]
        time.sleep(0.05)
    raise RuntimeError(f"window did not appear: {title}")


def rect(hwnd):
    value = wintypes.RECT()
    if not ctypes.windll.user32.GetWindowRect(hwnd, ctypes.byref(value)):
        raise OSError("GetWindowRect failed")
    return value.left, value.top, value.right, value.bottom


def click(x, y, right=False):
    user32 = ctypes.windll.user32
    user32.SetCursorPos(int(x), int(y))
    down, up = ((0x0008, 0x0010) if right else (0x0002, 0x0004))
    user32.mouse_event(down, 0, 0, 0, 0)
    user32.mouse_event(up, 0, 0, 0, 0)


def click_window(hwnd, x, y, right=False):
    """Deliver a client-area click directly to a specific smoke window."""
    user32 = ctypes.windll.user32
    down, up = ((0x0204, 0x0205) if right else (0x0201, 0x0202))
    key_state = 0x0002 if right else 0x0001
    lparam = (int(y) << 16) | (int(x) & 0xFFFF)
    user32.SendMessageW(hwnd, down, key_state, lparam)
    user32.SendMessageW(hwnd, up, 0, lparam)


def escape():
    user32 = ctypes.windll.user32
    user32.keybd_event(0x1B, 0, 0, 0)
    user32.keybd_event(0x1B, 0, 0x0002, 0)


def capture(hwnd, path: Path):
    from PIL import ImageGrab
    left, top, right, bottom = rect(hwnd)
    ImageGrab.grab(bbox=(left, top, right, bottom), all_screens=True).save(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=REPO / "build" / "gui-smoke")
    parser.add_argument("--theme", choices=("vellum", "glass"), default="vellum")
    parser.add_argument(
        "--executable",
        type=Path,
        help="Drive a packaged Loremaster executable instead of the Python source.",
    )
    parser.add_argument(
        "--no-capture",
        action="store_true",
        help="Validate live window geometry without saving screenshots.",
    )
    parser.add_argument(
        "--launch-only",
        action="store_true",
        help="For packaged builds, verify that the live Seed window launches.",
    )
    args = parser.parse_args()
    if os.name != "nt":
        print("SKIP: Loremaster GUI smoke test is Windows-only")
        return 0
    args.output.mkdir(parents=True, exist_ok=True)
    smoke_temp_root = REPO / "build"
    smoke_temp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
            prefix="loremaster-smoke-", dir=smoke_temp_root,
            ignore_cleanup_errors=True) as app_data:
        Path(app_data, "loremaster_config.json").write_text(
            json.dumps({"ui_theme": args.theme}), encoding="utf-8")
        env = dict(os.environ)
        env["LOREMASTER_APP_DATA_DIR"] = app_data
        # Keep PyInstaller's one-file extraction inside the writable smoke
        # workspace. This also makes packaged-GUI tests deterministic in CI.
        env["TEMP"] = app_data
        env["TMP"] = app_data
        command = (
            [str(args.executable.resolve()), "--demo"]
            if args.executable
            else [sys.executable, str(REPO / "loremaster" / "loremaster.py"),
                  "--demo"]
        )
        process = subprocess.Popen(command, cwd=REPO, env=env)
        try:
            seed = wait_window("Loremaster")
            time.sleep(0.8)
            seed_rect = rect(seed)
            if not args.no_capture:
                capture(seed, args.output / "01-seed.png")
            seed_size = (seed_rect[2] - seed_rect[0], seed_rect[3] - seed_rect[1])
            if seed_size[0] > 120 or seed_size[1] > 80:
                raise RuntimeError(f"unexpected seed size: {seed_size}")
            if args.launch_only:
                print("Loremaster packaged GUI launch: PASS | "
                      f"seed {seed_size}@{seed_rect[:2]}")
                return 0
            left, top, right, bottom = seed_rect
            for _attempt in range(4):
                ctypes.windll.user32.ShowWindow(seed, 5)
                ctypes.windll.user32.SetForegroundWindow(seed)
                time.sleep(0.12)
                click_window(
                    seed, (right - left) / 2, (bottom - top) / 2, right=True)
                time.sleep(0.35)
                if windows_by_title("Loremaster Settings"):
                    break
            settings = wait_window("Loremaster Settings")
            time.sleep(0.5)
            settings_rect = rect(settings)
            if not args.no_capture:
                capture(settings, args.output / "02-settings.png")
            ctypes.windll.user32.SetForegroundWindow(settings)
            escape()
            deadline = time.monotonic() + 2
            while windows_by_title("Loremaster Settings") and time.monotonic() < deadline:
                time.sleep(0.05)
            left, top, right, bottom = rect(seed)
            for _attempt in range(4):
                ctypes.windll.user32.SetForegroundWindow(seed)
                click((left + right) / 2, (top + bottom) / 2)
                time.sleep(0.55)
                probe = rect(seed)
                if probe[2] - probe[0] >= 440:
                    break
            expanded_rect = rect(seed)
            if not args.no_capture:
                capture(seed, args.output / "03-expanded.png")
            left, top, right, bottom = expanded_rect
            for _attempt in range(4):
                ctypes.windll.user32.SetForegroundWindow(seed)
                click(right - 62, top + 24)  # SEED masthead control
                time.sleep(0.55)
                probe = rect(seed)
                if probe[2] - probe[0] <= 120:
                    break
            collapsed_rect = rect(seed)
            if not args.no_capture:
                capture(seed, args.output / "04-collapsed.png")
            settings_size = (settings_rect[2] - settings_rect[0],
                             settings_rect[3] - settings_rect[1])
            expanded_size = (expanded_rect[2] - expanded_rect[0],
                             expanded_rect[3] - expanded_rect[1])
            collapsed_size = (collapsed_rect[2] - collapsed_rect[0],
                              collapsed_rect[3] - collapsed_rect[1])
            print("Loremaster GUI rects | "
                  f"seed={seed_rect} settings={settings_rect} "
                  f"expanded={expanded_rect} collapsed={collapsed_rect}")
            if settings_size[0] < 700 or settings_size[1] < 400:
                raise RuntimeError(f"settings surface is clipped: {settings_size}")
            if expanded_size[0] < 440 or expanded_size[1] < 520:
                raise RuntimeError(f"expanded surface is too small: {expanded_size}")
            if collapsed_size[0] > 120 or collapsed_size[1] > 80:
                raise RuntimeError(f"HUD did not collapse: {collapsed_size}")
            print("Loremaster GUI smoke: PASS | "
                  f"seed {seed_size}@{seed_rect[:2]} | "
                  f"settings {settings_size}@{settings_rect[:2]} | "
                  f"expanded {expanded_size}@{expanded_rect[:2]} | "
                  f"collapsed {collapsed_size}@{collapsed_rect[:2]}")
        finally:
            if args.executable:
                # A one-file PyInstaller process owns a child that hosts the
                # GUI, so terminate the full process tree before temp cleanup.
                subprocess.run(
                    ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                subprocess.run(
                    ["taskkill", "/IM", args.executable.name, "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                )
                time.sleep(0.4)
            else:
                process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
