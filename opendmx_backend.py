# opendmx_backend.py - ENTTEC Open DMX USB / FTDI clone backend
import os
import time
from typing import Optional

from pyftdi.ftdi import Ftdi


DEFAULT_FTDI_URLS = (
    "ftdi://ftdi:232/1",
    "ftdi://ftdi:232r/1",
    "ftdi://ftdi:230x/1",
    "ftdi://ftdi:ft-x/1",
    "ftdi://ftdi:232h/1",
)
DMX_BAUDRATE = 250000
BREAK_SECONDS = 0.00012
MAB_SECONDS = 0.000012


class OpenDMX:
    """Open DMX helper for FTDI based dongles using pyftdi/libusb."""

    def __init__(self, url: Optional[str] = None):
        env_url = os.environ.get("LUMICONTROLL_OPENDMX_URL")
        self.url = url or env_url
        self._candidate_urls = (self.url,) if self.url else DEFAULT_FTDI_URLS
        self.dev: Optional[Ftdi] = None
        self._last_frame: Optional[bytes] = None

    def open(self):
        if self.dev:
            return self

        last_error = None
        for candidate_url in self._candidate_urls:
            dev = Ftdi()
            try:
                dev.open_from_url(candidate_url)
                self.url = candidate_url
                break
            except Exception as exc:
                last_error = exc
                try:
                    dev.close()
                except Exception:
                    pass
        else:
            devices = self._format_devices()
            hint = (
                "Geen Open DMX FTDI device gevonden via pyftdi. "
                "Installeer met Zadig een libusb-win32 driver op de FTDI/Open DMX interface."
            )
            if devices:
                hint += f" Gevonden FTDI devices: {devices}"
            raise RuntimeError(hint) from last_error

        dev.set_baudrate(DMX_BAUDRATE)
        dev.set_line_property(8, 2, "N")
        try:
            dev.write_data_set_chunksize(513)
        except Exception:
            pass
        self.dev = dev
        self._last_frame = None
        print(f"[info] Open DMX geopend met {self.url}")
        return self

    def close(self):
        try:
            self.blackout()
        except Exception:
            pass
        try:
            if self.dev:
                self.dev.close()
        except Exception:
            pass
        self.dev = None
        self._last_frame = None

    def send_universe(self, data: bytes | bytearray, force: bool = False, **_kwargs):
        if not self.dev:
            return
        if len(data) != 512:
            raise ValueError("universe moet precies 512 bytes zijn")

        b = bytes(data)
        if (not force) and self._last_frame == b:
            return
        self._last_frame = b

        self.dev.set_break(True)
        time.sleep(BREAK_SECONDS)
        self.dev.set_break(False)
        time.sleep(MAB_SECONDS)
        self.dev.write_data(bytes([0]) + b)

    def blackout(self):
        self.send_universe(bytes(512), force=True)

    @staticmethod
    def _format_devices() -> str:
        try:
            found = Ftdi.list_devices("ftdi:///?")
        except Exception:
            return ""
        labels = []
        for desc, interface in found:
            serial = getattr(desc, "sn", "") or getattr(desc, "serial", "") or "no-serial"
            product = getattr(desc, "description", "") or getattr(desc, "product", "") or "FTDI"
            labels.append(f"{product}/{serial}/if{interface}")
        return ", ".join(labels)
