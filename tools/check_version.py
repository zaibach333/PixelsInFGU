"""Fail unless the bridge and extension versions match (and match a tag, if given).

    python tools/check_version.py            # bridge == extension
    python tools/check_version.py v0.1.0     # ... and == the release tag
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    bridge = re.search(r'__version__\s*=\s*"([^"]+)"', (ROOT / "bridge" / "version.py").read_text()).group(1)
    ext = re.search(r"<version>([^<]+)</version>",
                    (ROOT / "extension" / "PixelsFGU" / "extension.xml").read_text(encoding="latin-1")).group(1)
    versions = {"bridge/version.py": bridge, "extension.xml": ext}
    if len(sys.argv) > 1:
        versions["tag"] = sys.argv[1].removeprefix("refs/tags/").removeprefix("v")
    if len(set(versions.values())) != 1:
        print("Version mismatch:", versions)
        return 1
    print("Version", bridge)
    return 0


if __name__ == "__main__":
    sys.exit(main())
