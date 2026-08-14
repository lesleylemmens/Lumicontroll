# audiodetector.py
# Alle audio-detectie + sound-instellingen in één module.

import os
import sys
import json
import time
import threading
import queue as _queue

# Optionele audio deps
try:
    import numpy as np
    import sounddevice as sd
    _AUDIO_CORE_OK = True
except Exception:
    _AUDIO_CORE_OK = False
    np = None
    sd = None

try:
    import soundcard as sc
    _SOUNDCARD_OK = True
except Exception:
    sc = None
    _SOUNDCARD_OK = False

try:
    import pyaudiowpatch as paw
    _PYAUDIOWPATCH_OK = True
except Exception:
    paw = None
    _PYAUDIOWPATCH_OK = False

# Optionele SciPy (voor IIR bandpass); anders FFT fallback
try:
    from scipy.signal import get_window, butter, sosfilt
    _SCIPY_OK = True
except Exception:
    _SCIPY_OK = False

# --- instellingenbestand ---
# In ontwikkeling blijven settings naast app.py. In de gebouwde exe staan
# gebruikersinstellingen in %APPDATA%\LumiControLL, zodat updates ze bewaren.
APP_DATA_FOLDER = "LumiControLL"
_base_dir = os.path.dirname(os.path.abspath(sys.argv[0]))

def _is_frozen_app():
    return bool(getattr(sys, "frozen", False))

def _app_data_directory():
    if not _is_frozen_app():
        return _base_dir
    base = os.environ.get("PROGRAMDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DATA_FOLDER)

_data_dir = _app_data_directory()
SOUND_SETTINGS_FILE = os.path.join(_data_dir, "sound_settings.json")

def _prepare_sound_settings_file():
    if os.path.abspath(_data_dir).lower() == os.path.abspath(_base_dir).lower():
        return
    installed_settings = os.path.join(_base_dir, "sound_settings.json")
    if os.path.exists(SOUND_SETTINGS_FILE) or not os.path.exists(installed_settings):
        return
    try:
        os.makedirs(_data_dir, exist_ok=True)
        with open(installed_settings, "rb") as src, open(SOUND_SETTINGS_FILE, "wb") as dst:
            dst.write(src.read())
    except Exception:
        pass

_prepare_sound_settings_file()

DEFAULT_SOUND_SETTINGS = {
    "mode":   "Full Peak",
    "thr":    0.70,
    "minint": 180,
    "hold":   120,
    "slope":  0.00,
    "source_type": "input",
    "input_device": None,
    "input_device_name": "",
}

def load_sound_settings():
    try:
        if os.path.isfile(SOUND_SETTINGS_FILE):
            with open(SOUND_SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in DEFAULT_SOUND_SETTINGS.items():
                if k not in data:
                    data[k] = v
            return data
    except Exception:
        pass
    return DEFAULT_SOUND_SETTINGS.copy()

def save_sound_settings(d):
    try:
        os.makedirs(os.path.dirname(SOUND_SETTINGS_FILE), exist_ok=True)
        tmp = SOUND_SETTINGS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        os.replace(tmp, SOUND_SETTINGS_FILE)
    except Exception:
        pass

def is_audio_available() -> bool:
    """True als numpy + sounddevice beschikbaar zijn."""
    return bool(_AUDIO_CORE_OK)

def refresh_audio_devices():
    if not _AUDIO_CORE_OK:
        return
    try:
        sd._terminate()
        sd._initialize()
    except Exception:
        pass

def list_input_devices(refresh=False, usable_only=False):
    if not _AUDIO_CORE_OK:
        return []
    if refresh:
        refresh_audio_devices()
    try:
        devices = sd.query_devices()
    except Exception:
        return []
    inputs = []
    for idx, dev in enumerate(devices):
        try:
            channels = int(dev.get("max_input_channels", 0))
        except Exception:
            channels = 0
        if channels > 0:
            usable = True
            error = ""
            try:
                samplerate = float(dev.get("default_samplerate", 48000) or 48000)
                sd.check_input_settings(device=idx, channels=1, dtype="float32", samplerate=samplerate)
            except Exception:
                usable = False
                error = "Cannot open this input device."
            if usable_only and not usable:
                continue
            inputs.append({
                "index": idx,
                "name": str(dev.get("name", f"Input {idx}")),
                "source_type": "input",
                "channels": channels,
                "usable": usable,
                "error": error,
            })
    return inputs

def list_loopback_devices(refresh=False, usable_only=False):
    if not _PYAUDIOWPATCH_OK or not sys.platform.startswith("win"):
        return []
    try:
        pa = paw.PyAudio()
        devices = list(pa.get_loopback_device_info_generator())
    except Exception:
        return []
    finally:
        try:
            pa.terminate()
        except Exception:
            pass
    outputs = []
    for dev in devices:
        channels = int(dev.get("maxInputChannels", 0) or 0)
        if channels <= 0:
            continue
        outputs.append({
            "index": int(dev.get("index")),
            "name": str(dev.get("name", f"PC Audio {dev.get('index')}")).replace(" [Loopback]", ""),
            "source_type": "loopback",
            "channels": channels,
            "usable": True,
            "error": "",
            "samplerate": int(float(dev.get("defaultSampleRate", 48000) or 48000)),
        })
    return outputs

# ----------------------------------------------------------------------
# AudioPulseDetector — SciPy/IIR variant (fallback naar compacte FFT)
# ----------------------------------------------------------------------
class AudioPulseDetector:
    DETECT_MODES = [
        "Full RMS",
        "Full Peak",
        "Bass (20–150 Hz)",
        "Bass (50–100 Hz)",
        "Mid (150–1500 Hz)",
        "High (1500–8000 Hz)",
        "Spectral Flux",
    ]

    def __init__(self, settings: dict, on_pulse):
        """
        settings: dict met keys zoals DEFAULT_SOUND_SETTINGS
        on_pulse: callback zonder args; wordt geroepen bij gedetecteerde puls
        """
        self.sr   = 48000
        self.bs   = 1024
        self.mode = settings.get("mode", "Full RMS")
        self.threshold       = float(settings.get("thr", 0.70))
        self.min_interval_ms = int(settings.get("minint", 180))
        self.hold_ms         = int(settings.get("hold", 120))
        self.min_slope       = float(settings.get("slope", 0.00))
        self.smoothing       = 0.40
        self.autogain        = True
        self.source_type = str(settings.get("source_type", "input") or "input")
        if self.source_type not in ("input", "loopback"):
            self.source_type = "input"
        try:
            self.input_device = settings.get("input_device")
            if self.input_device is not None and self.source_type != "loopback":
                self.input_device = int(self.input_device)
        except Exception:
            self.input_device = None
        if _AUDIO_CORE_OK and self.input_device is not None:
            try:
                kind = "output" if self.source_type == "loopback" else "input"
                dev = sd.query_devices(self.input_device, kind)
                self.sr = int(float(dev.get("default_samplerate", self.sr)) or self.sr)
                if self.source_type == "loopback":
                    self.stream_channels = max(1, min(2, int(dev.get("max_output_channels", 2) or 2)))
                else:
                    self.stream_channels = 1
            except Exception:
                self.stream_channels = 1
        else:
            self.stream_channels = 1

        self._ag_avg   = 0.01
        self._env      = 0.0
        self._p2       = 0.0
        self._p1       = 0.0
        self._last_ts  = 0.0
        self._hold_until = 0.0
        self._prev_spec = None

        self._q = _queue.Queue()
        self._stream = None
        self._recorder_cm = None
        self._recorder = None
        self._loopback_mic = None
        self._pa = None
        self._thread = None
        self._running = False
        self._started_ts = 0.0
        self._last_callback_ts = 0.0
        self._last_status = ""
        self._failed = False
        self.on_pulse = on_pulse

        if _AUDIO_CORE_OK:
            if _SCIPY_OK:
                try:
                    self._win = get_window('hann', self.bs, fftbins=True)
                except Exception:
                    self._win = None
            else:
                try:
                    self._win = np.hanning(self.bs)
                except Exception:
                    self._win = None
        else:
            self._win = None

        self._sos_cache = {}
        self._zi_cache  = {}

    # ===== intern: audio callbacks/threads =====
    def _cb(self, indata, frames, t, status):
        self._last_callback_ts = time.monotonic()
        if status:
            self._last_status = str(status)
        x = indata.copy().astype(np.float32)
        if x.ndim > 1:
            x = np.mean(x, axis=1)
        self._q.put(x)

    def _finished(self):
        if self._running:
            self._failed = True
            self._last_status = self._last_status or "Microphone stream stopped."

    @staticmethod
    def _ema(prev, new, alpha): return alpha*new + (1-alpha)*prev

    @staticmethod
    def _limiter(x):
        if x <= 1.0:
            return x
        y = 1 + (x - 1) / (1 + (x - 1))
        return min(y, 1.2)

    def _autogain_scale(self, v):
        if not self.autogain:
            return v
        dt = self.bs / float(self.sr)
        alpha = min(max(dt/(1.0+dt), 0.001), 0.5)
        self._ag_avg = self._ema(self._ag_avg, v, alpha)
        return self._limiter(v / (self._ag_avg + 1e-8))

    def _smooth(self, v):
        a = self.smoothing
        self._env = v if a <= 0 else self._ema(self._env, v, a)
        return self._env

    def _should_fire(self, m):
        now = time.monotonic() * 1000.0
        if now < self._hold_until:
            self._p2, self._p1 = self._p1, m
            return False
        if (now - self._last_ts) < self.min_interval_ms:
            self._p2, self._p1 = self._p1, m
            return False
        thr = float(self.threshold)
        is_peak = (self._p2 < self._p1) and (self._p1 >= thr) and (m < self._p1)
        if is_peak and ((self._p1 - self._p2) >= float(self.min_slope)):
            self._last_ts = now
            self._hold_until = now + self.hold_ms
            self._p2, self._p1 = self._p1, m
            return True
        self._p2, self._p1 = self._p1, m
        return False

    # ===== metingen =====
    def _full_rms(self, x):
        return float(np.sqrt(np.mean(x*x) + 1e-8))

    def _full_peak(self, x):
        return float(np.max(np.abs(x) + 1e-8))

    def _sos_band_rms(self, x, f_lo, f_hi):
        if _SCIPY_OK:
            key = ("bp", f_lo, f_hi, 4, self.sr)
            if key not in self._sos_cache:
                nyq = 0.5 * self.sr
                lo  = max(f_lo/nyq, 1e-4)
                hi  = min(f_hi/nyq, 0.999)
                if hi <= lo:
                    hi = min(lo*1.2, 0.999)
                sos = butter(4, [lo, hi], btype="bandpass", output="sos")
                self._sos_cache[key] = sos
                import numpy as _np
                self._zi_cache[key]  = _np.zeros((sos.shape[0], 2), dtype=_np.float32)
            sos = self._sos_cache[key]
            zi = self._zi_cache[key]
            y, zf = sosfilt(sos, x, zi=zi)
            self._zi_cache[key] = zf
            return float(np.sqrt(np.mean(y*y) + 1e-8))

        # FFT fallback
        xf   = np.fft.rfft(x * (self._win if self._win is not None else 1.0))
        mag2 = (np.abs(xf)**2)
        freqs= np.fft.rfftfreq(len(x), d=1.0/self.sr)
        sel  = (freqs >= f_lo) & (freqs < f_hi)
        if not np.any(sel):
            return 0.0
        return float(np.sqrt(np.mean(mag2[sel]) + 1e-8))

    def _band_fft_energy(self, x, f_lo, f_hi):
        xf   = np.fft.rfft(x * (self._win if self._win is not None else 1.0))
        mag2 = (np.abs(xf)**2)
        freqs= np.fft.rfftfreq(len(x), d=1.0/self.sr)
        sel  = (freqs >= f_lo) & (freqs < f_hi)
        if not np.any(sel):
            return 0.0
        return float(np.sqrt(np.mean(mag2[sel]) + 1e-8))

    def _spectral_flux(self, x):
        mag = np.abs(np.fft.rfft(x * (self._win if self._win is not None else 1.0)))
        if self._prev_spec is None or len(self._prev_spec) != len(mag):
            self._prev_spec = mag
            return 0.0
        diff = mag - self._prev_spec
        flux = float(np.sum(diff[diff > 0.0])) / (len(mag) + 1e-8)
        self._prev_spec = mag
        return flux

    def _process_block(self, x):
        m = self.mode
        if   m == "Full RMS":            raw = self._full_rms(x)
        elif m == "Full Peak":           raw = self._full_peak(x)
        elif m == "Bass (20–150 Hz)":    raw = self._sos_band_rms(x, 20, 150)
        elif m == "Bass (50–100 Hz)":    raw = self._sos_band_rms(x, 50, 100)
        elif m == "Mid (150–1500 Hz)":   raw = self._band_fft_energy(x, 150, 1500)
        elif m == "High (1500–8000 Hz)": raw = self._band_fft_energy(x, 1500, 8000)
        elif m == "Spectral Flux":       raw = self._spectral_flux(x)
        else:                             raw = self._full_rms(x)
        # zachte clip
        import numpy as _np
        raw = _np.tanh(3.0*raw)
        met = self._smooth(self._autogain_scale(raw))
        if self._should_fire(met) and self.on_pulse:
            try:
                self.on_pulse()
            except Exception:
                pass

    def _worker(self):
        while self._running:
            try:
                x = self._q.get(timeout=0.2)
                self._process_block(x)
            except _queue.Empty:
                pass

    def _loopback_worker(self):
        try:
            while self._running:
                try:
                    x = self._q.get(timeout=0.5)
                    self._process_block(x)
                except _queue.Empty:
                    pass
        except Exception as e:
            self._failed = True
            self._last_status = str(e)

    def _loopback_cb(self, in_data, frame_count, time_info, status):
        try:
            self._last_callback_ts = time.monotonic()
            x = np.frombuffer(in_data, dtype=np.float32)
            if self.stream_channels > 1 and x.size >= self.stream_channels:
                x = x.reshape(-1, self.stream_channels).mean(axis=1)
            self._q.put(x.astype(np.float32, copy=False))
        except Exception as e:
            self._failed = True
            self._last_status = str(e)
        return (None, paw.paContinue)

    def start(self):
        if not _AUDIO_CORE_OK:
            return
        if self._running:
            return
        self._failed = False
        self._last_status = ""
        self._last_callback_ts = 0.0
        if self.source_type == "loopback":
            if not _PYAUDIOWPATCH_OK:
                raise RuntimeError("PC audio capture is not available.")
            self._pa = paw.PyAudio()
            dev = self._pa.get_device_info_by_index(int(self.input_device))
            self.sr = int(float(dev.get("defaultSampleRate", self.sr)) or self.sr)
            self.stream_channels = max(1, min(2, int(dev.get("maxInputChannels", 2) or 2)))
            self._stream = self._pa.open(
                format=paw.paFloat32,
                channels=self.stream_channels,
                rate=self.sr,
                input=True,
                input_device_index=int(self.input_device),
                frames_per_buffer=self.bs,
                stream_callback=self._loopback_cb,
            )
            self._running = True
            self._started_ts = time.monotonic()
            self._stream.start_stream()
            self._thread = threading.Thread(target=self._loopback_worker, daemon=True)
            self._thread.start()
            return
        extra_settings = None
        channel_options = [self.stream_channels]
        last_error = None
        for channels in channel_options:
            try:
                self._stream = sd.InputStream(
                    samplerate=self.sr, blocksize=self.bs, channels=channels,
                    dtype="float32", device=self.input_device, callback=self._cb,
                    finished_callback=self._finished, extra_settings=extra_settings
                )
                self.stream_channels = channels
                break
            except Exception as e:
                last_error = e
                self._stream = None
        if self._stream is None:
            raise last_error or RuntimeError("Could not open audio stream.")
        self._stream.start()
        self._running = True
        self._started_ts = time.monotonic()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._thread.start()

    def is_healthy(self):
        if self.source_type == "loopback":
            if not self._running or self._failed:
                return False
            if self._thread is not None and not self._thread.is_alive():
                return False
            return True
        if not self._running or self._stream is None or self._failed:
            return False
        try:
            if not bool(self._stream.active):
                return False
        except Exception:
            return False
        now = time.monotonic()
        if self._last_callback_ts <= 0.0:
            return (now - self._started_ts) < 2.5
        if (now - self._last_callback_ts) > 3.0:
            return False
        try:
            if self.source_type == "loopback":
                return bool(self._running and self._stream is not None and self._stream.is_active() and not self._failed)
            else:
                sd.check_input_settings(device=self.input_device, channels=1, dtype="float32", samplerate=self.sr)
        except Exception:
            return False
        return True

    def status_message(self):
        return self._last_status or "Microphone disconnected."

    def stop(self):
        self._running = False
        try:
            if self._stream:
                if hasattr(self._stream, "stop_stream"):
                    try:
                        self._stream.stop_stream()
                    except Exception:
                        pass
                elif hasattr(self._stream, "stop"):
                    self._stream.stop()
                self._stream.close()
            if self._pa:
                self._pa.terminate()
            if self.source_type == "loopback" and self._thread and self._thread.is_alive():
                self._thread.join(timeout=1.0)
        finally:
            self._stream = None
            self._recorder = None
            self._recorder_cm = None
            self._loopback_mic = None
            self._pa = None
