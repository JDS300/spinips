#!/usr/bin/env python3
"""Read, write and verify an AppImage's embedded update information.

Gear Lever and AppImageUpdate read a 1 KB ``.upd_info`` ELF section to learn
where a newer build lives.  electron-builder 26.x never writes it -- the
package contains no ``upd_info`` writer at all -- so every AppImage this
project has shipped carries that section zeroed, and Gear Lever shows a blank
update panel.  This tool fills it in after the build.

The section is patched **in place**.  An AppImage is an ELF runtime with a
squashfs payload appended after the ELF structure, so a tool that rewrites the
container (``objcopy --update-section``) discards the payload and produces a
broken image.  Writing at the section's recorded file offset leaves every other
byte, and the file length, untouched.

Order matters in CI: write the update information *before* generating the
``.zsync``, because zsync checksums file content and a zsync made from the
unpatched image describes bytes that no longer exist.

Update-information format (AppImageSpec):

    gh-releases-zsync|<owner>|<repo>|<channel>|<filename-glob>

``latest`` resolves through GitHub's /releases/latest, which excludes
prereleases.  ``latest-pre`` and ``latest-all`` make Gear Lever walk the full
release list newest-first and take the first release carrying an asset that
matches the glob, so the glob is what separates a candidate from a release.
"""

from __future__ import annotations

import argparse
import struct
import sys
from pathlib import Path

SECTION_NAME = ".upd_info"
# The AppImage runtime reserves exactly this much; a longer string cannot fit.
MAX_UPDATE_INFO = 1024


class ElfError(RuntimeError):
    """The file is not an ELF64 image we can patch."""


def find_section(source, name: str) -> tuple[int, int]:
    """Return the (offset, size) of a named section in an ELF64 image.

    ``source`` is a binary file object.  Only the pieces actually needed are
    read -- the ELF header, the section header table and the section-name
    string table -- because an AppImage is well over a hundred megabytes and
    its section header table can sit far past any fixed-size head buffer.  An
    earlier version read a flat 64 KB and failed on real images, whose table
    lives around 188 KB in.
    """

    def at(offset: int, size: int) -> bytes:
        source.seek(offset)
        chunk = source.read(size)
        if len(chunk) != size:
            raise ElfError(
                f"truncated: wanted {size} bytes at {offset}, got {len(chunk)}")
        return chunk

    header = at(0, 0x40)
    if header[:4] != b"\x7fELF":
        raise ElfError("not an ELF file")
    if header[4] != 2:
        raise ElfError("not ELF64")
    endian = "<" if header[5] == 1 else ">"

    # ELF64: e_shoff at 0x28, then e_shentsize / e_shnum / e_shstrndx at 0x3a.
    (e_shoff,) = struct.unpack_from(f"{endian}Q", header, 0x28)
    e_shentsize, e_shnum, e_shstrndx = struct.unpack_from(f"{endian}HHH", header, 0x3A)
    if not e_shoff or not e_shnum:
        raise ElfError("no section header table")
    if e_shstrndx >= e_shnum:
        raise ElfError("section name table index out of range")

    table = at(e_shoff, e_shentsize * e_shnum)

    def entry(index: int) -> tuple[int, int, int]:
        base = index * e_shentsize
        (sh_name,) = struct.unpack_from(f"{endian}I", table, base)
        sh_offset, sh_size = struct.unpack_from(f"{endian}QQ", table, base + 0x18)
        return sh_name, sh_offset, sh_size

    _, shstr_offset, shstr_size = entry(e_shstrndx)
    shstrtab = at(shstr_offset, shstr_size)

    wanted = name.encode()
    for index in range(e_shnum):
        sh_name, sh_offset, sh_size = entry(index)
        end = shstrtab.find(b"\x00", sh_name)
        if shstrtab[sh_name:end] == wanted:
            return sh_offset, sh_size
    raise ElfError(f"no {name} section")


def read_update_info(path: Path) -> str:
    """Return the update information string, or "" when the section is blank."""

    with path.open("rb") as handle:
        offset, size = find_section(handle, SECTION_NAME)
        handle.seek(offset)
        raw = handle.read(size)
    return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace")


def write_update_info(path: Path, text: str) -> None:
    """Patch the update information in place, leaving the file length alone."""

    payload = text.encode("utf-8")
    if not payload:
        raise ValueError("update information must not be empty")

    with path.open("r+b") as handle:
        offset, size = find_section(handle, SECTION_NAME)
        if len(payload) >= size:
            raise ValueError(
                f"update information is {len(payload)} bytes but the section "
                f"holds {size}")
        handle.seek(offset)
        # Zero-fill the remainder so a shorter string cannot leave a tail of a
        # longer previous one behind.
        handle.write(payload + b"\x00" * (size - len(payload)))


def update_string(owner: str, repo: str, channel: str, glob: str) -> str:
    for field, value in (("owner", owner), ("repo", repo),
                         ("channel", channel), ("glob", glob)):
        if not value or "|" in value:
            raise ValueError(f"{field} must be non-empty and contain no '|'")
    if channel not in ("latest", "latest-pre", "latest-all") and not channel.startswith("v"):
        raise ValueError(
            "channel must be latest, latest-pre, latest-all, or a literal tag")
    return f"gh-releases-zsync|{owner}|{repo}|{channel}|{glob}"


# -- self test -------------------------------------------------------------

def _synthetic_elf(section_size: int = MAX_UPDATE_INFO, pad: int = 0) -> bytes:
    """A minimal ELF64 carrying one .upd_info section, for testing.

    ``pad`` pushes the section header table that far into the file.  A real
    AppImage runtime puts its table around 188 KB in, which is what broke the
    first implementation's fixed 64 KB head read.
    """

    shstrtab = b"\x00" + SECTION_NAME.encode() + b"\x00" + b".shstrtab\x00"
    upd_name_off = 1
    shstr_name_off = 1 + len(SECTION_NAME) + 1

    header_size, entry_size, count = 0x40, 0x40, 3
    sh_offset = header_size + pad
    upd_offset = sh_offset + entry_size * count
    shstr_offset = upd_offset + section_size

    header = bytearray(header_size)
    header[0:4] = b"\x7fELF"
    header[4] = 2       # ELF64
    header[5] = 1       # little endian
    header[6] = 1       # version
    struct.pack_into("<Q", header, 0x28, sh_offset)
    struct.pack_into("<HHH", header, 0x3A, entry_size, count, 2)

    def entry(name_off: int, offset: int, size: int) -> bytes:
        buf = bytearray(entry_size)
        struct.pack_into("<I", buf, 0, name_off)
        struct.pack_into("<QQ", buf, 0x18, offset, size)
        return bytes(buf)

    return (bytes(header)
            + b"\x00" * pad
            + entry(0, 0, 0)                                  # NULL section
            + entry(upd_name_off, upd_offset, section_size)   # .upd_info
            + entry(shstr_name_off, shstr_offset, len(shstrtab))
            + b"\x00" * section_size
            + shstrtab)


def _self_test() -> int:
    import tempfile

    failures = []

    def check(label, condition):
        print(f"  {label}: {'PASS' if condition else 'FAIL'}")
        if not condition:
            failures.append(label)

    stable = update_string("JDS300", "spinips", "latest",
                           "Loremaster-[0-9]*-x86_64.AppImage.zsync")
    candidate = update_string("JDS300", "spinips", "latest-pre",
                              "Loremaster-RC-*-x86_64.AppImage.zsync")
    check("stable string is well formed",
          stable == "gh-releases-zsync|JDS300|spinips|latest|"
                    "Loremaster-[0-9]*-x86_64.AppImage.zsync")
    check("candidate targets prereleases", "|latest-pre|" in candidate)
    check("candidate glob excludes stable assets",
          "Loremaster-RC-*" in candidate)

    import fnmatch
    rc_glob = candidate.rsplit("|", 1)[1]
    stable_glob = stable.rsplit("|", 1)[1]
    check("rc glob does not match a stable asset",
          not fnmatch.fnmatch("Loremaster-0.4.0-x86_64.AppImage.zsync", rc_glob))
    check("rc glob matches an rc asset",
          fnmatch.fnmatch("Loremaster-RC-0.5.0-rc.1-x86_64.AppImage.zsync", rc_glob))
    check("stable glob matches a stable asset",
          fnmatch.fnmatch("Loremaster-0.4.0-x86_64.AppImage.zsync", stable_glob))
    # Anchoring on a digit is what keeps the two channels from overlapping.
    check("stable glob does not match an rc asset",
          not fnmatch.fnmatch("Loremaster-RC-0.5.0-rc.1-x86_64.AppImage.zsync",
                              stable_glob))

    for bad in (("", "spinips", "latest", "x"), ("a|b", "spinips", "latest", "x"),
                ("JDS300", "spinips", "nightly", "x")):
        try:
            update_string(*bad)
        except ValueError:
            pass
        else:
            check(f"rejects {bad}", False)
    check("rejects malformed inputs", True)

    with tempfile.TemporaryDirectory() as tmp:
        image = Path(tmp) / "fake.AppImage"
        original = _synthetic_elf()
        image.write_bytes(original)

        check("a fresh image reads back blank", read_update_info(image) == "")

        write_update_info(image, stable)
        check("round trips the written string", read_update_info(image) == stable)
        check("file length is unchanged", image.stat().st_size == len(original))

        write_update_info(image, candidate)
        check("a shorter rewrite leaves no tail",
              read_update_info(image) == candidate)

        try:
            write_update_info(image, "x" * MAX_UPDATE_INFO)
        except ValueError:
            check("refuses a string that will not fit", True)
        else:
            check("refuses a string that will not fit", False)

        # Regression: the section header table of a real AppImage sits far
        # past any fixed-size head buffer.  Reading a flat 64 KB failed on the
        # published images and passed here until this case existed.
        far = Path(tmp) / "far.AppImage"
        far.write_bytes(_synthetic_elf(pad=300_000))
        write_update_info(far, stable)
        check("finds a section table 300 KB into the file",
              read_update_info(far) == stable)

        # A payload appended after the ELF must survive the patch, because an
        # AppImage carries its squashfs there.
        payload = b"SQUASHFS-PAYLOAD" * 64
        image.write_bytes(original + payload)
        write_update_info(image, stable)
        check("appended payload survives",
              image.read_bytes().endswith(payload))

    print("appimage update info selftest:",
          "ALL PASS" if not failures else f"FAILED {failures}")
    return 1 if failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("image", nargs="?", type=Path)
    parser.add_argument("--write", metavar="TEXT")
    parser.add_argument("--read", action="store_true")
    parser.add_argument("--expect", metavar="TEXT",
                        help="fail unless the embedded value equals TEXT")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        return _self_test()
    if args.image is None:
        parser.error("an image path is required")

    if args.write:
        write_update_info(args.image, args.write)
        print(f"wrote update information: {args.write}")
    if args.read or not (args.write or args.expect):
        print(read_update_info(args.image) or "(blank)")
    if args.expect:
        found = read_update_info(args.image)
        if found != args.expect:
            print(f"update information mismatch\n  expected: {args.expect}\n"
                  f"  found:    {found or '(blank)'}", file=sys.stderr)
            return 1
        print(f"update information verified: {found}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
