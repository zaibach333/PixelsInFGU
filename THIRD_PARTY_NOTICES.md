# Third-party notices

## Pixels SDK (protocol details)

`bridge/pixels_protocol.py` ports the Bluetooth UUIDs, message layouts, enums, face-index
mapping (`DiceUtils.faceFromIndex`) and advertisement parsing (`getScannedPixel`) from
Systemic Games' Pixels packages: `@systemic-games/pixels-core-connect`,
`pixels-core-animation` and `react-native-pixels-connect`, version 1.3.

```
MIT License

Copyright (c) 2023 Systemic Games

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## Bundled in the bridge executables

Each release build of the bridge is made with PyInstaller and contains:

| Component | License |
|---|---|
| Python runtime | PSF License |
| [bleak](https://github.com/hbldh/bleak) | MIT |
| [winrt (pywinrt)](https://github.com/pywinrt/pywinrt) packages (Windows build) | MIT |
| [PyObjC](https://github.com/ronaldoussoren/pyobjc) core, CoreBluetooth and libdispatch (macOS builds) | MIT |
| [dbus-fast](https://github.com/Bluetooth-Devices/dbus-fast) (Linux build) | MIT |
| typing_extensions | PSF License |
| [PyInstaller](https://pyinstaller.org) bootloader | GPL-2.0 with a bootloader exception that allows distributing the built executable under any license |

See each project for its full license text.

## Fantasy Grounds

The extension runs on SmiteWorks' CoreRPG ruleset APIs. It does not include any SmiteWorks code
or assets. It layers onto the `manualroll_entry` window class by name.

## Trademarks

Pixels is a trademark of Systemic Games, LLC. Fantasy Grounds is a trademark of SmiteWorks USA, LLC.
This project is not affiliated with or endorsed by either company.
