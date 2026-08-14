# udmx_backend.py — libusb1 backend + caching + sneller defaults
import os, sys, time, ctypes
from pathlib import Path
from typing import Optional
from usb.core import USBError  # type: ignore

os.environ["PYUSB_BACKEND"] = "libusb1"

# Snelle, veilige defaults; app geeft chunk_size en delay live door
_CHUNK_SIZE        = 64
_INTER_CHUNK_DELAY = 0.0
_RETRY_MAX         = 3
_RETRY_BACKOFF     = 0.005

def _resolve_libusb1_dll() -> Optional[Path]:
    local = Path(sys.argv[0]).with_name("libusb-1.0.dll")
    if local.exists():
        return local.resolve()
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if bundle_dir:
        bundled = Path(bundle_dir) / "libusb-1.0.dll"
        if bundled.exists():
            return bundled.resolve()
    try:
        import importlib.resources as ir
        import libusb_package
        p = ir.files("libusb_package") / "libusb-1.0.dll"
        if p.exists():
            return Path(p).resolve()
    except Exception:
        pass
    return None

def _build_libusb1_backend(dll: Path):
    from usb.backend import libusb1 as be1
    from usb import core as usbcore
    try:
        os.add_dll_directory(str(dll.parent))
    except Exception:
        pass
    dll_abs = str(dll)
    backend = be1.get_backend(find_library=lambda _name: dll_abs)
    if backend is None:
        backend = be1.get_backend(find_library=lambda _name: dll_abs)
    if backend is None:
        raise RuntimeError(f"Kon libusb1-backend niet starten met {dll_abs}")
    _orig_find = usbcore.find
    def _find_with_backend(*args, **kwargs):
        kwargs["backend"] = backend
        return _orig_find(*args, **kwargs)
    usbcore.find = _find_with_backend
    return backend

def _is_libusb1_dll_loaded(expected_dll: Path) -> bool:
    if os.name != "nt":
        return True
    h = ctypes.windll.kernel32.GetModuleHandleW("libusb-1.0.dll")
    if not h:
        return False
    buf = ctypes.create_unicode_buffer(1024)
    n = ctypes.windll.kernel32.GetModuleFileNameW(h, buf, 1024)
    if n == 0:
        return True
    loaded = Path(buf.value).resolve()
    return (loaded == expected_dll.resolve()) or (loaded.name.lower() == expected_dll.name.lower())

def _with_retry(send_fn, *args):
    last = None
    for _ in range(_RETRY_MAX):
        try:
            return send_fn(*args)
        except USBError as e:
            last = e
            time.sleep(_RETRY_BACKOFF)
    if last:
        raise last

class UDMX:
    """uDMX helper met caching: open/close, send_universe, blackout."""
    def __init__(self):
        self.dev = None
        self._dll: Optional[Path] = None
        self._last_frame: Optional[bytes] = None

    def open(self):
        if self.dev:
            return self
        self._dll = _resolve_libusb1_dll()
        if not self._dll:
            raise RuntimeError("Geen libusb-1.0.dll gevonden.")
        _build_libusb1_backend(self._dll)

        # pyudmx zoekt het first-matching device; op Windows is driver-per-poort
        # via Zadig (libusbK/libusb-win32). Voor andere poorten: driver opnieuw
        # toewijzen met Zadig voor die device instance.
        from pyudmx import pyudmx
        self.dev = pyudmx.uDMXDevice()
        self.dev.open()
        time.sleep(0.02)

        if not _is_libusb1_dll_loaded(self._dll):
            raise RuntimeError("libusb-1.0.dll lijkt niet geladen.")
        print(f"[info] uDMX geopend met {self._dll}")
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

    def send_universe(self, data: bytes | bytearray,
                      chunk_size: int = _CHUNK_SIZE,
                      inter_delay: float = _INTER_CHUNK_DELAY,
                      force: bool = False):
        if not self.dev:
            return
        if len(data) != 512:
            raise ValueError("universe moet precies 512 bytes zijn")
        chunk_size = max(1, min(512, int(chunk_size)))
        b = bytes(data)
        if (not force) and self._last_frame == b:
            return
        self._last_frame = b

        for off in range(0, 512, chunk_size):
            start = off + 1
            chunk = list(b[off:off+chunk_size])
            try:
                _with_retry(self.dev.send_multi_value, start, chunk)
            except Exception:
                for i, v in enumerate(chunk, start=start):
                    _with_retry(self.dev.send_single_value, i, v)
            if inter_delay:
                time.sleep(inter_delay)

    def blackout(self):
        self.send_universe(bytes(512), force=True)
