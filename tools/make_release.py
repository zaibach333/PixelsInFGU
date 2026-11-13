"""Assemble release assets in dist/ (run after building the bridge(s) and the .ext).

Bridge binaries it looks for (any that exist get a bundle; at least one is required):
  dist/PixelsFGU-Bridge.exe                 Windows
  dist/PixelsFGU-Bridge-macos-arm64         macOS, Apple silicon (experimental)
  dist/PixelsFGU-Bridge-linux-x86_64        Linux x86-64 (experimental)

Produces:
  dist/PixelsInFGU-<version>-<platform>.zip  everything for one platform in one download
  dist/SHA256SUMS.txt                        checksums for every asset
  dist/release-notes.md                      body for the GitHub release

    python tools/make_release.py            # version from bridge/version.py
    python tools/make_release.py v0.1.0     # (the release workflow passes the tag)
"""

from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXT = "PixelsFGU.ext"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


@dataclass(frozen=True)
class Platform:
    key: str            # bundle suffix
    binary: str         # file name in dist/ and on the release
    inner: str          # file name inside the bundle
    label: str
    experimental: bool
    run: str            # how to start the bridge, for the quick start


PLATFORMS = [
    Platform("windows", "PixelsFGU-Bridge.exe", "PixelsFGU-Bridge.exe", "Windows 10/11", False,
             "Double-click PixelsFGU-Bridge.exe"),
    Platform("macos-arm64", "PixelsFGU-Bridge-macos-arm64", "PixelsFGU-Bridge",
             "macOS 12+ on Apple silicon", True,
             "In Terminal, cd to this folder and run: ./PixelsFGU-Bridge\n"
             "   First run: if macOS says it can't be opened, run\n"
             "     xattr -d com.apple.quarantine PixelsFGU-Bridge\n"
             "   and allow Terminal under System Settings > Privacy & Security >\n"
             "   Bluetooth and > Accessibility (the second lets it tap Shift for FGU)"),
    Platform("linux-x86_64", "PixelsFGU-Bridge-linux-x86_64", "PixelsFGU-Bridge",
             "Linux x86-64 (BlueZ)", True,
             "In a terminal, cd to this folder and run: ./PixelsFGU-Bridge\n"
             "   Install xdotool so it can tap Shift for FGU (X11 only)"),
]

QUICKSTART = """PixelsInFGU {version} for {label}{exp} - quick start
==========================================================

1. Copy PixelsFGU.ext into your Fantasy Grounds data folder's "extensions" folder.
   (In FGU's launcher: Settings > Data Folder shows where it is.)
2. Load your campaign with "Feature: Pixels Dice" enabled.
3. Close the Pixels phone app (a die talks to one app at a time) and pick up your
   dice to wake them.
4. {run}
   Leave it open while you play. If it can't find your FGU data folder, add
   --data-dir "<your data folder>".
5. Click a roll in FGU. Your matching dice blink blue - roll them and the result lands
   in FGU. Keep FGU as the active window.{manual}

Type /pixels in FGU chat to see your dice and battery levels.

More help, source code and how to verify these files:
https://github.com/{repo}
"""

EXPERIMENTAL_NOTE = """
   EXPERIMENTAL: this platform hasn't been tested with real dice yet. If a roll
   doesn't show up in FGU, tap Shift in FGU. Please report what works and what
   doesn't on GitHub."""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else "_See CHANGELOG.md._"


def write_zip(out: Path, members: dict[str, tuple[bytes, int]]) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(members):
            data, mode = members[name]
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3          # Unix, so unzip tools honor the mode bits
            info.external_attr = mode << 16
            z.writestr(info, data)


def main() -> int:
    version = re.search(r'"([^"]+)"', (ROOT / "bridge" / "version.py").read_text()).group(1)
    if len(sys.argv) > 1:
        version = sys.argv[1].removeprefix("v")
    repo = sys.argv[2] if len(sys.argv) > 2 else "zaibach333/PixelsInFGU"

    if not (DIST / EXT).exists():
        print(f"Missing dist/{EXT}; run tools/package_ext.py first.")
        return 1
    present = [p for p in PLATFORMS if (DIST / p.binary).exists()]
    if not present:
        print("No bridge binaries in dist/; build at least one first.")
        return 1

    folder = f"PixelsInFGU-{version}"
    ext_bytes = (DIST / EXT).read_bytes()
    assets: list[str] = []
    for p in present:
        bundle = f"PixelsInFGU-{version}-{p.key}.zip"
        crlf = p.key == "windows"
        quick = QUICKSTART.format(
            version=version, label=p.label, exp=" (experimental)" if p.experimental else "",
            run=p.run, manual=EXPERIMENTAL_NOTE if p.experimental else "", repo=repo)
        if crlf:
            quick = quick.replace("\n", "\r\n")
        write_zip(DIST / bundle, {
            f"{folder}/{p.inner}": ((DIST / p.binary).read_bytes(), 0o755),
            f"{folder}/{EXT}": (ext_bytes, 0o644),
            f"{folder}/QUICKSTART.txt": (quick.encode(), 0o644),
            f"{folder}/LICENSE.txt": ((ROOT / "LICENSE").read_bytes(), 0o644),
            f"{folder}/THIRD_PARTY_NOTICES.md": ((ROOT / "THIRD_PARTY_NOTICES.md").read_bytes(), 0o644),
        })
        assets.append(bundle)
    assets += [EXT] + [p.binary for p in present]

    sums = {name: sha256(DIST / name) for name in assets}
    (DIST / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="ascii")

    def link(name: str) -> str:
        return f"[{name}](https://github.com/{repo}/releases/download/v{version}/{name})"

    rows = []
    for p in present:
        exp = " — *experimental, untested with real dice*" if p.experimental else ""
        rows.append(f"| **{p.label}**{exp} | **{link(f'PixelsInFGU-{version}-{p.key}.zip')}** | {link(p.binary)} |")
    table = "\n".join(rows)

    notes = f"""## Downloads

Pick the zip for your computer: it has the bridge app, the FGU extension and a quick start.

| Platform | Everything in one zip | Bridge app only |
|---|---|---|
{table}

FGU extension only: {link(EXT)} (the same file for every platform). Checksums: `SHA256SUMS.txt`.

## Install

1. Copy `{EXT}` into your FGU data folder's `extensions` folder and enable **Feature: Pixels Dice** for your campaign.
2. Close the Pixels phone app, wake your dice, and run the bridge (see `QUICKSTART.txt` in the zip).
3. Roll! See the [README](https://github.com/{repo}#readme) for details.

macOS and Linux builds are experimental. On macOS the app isn't notarized, so the first run needs
`xattr -d com.apple.quarantine PixelsFGU-Bridge`. If a downloaded bridge-only file won't start, run `chmod +x` on it.

## Verify these files

Built by GitHub Actions from tag `v{version}`; nothing was uploaded from a personal machine.

```sh
sha256sum -c SHA256SUMS.txt --ignore-missing          # Linux (macOS: shasum -a 256 -c)
gh attestation verify <file> --repo {repo}            # signed build provenance
```

On Windows: `Get-FileHash <file> -Algorithm SHA256` and compare with `SHA256SUMS.txt`.
See [SECURITY.md](https://github.com/{repo}/blob/v{version}/SECURITY.md) for exactly what the bridge does on your computer.

## What's new

{changelog_section(version)}

<details><summary>SHA-256</summary>

```
{"".join(f"{h}  {n}" + chr(10) for n, h in sums.items()).rstrip()}
```
</details>
"""
    (DIST / "release-notes.md").write_text(notes, encoding="utf-8")
    for n, h in sums.items():
        print(f"{h}  {n}")
    print("Wrote dist/release-notes.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
