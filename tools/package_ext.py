"""Build dist/PixelsFGU.ext deterministically.

Same source -> byte-identical .ext (sorted entries, fixed timestamps, forward
slashes), so anyone can rebuild it and compare its SHA-256 with a release.

    python tools/package_ext.py
"""

import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "extension" / "PixelsFGU"
OUT = ROOT / "dist" / "PixelsFGU.ext"
FIXED_TIME = (1980, 1, 1, 0, 0, 0)


def main() -> int:
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for path in files:
            info = zipfile.ZipInfo(path.relative_to(SRC).as_posix(), FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            z.writestr(info, path.read_bytes())
    digest = hashlib.sha256(OUT.read_bytes()).hexdigest()
    print(f"Built {OUT.relative_to(ROOT)} ({len(files)} files)\nSHA-256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
