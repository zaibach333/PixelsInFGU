# Builds dist\PixelsFGU-Bridge.exe (single file, no Python needed to run it).
# The release workflow (.github/workflows/release.yml) runs the same PyInstaller command.
$root = Join-Path $PSScriptRoot ".." | Resolve-Path
$py = Join-Path $root "bridge\.venv\Scripts\python.exe"
& $py -m pip install -q -r (Join-Path $root "bridge\requirements-dev.txt")
Push-Location (Join-Path $root "bridge")
try {
    & $py -m PyInstaller --noconfirm --clean --onefile --name PixelsFGU-Bridge `
        --collect-submodules bleak --collect-all winrt `
        --distpath (Join-Path $root "dist") --workpath (Join-Path $root "build") --specpath (Join-Path $root "build") `
        pixels_bridge.py
} finally { Pop-Location }
