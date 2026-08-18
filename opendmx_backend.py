# opendmx_backend.py - ENTTEC Open DMX USB / FTDI clone backend
import os
import time
from typing import Optional

from pyftdi.ftdi import Ftdi
from serial import Serial
from serial.tools import list_ports


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
BREAK_BAUDRATE = 57600
BREAK_MODE = os.environ.get("LUMICONTROLL_OPENDMX_BREAK", "baudzero").lower()


class OpenDMX:
    """Open DMX helper for FTDI based dongles.

    Supports the original pyftdi/libusb path and a VCP COM-port fallback. The
    COM path uses a baud-rate break workaround for USB-RS485 adapters whose
    automatic direction control does not pass SerialPort break reliably.
    """

    def __init__(self, url: Optional[str] = None, port: Optional[str] = None):
        env_url = os.environ.get("LUMICONTROLL_OPENDMX_URL")
        env_port = os.environ.get("LUMICONTROLL_OPENDMX_PORT")
        env_mode = os.environ.get("LUMICONTROLL_OPENDMX_MODE", "auto").lower()
        self.url = url or env_url
        self.port = port or env_port
        self.mode = env_mode if env_mode in ("auto", "libusb", "com") else "auto"
        self._candidate_urls = (self.url,) if self.url else DEFAULT_FTDI_URLS
        self.dev: Optional[Ftdi] = None
        self.serial: Optional[Serial] = None
        self.active_mode: Optional[str] = None
        self._last_frame: Optional[bytes] = None

    def open(self):
        if self.dev or self.serial:
            return self

        errors = []
        if self.mode in ("auto", "libusb"):
            try:
                return self._open_libusb()
            except Exception as exc:
                errors.append(exc)
                if self.mode == "libusb":
                    raise

        if self.mode in ("auto", "com"):
            try:
                return self._open_com()
            except Exception as exc:
                errors.append(exc)
                if self.mode == "com":
                    raise

        devices = self._format_devices()
        ports = self._format_ports()
        hint = (
            "Geen Open DMX FTDI device gevonden via pyftdi/libusb of COM-poort. "
            "Gebruik libusb-win32/libusbK/WinUSB voor pyftdi, of FTDI VCP voor COM."
        )
        if devices:
            hint += f" Gevonden FTDI devices: {devices}."
        if ports:
            hint += f" Gevonden FTDI COM-poorten: {ports}."
        raise RuntimeError(hint) from (errors[-1] if errors else None)

    def _open_libusb(self):
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
        self.serial = None
        self.active_mode = "libusb"
        self._last_frame = None
        print(f"[info] Open DMX geopend met {self.url}")
        return self

    def _open_com(self):
        port = self.port or self._find_ftdi_com_port()
        if not port:
            ports = self._format_ports()
            hint = "Geen FTDI COM-poort gevonden voor Open DMX."
            if ports:
                hint += f" Beschikbare FTDI COM-poorten: {ports}"
            raise RuntimeError(hint)

        ser = Serial(
            port=port,
            baudrate=DMX_BAUDRATE,
            bytesize=8,
            parity="N",
            stopbits=2,
            timeout=1,
            write_timeout=1,
        )
        self.serial = ser
        self.dev = None
        self.port = port
        self.active_mode = "com"
        self._last_frame = None
        print(f"[info] Open DMX geopend met {self.port} (FTDI COM, BaudZero break)")
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
        try:
            if self.serial:
                self.serial.close()
        except Exception:
            pass
        self.dev = None
        self.serial = None
        self.active_mode = None
        self._last_frame = None

    def send_universe(self, data: bytes | bytearray, force: bool = False, **_kwargs):
        if not self.dev and not self.serial:
            return
        if len(data) != 512:
            raise ValueError("universe moet precies 512 bytes zijn")

        b = bytes(data)
        if (not force) and self._last_frame == b:
            return
        self._last_frame = b

        if self.serial:
            self._send_com_frame(b)
        elif self.dev:
            self._send_libusb_frame(b)

    def _send_libusb_frame(self, data: bytes):
        if not self.dev:
            return
        if BREAK_MODE == "serialbreak":
            self.dev.set_break(True)
            time.sleep(BREAK_SECONDS)
            self.dev.set_break(False)
            time.sleep(MAB_SECONDS)
            self.dev.write_data(bytes([0]) + data)
            return

        self.dev.set_baudrate(BREAK_BAUDRATE)
        self.dev.write_data(b"\x00")
        time.sleep(0.001)
        self.dev.set_baudrate(DMX_BAUDRATE)
        time.sleep(MAB_SECONDS)
        self.dev.write_data(bytes([0]) + data)

    def _send_com_frame(self, data: bytes):
        if not self.serial:
            return
        self.serial.baudrate = BREAK_BAUDRATE
        self.serial.write(b"\x00")
        self.serial.flush()
        time.sleep(0.001)
        self.serial.baudrate = DMX_BAUDRATE
        time.sleep(MAB_SECONDS)
        self.serial.write(bytes([0]) + data)

    def blackout(self):
        self.send_universe(bytes(512), force=True)

    @staticmethod
    def _find_ftdi_com_port() -> str:
        ports = []
        for port in list_ports.comports():
            vid = getattr(port, "vid", None)
            manufacturer = (getattr(port, "manufacturer", "") or "").lower()
            description = (getattr(port, "description", "") or "").lower()
            hwid = (getattr(port, "hwid", "") or "").lower()
            is_ftdi = (
                vid == 0x0403
                or "ftdi" in manufacturer
                or "ftdi" in description
                or "vid:pid=0403:" in hwid
            )
            if is_ftdi:
                ports.append(port.device)
        return ports[0] if ports else ""

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

    @staticmethod
    def _format_ports() -> str:
        labels = []
        for port in list_ports.comports():
            vid = getattr(port, "vid", None)
            if vid != 0x0403 and "FTDI" not in (getattr(port, "manufacturer", "") or ""):
                continue
            labels.append(f"{port.device} ({port.description})")
        return ", ".join(labels)
