# Contributing

## Layout

| Path | What |
|---|---|
| `bridge/` | Python bridge: Bluetooth (bleak), inbox/outbox files, Shift-key nudge |
| `extension/PixelsFGU/` | FGU extension (Lua + XML) |
| `extension/tests/` | Extension tests: runs the real Lua with stubbed FGU APIs via `lupa` |
| `tools/` | Packaging, version check, dev helpers |
| `docs/protocol.md` | The file contract between bridge and extension |

## Setup (Windows)

```powershell
py -m venv bridge\.venv
bridge\.venv\Scripts\python -m pip install -r bridge\requirements-dev.txt
powershell -ExecutionPolicy Bypass -File tools\deploy-dev.ps1   # junction the extension into FGU
```

The junction means FGU loads the extension straight from this checkout. Type `/reload` in FGU
after editing Lua or XML.

Test without dice: `bridge\.venv\Scripts\python bridge\pixels_bridge.py --simulate d20 d6`,
then type rolls such as `d20 17`.

## Tests

```powershell
bridge\.venv\Scripts\python -m unittest discover -s bridge -p "test_*.py"
bridge\.venv\Scripts\python -m unittest discover -s extension\tests -p "test_*.py"
```

CI runs both on every push and pull request.

## Releasing

1. Bump the version in **both** `bridge/version.py` and `extension/PixelsFGU/extension.xml`
   (`python tools/check_version.py` checks they match), and update `CHANGELOG.md`.
2. Commit, then tag and push the tag: `git tag v0.1.0 && git push origin v0.1.0`.
3. The **Release** workflow builds the `.exe` and `.ext` on GitHub's runners, then
   `tools/make_release.py` bundles them into `PixelsInFGU-<version>-windows.zip` (with a quick
   start, license and notices) and writes `SHA256SUMS.txt` and the release notes (downloads,
   install, verification, and this version's `CHANGELOG.md` section). Every asset gets a
   signed build-provenance attestation, and the workflow opens a **draft** release.
   To preview locally, build both artifacts and run `python tools/make_release.py`.
4. Review the draft, then publish it.

Release binaries are only ever built by the workflow, never uploaded from a local machine. That's
what lets users verify them (see SECURITY.md).
