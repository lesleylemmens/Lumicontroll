# LumiControLL

LumiControLL is a Windows lighting control application for Art-Net and USB DMX output.

It is designed for simple live control of DMX lights, with support for show pages, chases, audio-triggered playback, Art-Net output, uDMX dongles, and Open DMX FTDI dongles/clones.

## Download

Download the latest installer from the GitHub Releases page:

[Download the latest LumiControLL release](../../releases/latest)

The installer is named:

```text
lumicontroll setup.exe
```

## Quick Start

1. Install LumiControLL with `lumicontroll setup.exe`.
2. Start LumiControLL from the desktop shortcut or Start Menu.
3. Use **Output Settings** to choose the USB DMX backend: None, uDMX, or Open DMX.
4. Enable Art-Net in **Output Settings** if you want Art-Net output.
5. For USB dongles, use the included Zadig guide from **Output Settings > Install USB dongle**, or use the FTDI VCP driver for Open DMX / FTDI clone adapters.

## Locked Mode And Admin Mode

Use this shortcut to toggle admin mode:

```text
Alt + Shift + S
```

Admin mode enables editing features such as show management, output settings, page/block editing, and the Art-Net viewer menu.

## User Data

Installed builds store user settings and shows in:

```text
C:\ProgramData\LumiControLL
```

During uninstall, the uninstaller asks whether this user data should also be removed.

When running from source, runtime data is stored next to `app.py` for easier development.

## USB DMX Driver Setup

The installer includes `zadig-2.9.exe` in the LumiControLL program folder.

If LumiControLL cannot open a uDMX or Open DMX dongle, install a suitable USB driver with Zadig. The included guide explains the steps:

```text
docs/USB_DMX_Zadig_driver_installation_EN.txt
```

Recommended first driver choice for uDMX is `libusbK`. For Open DMX / FTDI clones, LumiControLL supports two driver routes:

- Zadig/libusb route: install `libusb-win32`, `libusbK`, or `WinUSB` on the FTDI/Open DMX device. LumiControLL uses `pyftdi` for this route.
- FTDI VCP/COM route: install the official FTDI driver so Windows shows the adapter as a `USB Serial Port (COMx)`. LumiControLL can auto-detect FTDI COM ports.

Official FTDI drivers are available here:

[FTDI D2XX/VCP drivers](https://ftdichip.com/drivers/d2xx-drivers/)

The default Open DMX break mode is `serialbreak`, which is the standard choice for original ENTTEC Open DMX interfaces. Some USB-RS485 FTDI clones with automatic direction control need the `baudzero` workaround instead. This can be selected in **Output Settings > Open DMX break**.

If multiple FTDI devices are connected, set `LUMICONTROLL_OPENDMX_PORT` to the desired COM port, for example `COM11`. You can force a specific route with `LUMICONTROLL_OPENDMX_MODE=libusb` or `LUMICONTROLL_OPENDMX_MODE=com`, and force a break mode with `LUMICONTROLL_OPENDMX_BREAK=serialbreak` or `LUMICONTROLL_OPENDMX_BREAK=baudzero`.

## Building From Source

Install Python, then install the dependencies:

```powershell
python -m pip install -r requirements.txt
```

Build the application executables:

```bat
build_app.bat
```

Build the Windows installer:

```bat
build_installer.bat
```

The installer build requires Inno Setup 6.

## Repository Layout

```text
app.py                         Main LumiControLL application
viewer.py                      Art-Net viewer
editor.py                      Chase/scene editor
audiodetector.py               Audio pulse detection
udmx_backend.py                uDMX USB backend
installer/                     Inno Setup installer definition
installer_defaults/            Clean default settings and empty default show
docs/                          User documentation
third_party_licenses/          Third-party license texts and notices
```

Generated files such as `build/`, `dist/`, and `installer_output/` are not committed.

## License

LumiControLL is provided under the [LumiControLL Non-Commercial License](LICENSE.txt).

Summary:

- Free use is allowed for personal, educational, and non-profit purposes.
- Commercial use requires prior written permission from Lesley Lemmens.
- Modified versions, forks, or derivative works may not be published as separate products or under another name.
- Updates and fixes may be contributed back to the original LumiControLL project.

This summary is not a replacement for the full license text. See [LICENSE.txt](LICENSE.txt).

## Third-Party Software

This project includes or uses third-party software:

- Zadig, licensed under GPLv3-or-later
- libwdi, licensed under LGPLv3-or-later
- stupidArtnet, licensed under MIT
- Art-Net protocol name and specification by Artistic Licence Engineering Ltd

License texts and source links are included in [third_party_licenses](third_party_licenses/).

## Author

LumiControLL is created by Lesley Lemmens.
