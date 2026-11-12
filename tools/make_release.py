"""Assemble release assets in dist/ (run after building the .exe and .ext).

Produces:
  dist/PixelsInFGU-<version>-windows.zip   everything in one download
  dist/SHA256SUMS.txt                      checksums for every asset
  dist/release-notes.md                    body for the GitHub release

    python tools/make_release.py            # version from bridge/version.py
    python tools/make_release.py v0.1.0     # (the release workflow passes the tag)
"""

import hashlib
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
EXE = "PixelsFGU-Bridge.exe"
EXT = "PixelsFGU.ext"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)

QUICKSTART = """PixelsInFGU {version} - quick start
=====================================

1. Copy PixelsFGU.ext into your Fantasy Grounds data folder's "extensions" folder.
   (In FGU's launcher: Settings > Data Folder shows where it is.)
2. Load your campaign with "Feature: Pixels Dice" enabled.
3. Close the Pixels phone app (a die talks to one app at a time), pick up your dice to
   wake them, and run PixelsFGU-Bridge.exe. Leave it open while you play.
4. Click a roll in FGU. Your matching dice blink blue - roll them and the result lands
   in FGU. Keep FGU as the active window.

Type /pixels in FGU chat to see your dice and battery levels.

More help, source code and how to verify these files:
https://github.com/{repo}
"""


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def changelog_section(version: str) -> str:
    text = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    m = re.search(rf"^## {re.escape(version)}\b.*?$\n(.*?)(?=^## |\Z)", text, re.M | re.S)
    return m.group(1).strip() if m else "_See CHANGELOG.md._"


def write_zip(out: Path, members: dict[str, bytes]) -> None:
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, members[name])


def main() -> int:
    version = re.search(r'"([^"]+)"', (ROOT / "bridge" / "version.py").read_text()).group(1)
    if len(sys.argv) > 1:
        version = sys.argv[1].removeprefix("v")
    repo = sys.argv[2] if len(sys.argv) > 2 else "zaibach333/PixelsInFGU"

    for name in (EXE, EXT):
        if not (DIST / name).exists():
            print(f"Missing dist/{name}; build it first.")
            return 1

    bundle_name = f"PixelsInFGU-{version}-windows.zip"
    folder = f"PixelsInFGU-{version}"
    write_zip(DIST / bundle_name, {
        f"{folder}/{EXE}": (DIST / EXE).read_bytes(),
        f"{folder}/{EXT}": (DIST / EXT).read_bytes(),
        f"{folder}/QUICKSTART.txt": QUICKSTART.format(version=version, repo=repo).replace("\n", "\r\n").encode(),
        f"{folder}/LICENSE.txt": (ROOT / "LICENSE").read_bytes(),
        f"{folder}/THIRD_PARTY_NOTICES.md": (ROOT / "THIRD_PARTY_NOTICES.md").read_bytes(),
    })

    assets = [bundle_name, EXE, EXT]
    sums = {name: sha256(DIST / name) for name in assets}
    (DIST / "SHA256SUMS.txt").write_text("".join(f"{h}  {n}\n" for n, h in sums.items()), encoding="ascii")

    notes = f"""## Downloads

| File | What it is |
|---|---|
| **[{bundle_name}](https://github.com/{repo}/releases/download/v{version}/{bundle_name})** | **Everything in one zip**: bridge, extension, quick start |
| [{EXE}](https://github.com/{repo}/releases/download/v{version}/{EXE}) | The bridge app for Windows 10/11 (connects to your dice) |
| [{EXT}](https://github.com/{repo}/releases/download/v{version}/{EXT}) | The Fantasy Grounds extension |
| SHA256SUMS.txt | Checksums for the files above |

## Install

1. Copy `{EXT}` into your FGU data folder's `extensions` folder and enable **Feature: Pixels Dice** for your campaign.
2. Close the Pixels phone app, wake your dice, and run `{EXE}`.
3. Roll! See the [README](https://github.com/{repo}#readme) for details.

## Verify these files

Built by GitHub Actions from tag `v{version}`; nothing was uploaded from a personal machine.

```powershell
Get-FileHash .\\{EXE}, .\\{EXT} -Algorithm SHA256      # compare with SHA256SUMS.txt
gh attestation verify .\\{EXE} --repo {repo}           # signed build provenance
```

See [SECURITY.md](https://github.com/{repo}/blob/v{version}/SECURITY.md) for exactly what the bridge does on your PC.

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
