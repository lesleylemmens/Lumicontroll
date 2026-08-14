# app.py — LumiControLL v1.2 (Art-Net + uDMX)
import os, sys, json, time, shutil, subprocess, threading, tkinter as tk
import re
from tkinter import filedialog, messagebox
from tkinter import ttk

try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("LumiControLL.App")
except Exception:
    pass

# ----------------- Defaults -----------------
DMX_CHANNELS        = 128
BANK_SIZE           = 16
DEFAULT_TICK_MS     = 25
USB_RETRY_MS        = 5000        # backoff voor opnieuw openen
STATUS_REFRESH_MS   = 1000
DEFAULT_USB_FPS     = 33
DEFAULT_CHUNK_SIZE  = 64
DEFAULT_INTER_DELAY = 0.0
DEFAULT_USB_ALWAYS_SEND = False

# Runtime configurables (laden uit settings)
PLAYBACK_TICK_MS     = DEFAULT_TICK_MS
USB_SEND_MIN_INTERVAL_MS = int(round(1000.0 / max(1, DEFAULT_USB_FPS)))
USB_CHUNK_SIZE       = DEFAULT_CHUNK_SIZE
USB_INTER_DELAY_MS   = DEFAULT_INTER_DELAY
USB_ALWAYS_SEND      = DEFAULT_USB_ALWAYS_SEND

# ----------------- Optionele hotkey -----------------
try:
    import keyboard
except Exception:
    keyboard = None

# ----------------- Art-Net -----------------
ARTNET_AVAILABLE = True
ARTNET_IMPORT_ERROR = None
try:
    from stupidArtnet import StupidArtnet
except Exception as e:
    ARTNET_AVAILABLE = False
    ARTNET_IMPORT_ERROR = e
    class StupidArtnet:
        def __init__(self, ip, universe, length): pass
        def set(self, data): pass
        def show(self): pass

# ----------------- Editor & Audio -----------------
from editor import init_editor, open_scene_editor, is_editor_open
from audiodetector import (
    AudioPulseDetector,
    load_sound_settings,
    save_sound_settings,
    is_audio_available,
    list_input_devices,
    list_loopback_devices,
)

# ----------------- USB backend -----------------
from udmx_backend import UDMX

# ----------------- paden & files -----------------
script_directory = os.path.dirname(os.path.abspath(sys.argv[0]))
os.chdir(script_directory)

APP_DATA_FOLDER = "LumiControLL"

def _is_frozen_app():
    return bool(getattr(sys, "frozen", False))

def _app_data_directory():
    if not _is_frozen_app():
        return script_directory
    base = os.environ.get("PROGRAMDATA") or os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, APP_DATA_FOLDER)

data_directory = _app_data_directory()

settings_file = os.path.join(data_directory, "settings.config")
legacy_scenes_file = os.path.join(data_directory, "scenes.config")
shows_dir     = os.path.join(data_directory, "shows")
icon_file     = os.path.join(script_directory, "an.ico")
adm_file      = os.path.join(data_directory, "adm.config")
readme_file   = os.path.join(script_directory, "readme.pdf")
third_party_licenses_dir = os.path.join(script_directory, "third_party_licenses")
udmx_driver_guide_file = os.path.join(script_directory, "docs", "uDMX_Zadig_driver_installatie_NL.txt")
viewer_exe    = os.path.join(script_directory, "viewer.exe")
viewer_py     = os.path.join(script_directory, "viewer.py")
SHOW_EXTENSION = ".lumishow"
LEGACY_SHOW_EXTENSIONS = (".show.json", ".json", ".config")
ALL_SHOW_EXTENSIONS = (SHOW_EXTENSION,) + LEGACY_SHOW_EXTENSIONS

def _copy_first_run_file(src, dst):
    if os.path.exists(dst) or not os.path.exists(src):
        return
    try:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
    except Exception:
        pass

def _prepare_user_data_files():
    os.makedirs(data_directory, exist_ok=True)
    if os.path.abspath(data_directory).lower() == os.path.abspath(script_directory).lower():
        return

    _copy_first_run_file(
        os.path.join(script_directory, "settings.config"),
        settings_file,
    )
    _copy_first_run_file(
        os.path.join(script_directory, "adm.config"),
        adm_file,
    )

    installed_shows_dir = os.path.join(script_directory, "shows")
    if not os.path.exists(shows_dir) and os.path.isdir(installed_shows_dir):
        try:
            shutil.copytree(installed_shows_dir, shows_dir)
        except Exception:
            pass

_prepare_user_data_files()

# ----------------- Settings & defaults -----------------
default_settings = {
    "node_ip": "192.168.1.100",
    "universe": 0,
    "bpm": 120,
    "output_mode": "artnet",       # "artnet" | "usb" | "both"
    # performance
    "playback_tick_ms": DEFAULT_TICK_MS,
    "usb_fps": DEFAULT_USB_FPS,
    "usb_chunk_size": DEFAULT_CHUNK_SIZE,
    "usb_inter_delay_ms": DEFAULT_INTER_DELAY,
    "usb_always_send": DEFAULT_USB_ALWAYS_SEND,
    "block_view": "4",
    "current_show": "default.lumishow",
}
def _empty_chase(name="New chase"):
    return {
        "name": name,
        "values": [0] * DMX_CHANNELS,
        "timing_mode": "duration",
        "repeat": True,
        "fade": False,
        "button_color": "",
        "steps": [{"name": "Step 1", "values": [0] * DMX_CHANNELS, "duration_ms": 500}],
    }

def _new_show_pages():
    return [
        {"name": "Page 1", "solo": False, "chases": []},
        {"name": "Page 2", "solo": False, "chases": []},
        {"name": "Page 3", "solo": False, "chases": []},
        {"name": "Page 4", "solo": False, "chases": []},
    ]

def _new_block_slots(count=8):
    return [{"page": i if i < 4 else None} for i in range(count)]

# Admin flag
try:
    if not os.path.exists(adm_file):
        with open(adm_file, 'w', encoding='utf-8') as _f: _f.write('0')
    with open(adm_file, 'r', encoding='utf-8') as _f:
        adm_permission = _f.read().strip() or '0'
except Exception:
    adm_permission = '0'

def _set_window_icon(win):
    try:
        if os.path.exists(icon_file):
            try:
                win.iconbitmap(default=icon_file)
            except Exception:
                win.iconbitmap(icon_file)
            try:
                win.iconphoto(True, tk.PhotoImage(file=icon_file))
            except Exception:
                pass
    except Exception:
        pass

def _ask_text(title, prompt, initialvalue="", parent=None):
    parent = parent or root
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.resizable(False, False)
    win.transient(parent); win.grab_set()
    frm = tk.Frame(win, padx=16, pady=16); frm.pack(fill="both", expand=True)
    tk.Label(frm, text=prompt, anchor="w").pack(fill="x", pady=(0, 8))
    var = tk.StringVar(value=str(initialvalue or ""))
    ent = tk.Entry(frm, textvariable=var, width=32)
    ent.pack(fill="x", pady=(0, 10))
    result = {"value": None}
    def ok():
        result["value"] = var.get()
        try: win.grab_release()
        except Exception: pass
        win.destroy()
    def cancel():
        try: win.grab_release()
        except Exception: pass
        win.destroy()
    row = tk.Frame(frm); row.pack(fill="x")
    tk.Button(row, text="Cancel", width=10, command=cancel).pack(side="right")
    tk.Button(row, text="OK", width=10, command=ok).pack(side="right", padx=(0, 6))
    win.bind("<Return>", lambda e: ok())
    win.bind("<Escape>", lambda e: cancel())
    win.protocol("WM_DELETE_WINDOW", cancel)
    win.update_idletasks()
    try:
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        x = px + (pw - ww) // 2
        y = py + (ph - wh) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass
    win.after(10, lambda: (ent.focus_set(), ent.selection_range(0, "end")))
    win.wait_window()
    return result["value"]

def _ask_integer(title, prompt, initialvalue=0, minvalue=None, maxvalue=None, parent=None):
    while True:
        raw = _ask_text(title, prompt, str(initialvalue), parent=parent)
        if raw is None:
            return None
        try:
            value = int(raw)
            if minvalue is not None and value < minvalue:
                raise ValueError
            if maxvalue is not None and value > maxvalue:
                raise ValueError
            return value
        except Exception:
            messagebox.showwarning(title, "Please enter a valid integer.", parent=parent or root)

def _load_settings():
    if not os.path.exists(settings_file):
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, indent=4)
        return default_settings.copy()
    try:
        with open(settings_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("settings.config moet een JSON object zijn")
        merged = default_settings.copy()
        merged.update(data)
        return merged
    except Exception:
        backup = f"{settings_file}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
        try:
            shutil.copy2(settings_file, backup)
        except Exception:
            pass
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(default_settings, f, indent=4)
        return default_settings.copy()

settings = _load_settings()

def _read_setting(key, fallback):
    try:
        return settings.get(key, fallback)
    except Exception:
        return fallback

def _read_int_setting(key, fallback, min_value=None, max_value=None):
    try:
        value = int(_read_setting(key, fallback))
    except Exception:
        value = int(fallback)
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def _read_float_setting(key, fallback, min_value=None, max_value=None):
    try:
        value = float(_read_setting(key, fallback))
    except Exception:
        value = float(fallback)
    if min_value is not None:
        value = max(min_value, value)
    if max_value is not None:
        value = min(max_value, value)
    return value

def _read_bool_setting(key, fallback):
    value = _read_setting(key, fallback)
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)

node_ip       = _read_setting("node_ip", "192.168.1.100")
universe      = _read_int_setting("universe", 0, 0, 32767)
bpm           = _read_int_setting("bpm", 120, 1, 400)
output_mode   = str(_read_setting("output_mode", "artnet"))
if output_mode not in ("artnet", "usb", "both"):
    output_mode = "artnet"
block_view    = str(_read_setting("block_view", "4"))
if block_view not in ("1", "2", "3", "4", "6", "8"):
    block_view = "4"
current_show  = str(_read_setting("current_show", "default.lumishow") or "default.lumishow")
dmx_channels  = DMX_CHANNELS

# Performance inlezen
PLAYBACK_TICK_MS    = _read_int_setting("playback_tick_ms", DEFAULT_TICK_MS, 1)
_usb_fps            = _read_int_setting("usb_fps", DEFAULT_USB_FPS, 1)
USB_SEND_MIN_INTERVAL_MS = int(round(1000.0 / max(1, _usb_fps)))
USB_CHUNK_SIZE      = _read_int_setting("usb_chunk_size", DEFAULT_CHUNK_SIZE, 1, 256)
USB_INTER_DELAY_MS  = _read_float_setting("usb_inter_delay_ms", DEFAULT_INTER_DELAY, 0.0)
USB_ALWAYS_SEND     = _read_bool_setting("usb_always_send", DEFAULT_USB_ALWAYS_SEND)

def save_settings():
    global block_view
    usb_fps = int(round(1000.0 / max(1, USB_SEND_MIN_INTERVAL_MS)))
    cfg = {
        "node_ip": node_ip,
        "universe": universe,
        "bpm": bpm,
        "output_mode": output_mode,
        "playback_tick_ms": int(PLAYBACK_TICK_MS),
        "usb_fps": usb_fps,
        "usb_chunk_size": int(USB_CHUNK_SIZE),
        "usb_inter_delay_ms": float(USB_INTER_DELAY_MS),
        "usb_always_send": bool(USB_ALWAYS_SEND),
        "block_view": str(block_view),
        "current_show": str(current_show),
    }
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(cfg, f, indent=4)

def _now_ms(): return int(time.time() * 1000)

# ----------------- Scenes/Blocks -----------------
def _clamp_dmx_values(values, length=DMX_CHANNELS):
    vals = list(values or [])
    out = []
    for v in vals[:length]:
        try:
            iv = int(v)
        except Exception:
            iv = 0
        out.append(max(0, min(255, iv)))
    if len(out) < length:
        out += [0] * (length - len(out))
    return out

def _normalise_chase(ch, idx=0):
    ch = dict(ch or {})
    ch["name"] = str(ch.get("name", f"Chase {idx + 1}"))
    ch["values"] = _clamp_dmx_values(ch.get("values", []))
    if isinstance(ch.get("steps"), list):
        new_steps = []
        for i, st in enumerate(ch["steps"]):
            st = dict(st or {})
            st["values"] = _clamp_dmx_values(st.get("values", ch["values"]))
            st["name"] = str(st.get("name", f"Step {i+1}"))
            try:
                st["duration_ms"] = max(1, int(st.get("duration_ms", 500)))
            except Exception:
                st["duration_ms"] = 500
            new_steps.append(st)
        ch["steps"] = new_steps
    ch["timing_mode"] = ch.get("timing_mode", "duration")
    ch["repeat"] = bool(ch.get("repeat", True))
    ch["fade"] = bool(ch.get("fade", False))
    color = str(ch.get("button_color", "") or "")
    ch["button_color"] = color if color.startswith("#") and len(color) == 7 else ""
    if not ch.get("steps"):
        ch["steps"] = [{"name": "Step 1", "values": ch["values"][:], "duration_ms": 500}]
    return ch

def _normalise_page(page, idx=0):
    page = dict(page or {})
    chases = page.get("chases", [])
    if not isinstance(chases, list):
        chases = []
    return {
        "name": str(page.get("name", f"Page {idx+1}")),
        "solo": bool(page.get("solo", False)),
        "chases": [_normalise_chase(ch, ci) for ci, ch in enumerate(chases)],
    }

def _normalise_block_slots(raw_slots, count=None):
    slots = raw_slots if isinstance(raw_slots, list) else []
    out = []
    for slot in slots:
        if isinstance(slot, dict):
            page = slot.get("page")
        else:
            page = slot
        try:
            page = int(page) if page is not None else None
        except Exception:
            page = None
        out.append({"page": page})
    target = count or max(4, len(out))
    while len(out) < target:
        out.append({"page": None})
    return out

def _normalise_show(raw):
    if not isinstance(raw, dict):
        raise ValueError("scenes.config moet een JSON object zijn")
    if isinstance(raw.get("pages"), list):
        pages_inline = [_normalise_page(p, i) for i, p in enumerate(raw["pages"])]
        slots = _normalise_block_slots(raw.get("blocks"), max(8, len(raw.get("blocks", []))))
    elif isinstance(raw.get("blocks"), list):
        pages_inline = [_normalise_page(blk, i) for i, blk in enumerate(raw["blocks"])]
        slots = _new_block_slots(max(4, len(pages_inline)))
    else:
        raise ValueError("scenes.config mist pages/blocks")
    if not pages_inline:
        pages_inline = _new_show_pages()
    for slot in slots:
        page = slot["page"]
        if page is not None and not (0 <= page < len(pages_inline)):
            slot["page"] = None
    return pages_inline, slots

def _visible_block_count():
    try:
        return int(block_view)
    except Exception:
        return 4

def _block_grid_shape():
    count = _visible_block_count()
    if count == 6:
        return 3, 2
    if count == 8:
        return 4, 2
    return max(1, count), 1

def _visible_blocks():
    visible = []
    for slot in block_slots[:_visible_block_count()]:
        page_idx = slot.get("page")
        if page_idx is None or not (0 <= page_idx < len(pages)):
            visible.append({"name": "None", "solo": False, "chases": [], "_none": True})
        else:
            visible.append(pages[page_idx])
    return visible

def _ensure_block_slots():
    while len(block_slots) < 8:
        block_slots.append({"page": None})

def _strip_show_extension(name):
    lowered = name.lower()
    for ext in ALL_SHOW_EXTENSIONS:
        if lowered.endswith(ext):
            return name[:-len(ext)]
    return name

def _safe_show_filename(name, prefer_lumishow=False):
    base = os.path.basename(str(name or "default.lumishow")).strip()
    if not base:
        base = "default.lumishow"
    safe = []
    for ch in base:
        safe.append(ch if (ch.isalnum() or ch in (" ", "-", "_", ".")) else "_")
    base = "".join(safe).strip(" .") or "default"
    if prefer_lumishow:
        base = _strip_show_extension(base).strip(" .") or "default"
        base += SHOW_EXTENSION
    elif not base.lower().endswith(ALL_SHOW_EXTENSIONS):
        base += SHOW_EXTENSION
    return base

def _show_file_path(name=None):
    return os.path.join(shows_dir, _safe_show_filename(name or current_show))

def _lumishow_name_from(name):
    return _safe_show_filename(name, prefer_lumishow=True)

def _show_title_from_filename(name):
    return _strip_show_extension(_safe_show_filename(name or current_show)).strip() or "default"

def _update_window_title():
    try:
        root.title(f"LumiControLL - {_show_title_from_filename(current_show)}")
    except Exception:
        pass

def _ask_show_filename(title, initialvalue=""):
    while True:
        raw = _ask_text(title, "Show title:", initialvalue=initialvalue, parent=root)
        if raw is None:
            return None
        raw = raw.strip()
        if not raw:
            messagebox.showwarning(title, "Enter a show title.", parent=root)
            continue
        dest_name = _lumishow_name_from(raw)
        clean_title = _show_title_from_filename(dest_name)
        if raw != clean_title:
            messagebox.showwarning(
                title,
                "Use only letters, numbers, spaces, dots, dashes and underscores.",
                parent=root,
            )
            continue
        return dest_name

def _migrate_current_show_name():
    global current_show
    old_name = _safe_show_filename(current_show)
    new_name = _lumishow_name_from(old_name)
    if old_name == new_name:
        current_show = new_name
        return

    old_path = os.path.join(shows_dir, old_name)
    new_path = os.path.join(shows_dir, new_name)
    if not os.path.exists(new_path) and os.path.exists(old_path):
        try:
            shutil.copy2(old_path, new_path)
        except Exception:
            pass
    current_show = new_name

def _empty_show_data():
    return {"pages": _new_show_pages(), "blocks": _new_block_slots(8)}

def _ensure_shows_dir():
    os.makedirs(shows_dir, exist_ok=True)

def _write_scenes_file(pages_inline, slots_inline):
    _ensure_shows_dir()
    while len(slots_inline) < 8:
        slots_inline.append({"page": None})
    with open(_show_file_path(), "w", encoding="utf-8") as f:
        json.dump({"pages": pages_inline, "blocks": slots_inline}, f, indent=4)

def _load_scenes():
    global current_show
    _ensure_shows_dir()
    _migrate_current_show_name()
    scenes_file = _show_file_path()

    if not os.path.exists(scenes_file):
        legacy_candidates = [
            os.path.join(shows_dir, _safe_show_filename("default.show.json")),
            legacy_scenes_file,
        ]
        for legacy_path in legacy_candidates:
            if os.path.exists(legacy_path):
                try:
                    shutil.copy2(legacy_path, scenes_file)
                    break
                except Exception:
                    pass

    if not os.path.exists(scenes_file):
        pages_inline = _new_show_pages()
        slots_inline = _new_block_slots(8)
        _write_scenes_file(pages_inline, slots_inline)
    else:
        try:
            with open(scenes_file, "r", encoding="utf-8") as f:
                pages_inline, slots_inline = _normalise_show(json.load(f))
        except Exception:
            backup = f"{scenes_file}.broken-{time.strftime('%Y%m%d-%H%M%S')}"
            try:
                shutil.copy2(scenes_file, backup)
            except Exception:
                pass
            pages_inline = _new_show_pages()
            slots_inline = _new_block_slots(8)
            _write_scenes_file(pages_inline, slots_inline)
    save_settings()
    return pages_inline, slots_inline

pages, block_slots = _load_scenes()
_ensure_block_slots()
blocks = _visible_blocks()

def _rebuild_flat_from_inline():
    global blocks, scenes, scene_to_block, scene_to_local
    blocks = _visible_blocks()
    scenes, scene_to_block, scene_to_local = [], [], []
    for bi, blk in enumerate(blocks):
        if blk.get("_none"):
            continue
        for ci, ch in enumerate(blk["chases"]):
            norm = _normalise_chase(ch, ci)
            blk["chases"][ci] = norm
            scenes.append(norm)
            scene_to_block.append(bi)
            scene_to_local.append(ci)

def save_scenes():
    _write_scenes_file(pages, block_slots)

_rebuild_flat_from_inline()

# ----------------- Output bussen -----------------
# Art-Net
def _make_artnet():
    return StupidArtnet(node_ip, universe, 512)

_artnet = _make_artnet()

def _update_artnet():
    global _artnet
    _artnet = _make_artnet()

def _send_artnet_live(frame):
    if not ARTNET_AVAILABLE:
        return
    f = _pad512(list(frame))
    _artnet.set(f)
    _artnet.show()

# USB (uDMX) met backoff + echte stats
class USBOut:
    def __init__(self):
        self.dev = None               # type: UDMX|None
        self.last_frame = None        # type: bytes|None
        self._reconnect_job = None
        self._status_cb = None
        self._root = None
        self._last_send_ms = 0        # rate-limit
        self._open_blocked_until = 0  # backoff ms
        self._lock = threading.RLock()
        self._send_event = threading.Event()
        self._pending_frame = None    # type: bytes|None

        # Stats window (rolling)
        self._stat_win_ms = 1500
        self._stat_bytes = 0
        self._stat_frames = 0
        self._stat_reset_ms = _now_ms()
        self._worker = threading.Thread(target=self._send_worker, daemon=True)
        self._worker.start()

    # ---- stats helpers ----
    def _accumulate_stats(self, bytes_sent, frames=1):
        self._stat_bytes += int(bytes_sent)
        self._stat_frames += int(frames)
        now = _now_ms()
        if now - self._stat_reset_ms > self._stat_win_ms:
            # decay in plaats van hard reset (smooth)
            decay = 0.5
            self._stat_bytes = int(self._stat_bytes * decay)
            self._stat_frames = max(1, int(self._stat_frames * decay))
            self._stat_reset_ms = now

    def stats(self):
        # Gemeten bps & fps over rolling window
        dur = max(1, _now_ms() - self._stat_reset_ms)
        bps = int((self._stat_bytes * 1000) / dur)
        fps = float((self._stat_frames * 1000) / dur)
        return bps, fps

    def set_status_cb(self, cb):
        self._status_cb = cb

    def status_text(self):
        with self._lock:
            return "USB: connected" if self.dev else "USB: not connected"

    def ensure_open(self, root=None, verbose=False, force=False):
        if root is not None:
            self._root = root
        now = _now_ms()
        with self._lock:
            if self.dev:
                return True
        if (not force) and (now < self._open_blocked_until):
            return False
        try:
            d = UDMX().open()
            with self._lock:
                self.dev = d
                self.last_frame = None
                self._open_blocked_until = 0
            if verbose: print("[usb] opened")
            if self._status_cb: self._status_cb()
            return True
        except Exception as e:
            if verbose: print(f"[usb] open failed: {e}")
            with self._lock:
                self.dev = None
                self.last_frame = None
            # backoff
            self._open_blocked_until = now + USB_RETRY_MS
            if self._status_cb: self._status_cb()
            # één geplande retry voor UI-feedback
            if self._root is not None and self._reconnect_job is None:
                self._reconnect_job = self._root.after(USB_RETRY_MS, self._retry_open)
            return False

    def _retry_open(self):
        self._reconnect_job = None
        self.ensure_open(root=self._root, verbose=False, force=True)

    def close(self):
        if self._reconnect_job and self._root:
            try: self._root.after_cancel(self._reconnect_job)
            except Exception: pass
        self._reconnect_job = None
        try:
            with self._lock:
                dev = self.dev
                self.dev = None
                self.last_frame = None
                self._pending_frame = None
            if dev:
                dev.close()
        except Exception:
            pass
        if self._status_cb: self._status_cb()

    def send_if_changed(self, frame512: bytes):
        now = _now_ms()
        if now - self._last_send_ms < USB_SEND_MIN_INTERVAL_MS:
            return
        with self._lock:
            if not self.dev:
                return
            if (not USB_ALWAYS_SEND) and (self.last_frame == frame512):
                return
            self._pending_frame = frame512
            self._last_send_ms = now
        self._send_event.set()

    def _send_worker(self):
        while True:
            self._send_event.wait()
            while True:
                with self._lock:
                    frame512 = self._pending_frame
                    self._pending_frame = None
                    dev = self.dev
                if frame512 is None:
                    with self._lock:
                        if self._pending_frame is None:
                            self._send_event.clear()
                            break
                    continue
                if not dev:
                    continue
                try:
                    dev.send_universe(frame512,
                                      chunk_size=int(USB_CHUNK_SIZE),
                                      inter_delay=float(USB_INTER_DELAY_MS),
                                      force=bool(USB_ALWAYS_SEND))
                    with self._lock:
                        self.last_frame = frame512
                    self._accumulate_stats(512, 1)
                except Exception as e:
                    print(f"[usb] send error: {e}")
                    try:
                        dev.close()
                    except Exception:
                        pass
                    with self._lock:
                        if self.dev is dev:
                            self.dev = None
                        self.last_frame = None
                        self._pending_frame = None
                        self._open_blocked_until = _now_ms() + USB_RETRY_MS
                    if self._status_cb: self._status_cb()
                    self._send_event.clear()
                    break

    def blackout(self):
        with self._lock:
            dev = self.dev
            self._pending_frame = None
        if dev:
            try: dev.blackout()
            except Exception: pass
        with self._lock:
            self.last_frame = None

_usb = USBOut()

# ----------------- DMX mix & output -----------------
def htp_mix(frames, dmx_len):
    out = [0]*dmx_len
    for frame in frames:
        for i, v in enumerate(frame[:dmx_len]):
            if v > out[i]: out[i] = v
    return out

def _pad512(frame):
    if len(frame) >= 512:
        return bytes(frame[:512])
    return bytes(frame + [0]*(512-len(frame)))

def send_dmx(frame):
    # ARTNET
    if output_mode in ("artnet", "both"):
        _send_artnet_live(frame)

    # USB
    if output_mode in ("usb", "both"):
        frame512 = _pad512(list(frame))
        _usb.send_if_changed(frame512)

# ----------------- State voor scenes -----------------
editor_preview_on = False
editor_preview_frame = None
chase_state = {}
active_by_block = [set() for _ in range(len(blocks))]

def set_editor_preview_frame(frame):
    global editor_preview_frame
    if frame is None:
        editor_preview_frame = None
    else:
        tmp = list(frame) + [0]*dmx_channels
        editor_preview_frame = tmp[:dmx_channels]

def clear_editor_preview_frame():
    set_editor_preview_frame(None)

def _start_chase_if_needed(sidx, t_ms):
    if sidx not in chase_state:
        chase_state[sidx] = {"step": 0, "start_ms": t_ms, "started_ms": t_ms}

def _stop_chase(sidx):
    chase_state.pop(sidx, None)

def _get_period_ms(ch, step_idx, t_ms):
    if ch.get("timing_mode", "duration") == "bpm":
        per = int(60000 / max(1, bpm))
        return max(1, per)
    else:
        steps = ch.get("steps") or []
        if not steps: return 500
        try:
            return max(1, int(steps[step_idx % len(steps)].get("duration_ms", 500)))
        except Exception:
            return 500

def _advance_step_manual(sidx, t_ms):
    if not (0 <= sidx < len(scenes)): return
    ch = scenes[sidx]; steps = ch.get("steps") or []
    if not steps: return
    _start_chase_if_needed(sidx, t_ms)
    st = chase_state[sidx]
    st["step"] = (st["step"] + 1) % len(steps)
    st["start_ms"] = t_ms

def _advance_and_get_frame(sidx, t_ms):
    if not (0 <= sidx < len(scenes)): return [0]*dmx_channels
    ch = scenes[sidx]; steps = ch.get("steps") or []
    if not steps: return ch.get("values", [0]*dmx_channels)[:dmx_channels]
    _start_chase_if_needed(sidx, t_ms)
    st = chase_state[sidx]
    step_idx = st["step"]
    mode = ch.get("timing_mode", "duration")
    if mode == "duration" and not bool(ch.get("repeat", True)):
        durations = [max(1, int(step.get("duration_ms", 500))) for step in steps]
        elapsed_total = max(0, t_ms - st.get("started_ms", st.get("start_ms", t_ms)))
        total = sum(durations)
        if elapsed_total >= total:
            return None
        acc = 0
        for idx, dur in enumerate(durations):
            if elapsed_total < acc + dur:
                st["step"] = idx
                st["start_ms"] = t_ms - (elapsed_total - acc)
                step_idx = idx
                break
            acc += dur
    if mode != "sound":
        period = _get_period_ms(ch, step_idx, t_ms)
        elapsed = t_ms - st["start_ms"]
        if elapsed >= period:
            if period <= 0: period = 1
            steps_ahead = elapsed // period
            if mode == "duration" and not bool(ch.get("repeat", True)):
                step_idx = min(len(steps) - 1, step_idx + steps_ahead)
            else:
                step_idx = (step_idx + steps_ahead) % len(steps)
            st["step"] = step_idx
            st["start_ms"] = t_ms - (elapsed % period)
    if mode == "duration" and bool(ch.get("fade", False)):
        period = max(1, _get_period_ms(ch, st["step"], t_ms))
        elapsed = max(0, t_ms - st["start_ms"])
        a = steps[st["step"]]["values"]
        if not bool(ch.get("repeat", True)) and st["step"] >= len(steps) - 1:
            b = a
        else:
            b = steps[(st["step"] + 1) % len(steps)]["values"]
        t = max(0.0, min(1.0, elapsed / float(period)))
        out = [0]*dmx_channels
        for i in range(dmx_channels):
            ai = a[i]; bi = b[i]
            out[i] = int(round(ai + (bi - ai) * t))
        return out
    else:
        return steps[st["step"]]["values"][:dmx_channels]

def render_and_send():
    t = _now_ms()
    frames = []
    stopped_any = False
    for bi, aset in enumerate(active_by_block):
        for sidx in list(aset):
            frame = _advance_and_get_frame(sidx, t)
            if frame is None:
                aset.discard(sidx)
                _stop_chase(sidx)
                stopped_any = True
            else:
                frames.append(frame)
    if editor_preview_on and (editor_preview_frame is not None):
        frames.append(editor_preview_frame)
    out = [0]*dmx_channels if not frames else htp_mix(frames, dmx_channels)
    send_dmx(out)
    if stopped_any:
        update_button_highlight()

# -------- SOUND pulse handling ----------
pending_events = []
_sound_color_toggle = {"state": False}  # False=green, True=red
detector = None
mic_status = {"available": False, "message": "", "last_health_check": 0.0}

def _set_sound_label_available(available, message=""):
    mic_status["available"] = bool(available)
    mic_status["message"] = str(message or "")
    try:
        if available:
            sound_label.config(text="SOUND", fg="green")
        else:
            sound_label.config(text="NO MIC", fg="red")
    except Exception:
        pass

def _device_label(dev):
    suffix = "" if dev.get("usable", True) else " (unavailable)"
    prefix = "PC Audio" if dev.get("source_type") == "loopback" else "Input"
    if dev.get("source_type") == "loopback":
        return f"{prefix}: {dev.get('name')}{suffix}"
    return f"{prefix} {dev.get('index')}: {dev.get('name')}{suffix}"

def _is_human_input_device(dev):
    name = str(dev.get("name", "")).strip().lower()
    blocked = (
        "microsoft-geluidstoewijzing",
        "microsoft sound mapper",
        "primair stuurprogramma",
        "primary sound",
        "what u hear",
        "wave mapper",
    )
    if any(term in name for term in blocked):
        return False
    return True

def _sort_input_devices(devices):
    def score(dev):
        name = str(dev.get("name", "")).lower()
        is_loopback = dev.get("source_type") == "loopback"
        preferred = any(term in name for term in ("usb", "microfoon", "microphone", "mic"))
        usable = bool(dev.get("usable", True))
        return (0 if preferred else 1, 1 if is_loopback else 0, 0 if usable else 1, str(dev.get("name", "")).lower())
    return sorted(devices, key=score)

def _device_base_name(dev):
    name = str(dev.get("name", "")).strip()
    name = re.sub(r"\s*\(\d+-\s*", "(", name)
    name = re.sub(r"\s+", " ", name)
    return name

def _dedupe_input_devices(devices):
    def sort_index(dev):
        try:
            return int(dev.get("index", 9999))
        except Exception:
            return 9999
    best = {}
    for dev in devices:
        key = f"{dev.get('source_type', 'input')}:{_device_base_name(dev).lower()}"
        current = best.get(key)
        if current is None:
            best[key] = dev
            continue
        cur_score = (0 if current.get("usable", True) else 1, sort_index(current))
        new_score = (0 if dev.get("usable", True) else 1, sort_index(dev))
        if new_score < cur_score:
            best[key] = dev
    return list(best.values())

def _device_index_from_label(label):
    try:
        left = str(label).split(":", 1)[0].strip()
        return int(left.split()[-1])
    except Exception:
        return None

def _device_source_from_label(label):
    return "loopback" if str(label).startswith("PC Audio ") else "input"

def _valid_input_index(index, devices):
    try:
        index = int(index)
    except Exception:
        return None
    for dev in devices:
        if int(dev.get("index", -9999)) == index:
            return index
    return None

def _valid_device(index, source_type, devices):
    source_type = str(source_type or "input")
    if source_type == "input":
        try:
            index_cmp = int(index)
        except Exception:
            return None
    else:
        index_cmp = str(index)
    for dev in devices:
        if str(dev.get("source_type", "input")) != source_type:
            continue
        if source_type == "input":
            try:
                if int(dev.get("index", -9999)) == index_cmp:
                    return index_cmp
            except Exception:
                pass
        elif str(dev.get("index", "")) == index_cmp:
            return index_cmp
    return None

def _input_index_by_name(name, devices, source_type="input"):
    wanted = str(name or "").strip().lower()
    if not wanted:
        return None
    source_type = str(source_type or "input")
    for dev in devices:
        if str(dev.get("source_type", "input")) == source_type and str(dev.get("name", "")).strip().lower() == wanted:
            if source_type == "loopback":
                return str(dev.get("index", ""))
            try:
                return int(dev.get("index", 0))
            except Exception:
                return None
    return None

def _start_audio_detector(silent=True, device_index=None, source_type=None):
    global detector
    if detector:
        try:
            detector.stop()
        except Exception:
            pass
        detector = None
    if not is_audio_available():
        _set_sound_label_available(False, "Audio support is not available.")
        return False
    devices = list_input_devices(refresh=device_index is not None, usable_only=False)
    devices += list_loopback_devices(refresh=False, usable_only=False)
    if not devices:
        _set_sound_label_available(False, "No microphone/input device found.")
        return False
    init_sound_settings = load_sound_settings()
    candidates = []
    saved_device = init_sound_settings.get("input_device")
    saved_name = init_sound_settings.get("input_device_name")
    saved_source = init_sound_settings.get("source_type", "input")
    source_type = source_type or saved_source or "input"
    if device_index is not None:
        valid = _valid_device(device_index, source_type, devices)
        if valid is None:
            _set_sound_label_available(False, "Selected audio source not found.")
            return False
        candidates.append(valid)
    else:
        valid = _valid_device(saved_device, saved_source, devices)
        if valid is not None:
            candidates.append(valid)
        else:
            name_match = _input_index_by_name(saved_name, devices, saved_source)
            if name_match is not None:
                candidates.append(name_match)
        if not candidates and (saved_device is not None or saved_name):
            _set_sound_label_available(False, "Selected microphone not found.")
            return False
        if not candidates:
            _set_sound_label_available(False, "No microphone selected.")
            return False
    def _on_pulse():
        try: pending_events.append(("sound_pulse", time.monotonic()))
        except Exception: pass
    last_error = ""
    for chosen in candidates:
        init_sound_settings["input_device"] = chosen
        init_sound_settings["source_type"] = source_type if device_index is not None else saved_source
        for dev in devices:
            try:
                if int(dev.get("index", -9999)) == int(chosen) and str(dev.get("source_type", "input")) == init_sound_settings["source_type"]:
                    init_sound_settings["input_device_name"] = str(dev.get("name", ""))
                    break
            except Exception:
                pass
        try:
            detector = AudioPulseDetector(init_sound_settings, on_pulse=lambda: root.after(0, _on_pulse))
            detector.start()
            save_sound_settings(init_sound_settings)
            _set_sound_label_available(True)
            return True
        except Exception as e:
            last_error = str(e)
            try:
                if detector: detector.stop()
            except Exception:
                pass
            detector = None
    _set_sound_label_available(False, last_error or "No usable microphone/input device found.")
    return False

def _check_audio_detector_health():
    global detector
    now = time.monotonic()
    if (now - float(mic_status.get("last_health_check", 0.0) or 0.0)) < 1.0:
        return
    mic_status["last_health_check"] = now
    if not mic_status.get("available", False) or detector is None:
        return
    try:
        healthy = detector.is_healthy()
        message = detector.status_message()
    except Exception as e:
        healthy = False
        message = str(e)
    if healthy:
        return
    try:
        detector.stop()
    except Exception:
        pass
    detector = None
    _set_sound_label_available(False, message or "Microphone disconnected.")

def _open_input_select_dialog(no_mic=False, parent=None):
    parent = parent or root
    win = tk.Toplevel(root)
    win.title("Microphone" if no_mic else "Select input")
    _set_window_icon(win)
    win.resizable(False, False)
    win.transient(parent); win.grab_set()
    frm = tk.Frame(win, padx=18, pady=16)
    frm.pack(fill="both", expand=True)
    msg = mic_status.get("message") or "No microphone/input device found."
    if no_mic:
        tk.Label(frm, text="NO MIC", font=("TkDefaultFont", 12, "bold"), fg="red").pack(pady=(0, 8))
    status_text = msg if no_mic else "Select an input device."
    status = tk.Label(frm, text=status_text, wraplength=340, justify="center")
    status.pack(fill="x", pady=(0, 12))
    device_var = tk.StringVar(value="")
    combo = ttk.Combobox(frm, textvariable=device_var, state="readonly", width=46)
    combo.pack(fill="x", pady=(0, 12))
    visible_devices = {"items": []}

    def refresh_devices(preferred_label=None):
        all_devices = list_input_devices(refresh=True, usable_only=False)
        all_devices += list_loopback_devices(refresh=False, usable_only=False)
        devices = [dev for dev in all_devices if _is_human_input_device(dev) and dev.get("usable", True)]
        if not devices:
            devices = [dev for dev in all_devices if _is_human_input_device(dev)]
        if not devices:
            devices = [dev for dev in all_devices if dev.get("usable", True)]
        devices = _sort_input_devices(_dedupe_input_devices(devices))
        visible_devices["items"] = devices
        labels = [_device_label(dev) for dev in devices]
        combo.config(values=labels)
        sound_settings = load_sound_settings()
        saved = sound_settings.get("input_device")
        saved_name = sound_settings.get("input_device_name")
        saved_source = sound_settings.get("source_type", "input")
        selected = None
        if preferred_label in labels:
            selected = preferred_label
        for dev, label in zip(devices, labels):
            if selected is None and _valid_device(saved, saved_source, [dev]) is not None:
                selected = label
                break
            if selected is None and _input_index_by_name(saved_name, [dev], saved_source) is not None:
                selected = label
                break
        if selected is None and labels:
            selected = labels[0]
        device_var.set(selected or "")
        if labels:
            status.config(text=(mic_status.get("message") if no_mic else "") or "Select an input device.")
        else:
            status.config(text="No microphone/input device found.")
        return devices

    refresh_devices()

    def select_mic():
        devices = visible_devices.get("items", [])
        label = device_var.get()
        selected_dev = None
        for dev in devices:
            if _device_label(dev) == label:
                selected_dev = dev
                break
        if selected_dev is None and devices:
            selected_dev = devices[0]
        selected = selected_dev.get("index") if selected_dev else None
        selected_source = str(selected_dev.get("source_type", "input")) if selected_dev else "input"
        selected_name = str(selected_dev.get("name", "")) if selected_dev else ""
        if selected is not None:
            settings_now = load_sound_settings()
            settings_now["input_device"] = selected
            settings_now["input_device_name"] = selected_name
            settings_now["source_type"] = selected_source
            save_sound_settings(settings_now)
        ok = _start_audio_detector(silent=True, device_index=selected, source_type=selected_source)
        if ok:
            try: win.grab_release()
            except Exception: pass
            win.destroy()
        else:
            status.config(text=mic_status.get("message") or "Still no microphone/input device found.")

    row = tk.Frame(frm); row.pack(fill="x")
    tk.Button(row, text="Close", width=10, command=lambda: (win.grab_release(), win.destroy())).pack(side="right")
    tk.Button(row, text="Select Input", width=12, command=select_mic).pack(side="right", padx=(0, 6))
    win.update_idletasks()
    try:
        px, py = root.winfo_rootx(), root.winfo_rooty()
        pw, ph = root.winfo_width(), root.winfo_height()
        ww, wh = win.winfo_width(), win.winfo_height()
        x = px + (pw - ww) // 2
        y = py + (ph - wh) // 2
        win.geometry(f"+{max(0, x)}+{max(0, y)}")
    except Exception:
        pass
    win.bind("<Escape>", lambda e: (win.grab_release(), win.destroy()))

def _open_no_mic_dialog():
    _open_input_select_dialog(no_mic=True, parent=root)

def _handle_pending_events():
    changed = False
    while pending_events:
        typ, ts = pending_events.pop(0)
        if typ == "sound_pulse":
            if not mic_status.get("available", False):
                continue
            _sound_color_toggle["state"] = not _sound_color_toggle["state"]
            changed = True
            now = _now_ms()
            for bi, aset in enumerate(active_by_block):
                for sidx in list(aset):
                    ch = scenes[sidx]
                    if ch.get("timing_mode", "duration") == "sound":
                        _advance_step_manual(sidx, now)
    if changed:
        try:
            sound_label.config(fg=("red" if _sound_color_toggle["state"] else "green"))
        except Exception:
            pass

# ---------- Admin & menus ----------
def _ask_universe_with_focus(parent, initial_value):
    win = tk.Toplevel(parent)
    win.title("Universe")
    _set_window_icon(win)
    win.resizable(False, False)
    win.transient(parent); win.grab_set()

    frm = tk.Frame(win, padx=16, pady=16); frm.pack(fill="both", expand=True)
    tk.Label(frm, text="Enter Universe:", anchor="center", justify="center").pack(pady=(0, 8))
    var = tk.StringVar(value=str(initial_value))
    ent = tk.Entry(frm, textvariable=var, width=10, justify="center"); ent.pack(pady=(0, 8))
    ok = tk.Button(frm, text="OK", width=10); ok.pack(pady=(6, 0))

    result = {"val": None}
    def _close_ok(*_):
        s = var.get().strip()
        if s.isdigit():
            result["val"] = int(s)
            try: win.grab_release()
            except Exception: pass
            win.destroy()
        else:
            messagebox.showwarning("Universe", "Please enter a valid integer.", parent=win)
            try: ent.focus_set(); ent.selection_range(0, "end")
            except Exception: pass

    ok.config(command=_close_ok)
    win.bind("<Return>", _close_ok)

    parent.update_idletasks()
    try:
        px,py = parent.winfo_rootx(), parent.winfo_rooty()
        pw,ph = parent.winfo_width(), parent.winfo_height()
        ww,wh = 240, 140
        x = px + (pw - ww)//2; y = py + (ph - wh)//2
        win.geometry(f"{ww}x{wh}+{max(0,x)}+{max(0,y)}")
    except Exception: pass

    win.after(10, lambda: (ent.focus_set(), ent.selection_range(0, "end")))
    win.wait_window()
    return result["val"]

def open_artnet_node_settings():
    global node_ip, universe
    new_ip = _ask_text("Node IP", "Enter Art-Net node IP:", initialvalue=node_ip, parent=root)
    if new_ip is not None and new_ip.strip():
        node_ip = new_ip.strip()
    new_uni = _ask_universe_with_focus(root, universe)
    if new_uni is not None:
        universe = int(new_uni)
    _update_artnet()
    save_settings()

def toggle_admin_mode():
    global adm_permission
    adm_permission = "1" if adm_permission == "0" else "0"
    try:
        with open(adm_file, 'w', encoding='utf-8') as _f: _f.write(adm_permission)
    except Exception: pass
    update_gui(); update_menubar()

def open_readme():
    if os.path.exists(readme_file):
        try:
            if sys.platform.startswith("win"): os.startfile(readme_file)  # type: ignore[attr-defined]
            elif sys.platform == "darwin": os.system(f'open "{readme_file}"')
            else: os.system(f'xdg-open "{readme_file}"')
        except Exception:
            messagebox.showinfo("Help", f"Open this file manually:\n{readme_file}")
    else:
        messagebox.showwarning("Help", "readme.pdf not found in the app folder.")

def open_path(path, title="Open folder"):
    if os.path.exists(path):
        try:
            if sys.platform.startswith("win"): os.startfile(path)  # type: ignore[attr-defined]
            elif sys.platform == "darwin": subprocess.Popen(["open", path])
            else: subprocess.Popen(["xdg-open", path])
        except Exception:
            messagebox.showinfo(title, f"Open this path manually:\n{path}")
    else:
        messagebox.showwarning(title, f"Not found:\n{path}")

def open_url(url: str):
    import webbrowser
    try: webbrowser.open_new(url)
    except Exception:
        messagebox.showinfo("Open URL", f"Open this link manually:\n{url}")

def open_artnet_viewer():
    try:
        if os.path.exists(viewer_exe):
            subprocess.Popen([viewer_exe], cwd=script_directory)
        elif os.path.exists(viewer_py):
            subprocess.Popen([sys.executable, viewer_py], cwd=script_directory)
        else:
            messagebox.showwarning("Art-Net Viewer", "viewer.exe or viewer.py not found.", parent=root)
    except Exception as e:
        messagebox.showerror("Art-Net Viewer", f"Could not open Art-Net Viewer:\n{e}", parent=root)

def _show_filetypes():
    return [("LumiControLL shows", "*.lumishow"), ("Legacy show files", "*.show.json *.json *.config"), ("All files", "*.*")]

def _load_show_file(show_name):
    global current_show, pages, block_slots
    current_show = _lumishow_name_from(show_name)
    pages, block_slots = _load_scenes()
    _ensure_block_slots()
    for aset in active_by_block:
        for sidx in list(aset):
            _stop_chase(sidx)
        aset.clear()
    _rebuild_flat_from_inline()
    save_settings()
    _update_window_title()
    update_gui()

def select_show():
    _ensure_shows_dir()
    path = filedialog.askopenfilename(
        parent=root,
        title="Select show",
        initialdir=shows_dir,
        filetypes=_show_filetypes(),
    )
    if not path:
        return
    show_dir_abs = os.path.abspath(shows_dir)
    path_abs = os.path.abspath(path)
    if os.path.dirname(path_abs).lower() != show_dir_abs.lower():
        messagebox.showwarning("Select show", "Use Import Show for shows outside the show folder.", parent=root)
        return
    try:
        with open(path_abs, "r", encoding="utf-8") as f:
            _normalise_show(json.load(f))
    except Exception as e:
        messagebox.showerror("Select show", f"Could not open show:\n{e}", parent=root)
        return
    _load_show_file(os.path.basename(path_abs))

def new_show():
    global current_show, pages, block_slots
    dest_name = _ask_show_filename("New show", "New show")
    if dest_name is None:
        return
    dest = _show_file_path(dest_name)
    if os.path.exists(dest) and not messagebox.askyesno("New show", f"Replace existing show '{dest_name}'?", parent=root):
        return
    current_show = dest_name
    pages, block_slots = _new_show_pages(), _new_block_slots(8)
    save_scenes()
    _load_show_file(dest_name)

def rename_show():
    global current_show
    _ensure_shows_dir()
    old_name = _lumishow_name_from(current_show)
    old_path = _show_file_path(old_name)
    new_name = _ask_show_filename("Rename show", _show_title_from_filename(old_name))
    if new_name is None or new_name == old_name:
        return
    new_path = _show_file_path(new_name)
    if os.path.exists(new_path):
        messagebox.showwarning("Rename show", f"A show named '{new_name}' already exists.", parent=root)
        return
    try:
        if not os.path.exists(old_path):
            save_scenes()
        os.replace(old_path, new_path)
        current_show = new_name
        save_settings()
        _update_window_title()
    except Exception as e:
        messagebox.showerror("Rename show", f"Could not rename show:\n{e}", parent=root)

def import_show():
    global current_show, pages, block_slots
    path = filedialog.askopenfilename(
        parent=root,
        title="Import show",
        filetypes=_show_filetypes(),
    )
    if not path:
        return
    try:
        with open(path, "r", encoding="utf-8") as f:
            imported_pages, imported_slots = _normalise_show(json.load(f))
    except Exception as e:
        messagebox.showerror("Import show", f"Could not import show:\n{e}", parent=root)
        return
    _ensure_shows_dir()
    dest_name = _lumishow_name_from(os.path.basename(path))
    dest = _show_file_path(dest_name)
    src_abs = os.path.abspath(path)
    dest_abs = os.path.abspath(dest)
    if os.path.exists(dest) and not messagebox.askyesno("Import show", f"Replace existing show '{dest_name}'?", parent=root):
        return
    try:
        if src_abs.lower() == dest_abs.lower():
            with open(dest_abs, "w", encoding="utf-8") as f:
                json.dump({"pages": imported_pages, "blocks": imported_slots}, f, indent=4)
        elif path.lower().endswith(SHOW_EXTENSION):
            shutil.copy2(src_abs, dest_abs)
        else:
            with open(dest_abs, "w", encoding="utf-8") as f:
                json.dump({"pages": imported_pages, "blocks": imported_slots}, f, indent=4)
    except Exception as e:
        messagebox.showerror("Import show", f"Could not copy show to the show folder:\n{e}", parent=root)
        return
    _load_show_file(dest_name)

def export_show():
    _ensure_shows_dir()
    src = _show_file_path()
    if not os.path.exists(src):
        save_scenes()
    path = filedialog.asksaveasfilename(
        parent=root,
        title="Export show",
        initialfile=_lumishow_name_from(current_show),
        defaultextension=SHOW_EXTENSION,
        filetypes=[("LumiControLL shows", "*.lumishow"), ("Legacy JSON files", "*.json"), ("All files", "*.*")],
    )
    if not path:
        return
    try:
        shutil.copy2(src, path)
    except Exception as e:
        messagebox.showerror("Export show", f"Could not export show:\n{e}", parent=root)

def delete_current_show():
    global current_show, pages, block_slots
    _ensure_shows_dir()
    show_name = _safe_show_filename(current_show)
    if not messagebox.askyesno("Delete show", f"Delete current show '{show_name}'?", parent=root):
        return
    try:
        show_stem = _strip_show_extension(show_name).lower()
        for filename in list(os.listdir(shows_dir)):
            if not filename.lower().endswith(ALL_SHOW_EXTENSIONS):
                continue
            if _strip_show_extension(filename).lower() != show_stem:
                continue
            path = os.path.join(shows_dir, filename)
            if os.path.isfile(path):
                os.remove(path)
    except Exception as e:
        messagebox.showerror("Delete show", f"Could not delete show:\n{e}", parent=root)
        return
    remaining = [
        f for f in os.listdir(shows_dir)
        if os.path.isfile(os.path.join(shows_dir, f)) and f.lower().endswith(ALL_SHOW_EXTENSIONS)
    ]
    remaining.sort(key=lambda f: (0 if f.lower().endswith(SHOW_EXTENSION) else 1, f.lower()))
    if remaining:
        _load_show_file(remaining[0])
    else:
        current_show = "default.lumishow"
        pages, block_slots = _new_show_pages(), _new_block_slots(8)
        save_scenes()
        _load_show_file(current_show)

def _block_view_var():
    global block_view_var
    try:
        block_view_var.set(str(block_view))
        return block_view_var
    except Exception:
        block_view_var = tk.StringVar(value=str(block_view))
        return block_view_var

def show_about():
    win = tk.Toplevel(root)
    win.title("About LumiControLL")
    _set_window_icon(win)
    win.resizable(False, False)
    win.transient(root); win.grab_set()
    wrap = tk.Frame(win, padx=16, pady=16); wrap.pack(fill="both", expand=True)
    tk.Label(wrap, text="LumiControLL", font=("Arial", 14, "bold")).pack(pady=(0, 6))
    tk.Label(wrap, text="By L.C.L. Lemmens", font=("Arial", 10)).pack(pady=(0, 10))
    tk.Label(wrap, text="Thanks to StupidArtnet:", font=("Arial", 10)).pack()
    link1 = tk.Label(wrap, text="https://github.com/cpvalente/stupidArtnet",
                     font=("Arial", 10, "underline"), fg="blue", cursor="hand2")
    link1.pack()
    link1.bind("<Button-1>", lambda e: open_url("https://github.com/cpvalente/stupidArtnet"))
    tk.Label(wrap, text="Icon by:", font=("Arial", 10)).pack(pady=(10, 0))
    link2 = tk.Label(wrap, text="Vecteezy", font=("Arial", 10, "underline"),
                     fg="blue", cursor="hand2")
    link2.pack()
    link2.bind("<Button-1>", lambda e: open_url("https://www.vecteezy.com/free-vector/slider-icon"))
    tk.Label(wrap,
             text="Art-Net™ Designed by and Copyright Artistic Licence Engineering Ltd",
             font=("Arial", 10), wraplength=420, justify="center").pack(pady=(10, 0))
    tk.Button(
        wrap,
        text="Third-party licenses",
        command=lambda: open_path(third_party_licenses_dir, "Third-party licenses"),
    ).pack(pady=(10, 0))
    btn = tk.Button(wrap, text="Close", width=12,
                    command=lambda: (win.grab_release(), win.destroy()))
    btn.pack(pady=(6, 0))
    root.update_idletasks()
    try:
        px,py = root.winfo_rootx(), root.winfo_rooty()
        pw,ph = root.winfo_width(), root.winfo_height()
        ww,wh = 460, 300
        x = px + (pw - ww)//2; y = py + (ph - wh)//2
        win.geometry(f"{ww}x{wh}+{max(0,x)}+{max(0,y)}")
    except Exception: pass
    win.bind("<Return>", lambda e: (win.grab_release(), win.destroy()))
    win.after(10, btn.focus_set)

def _apply_output_mode(new_mode: str):
    """Direct toepassen bij radiobutton click."""
    global output_mode
    if new_mode == output_mode:
        return
    output_mode = new_mode
    if output_mode in ("usb", "both"):
        _usb.ensure_open(root=root, verbose=False, force=True)
    else:
        _usb.close()
    save_settings()

def update_menubar():
    global menubar, filemenu
    menubar.delete(0, "end")
    if adm_permission == "1":
        filemenu = tk.Menu(menubar, tearoff=0)
        filemenu.add_command(label="Select Show", command=select_show)
        filemenu.add_command(label="New Show", command=new_show)
        filemenu.add_command(label="Rename Show", command=rename_show)
        filemenu.add_separator()
        filemenu.add_command(label="Import Show", command=import_show)
        filemenu.add_command(label="Export Show", command=export_show)
        filemenu.add_command(label="Delete Show", command=delete_current_show)
        filemenu.add_separator()
        filemenu.add_command(label="Art-Net Settings", command=open_artnet_node_settings)
        filemenu.add_command(label="Output Settings", command=open_output_settings)
        # Performance niet meer in menu; hotkey-only
        menubar.add_cascade(label="File", menu=filemenu)
        viewmenu = tk.Menu(menubar, tearoff=0)
        viewmenu.add_radiobutton(label="1 block", value="1", variable=_block_view_var(), command=lambda: set_block_view("1"))
        viewmenu.add_radiobutton(label="2 blocks", value="2", variable=_block_view_var(), command=lambda: set_block_view("2"))
        viewmenu.add_radiobutton(label="3 blocks", value="3", variable=_block_view_var(), command=lambda: set_block_view("3"))
        viewmenu.add_radiobutton(label="4 blocks", value="4", variable=_block_view_var(), command=lambda: set_block_view("4"))
        viewmenu.add_radiobutton(label="6 blocks (3 x 2)", value="6", variable=_block_view_var(), command=lambda: set_block_view("6"))
        viewmenu.add_radiobutton(label="8 blocks (4 x 2)", value="8", variable=_block_view_var(), command=lambda: set_block_view("8"))
        menubar.add_cascade(label="View", menu=viewmenu)
    if adm_permission == "1":
        menubar.add_command(label="Art-Net Viewer", command=open_artnet_viewer)
    menubar.add_command(label="Help", command=open_readme)
    menubar.add_command(label="About", command=show_about)
    root.config(menu=menubar)

# ---------- Output Settings dialog ----------
def open_output_settings():
    d = tk.Toplevel(root)
    d.title("Output Settings")
    _set_window_icon(d)
    d.resizable(False, False)
    d.transient(root); d.grab_set()

    frm = ttk.Frame(d, padding=12); frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Outputs").grid(row=0, column=0, columnspan=3, sticky="w", pady=(0,8))

    mode_var = tk.StringVar(value=output_mode)
    def _on_mode():
        _apply_output_mode(mode_var.get())

    rb1 = ttk.Radiobutton(frm, text="Art-Net only",     value="artnet", variable=mode_var, command=_on_mode)
    rb2 = ttk.Radiobutton(frm, text="USB (uDMX) only",  value="usb",    variable=mode_var, command=_on_mode)
    rb3 = ttk.Radiobutton(frm, text="Art-Net + USB",    value="both",   variable=mode_var, command=_on_mode)
    rb1.grid(row=1, column=0, sticky="w")
    rb2.grid(row=2, column=0, sticky="w")
    rb3.grid(row=3, column=0, sticky="w")

    # Status: alleen mode + USB connected state
    status_lbl = ttk.Label(frm, text="—")
    status_lbl.grid(row=4, column=0, columnspan=3, sticky="w", pady=(10,0))

    # Alleen Close-knop
    btn_row = ttk.Frame(frm); btn_row.grid(row=5, column=0, columnspan=3, sticky="e", pady=(12,0))
    guide_btn = tk.Button(
        btn_row,
        text="uDMX dongle installeren",
        command=lambda: open_path(udmx_driver_guide_file, "uDMX dongle installeren"),
    )
    guide_btn.pack(side="left", padx=(0, 8))
    close_btn = tk.Button(btn_row, text="Close", width=10, command=lambda: (d.grab_release(), d.destroy()))
    close_btn.pack(side="right")

    for c in (0,1,2):
        frm.columnconfigure(c, weight=1)

    # Status updater (geen FPS/B/s hier)
    _status_ctx = {"alive": True}
    def _tick_status():
        if not _status_ctx["alive"]:
            return
        artnet_status = "Art-Net: ready" if ARTNET_AVAILABLE else "Art-Net: unavailable"
        s = f"Mode: {mode_var.get()} | {artnet_status} | {_usb.status_text()}"
        status_lbl.config(text=s)
        d.after(STATUS_REFRESH_MS, _tick_status)

    def _on_close():
        _status_ctx["alive"] = False
        try: d.grab_release()
        except Exception: pass
        d.destroy()

    # Center + focus
    d.update_idletasks()
    try:
        px,py = root.winfo_rootx(), root.winfo_rooty()
        pw,ph = root.winfo_width(), root.winfo_height()
        ww = max(440, d.winfo_width()); wh = max(190, d.winfo_height())
        x = px + (pw - ww)//2; y = py + (ph - wh)//2
        d.geometry(f"{ww}x{wh}+{max(0,x)}+{max(0,y)}")
    except Exception: pass

    d.bind("<Return>", lambda e: _on_close())
    d.protocol("WM_DELETE_WINDOW", _on_close)
    d.after(10, close_btn.focus_set)
    d.after(50, _tick_status)

# ---------- Performance dialog (EN) ----------
def open_performance_dialog():
    d = tk.Toplevel(root)
    d.title("Performance")
    _set_window_icon(d)
    d.resizable(False, False)
    d.transient(root); d.grab_set()

    frm = ttk.Frame(d, padding=12); frm.pack(fill="both", expand=True)

    fps_var    = tk.IntVar(value=int(round(1000.0 / max(1, USB_SEND_MIN_INTERVAL_MS))))
    chunk_var  = tk.IntVar(value=int(USB_CHUNK_SIZE))
    inter_var  = tk.DoubleVar(value=float(USB_INTER_DELAY_MS))
    tick_var   = tk.IntVar(value=int(PLAYBACK_TICK_MS))
    always_var = tk.BooleanVar(value=bool(USB_ALWAYS_SEND))

    r = 0
    ttk.Label(frm, text="USB target FPS").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=fps_var, width=10).grid(row=r, column=1, sticky="w", pady=4)

    r += 1
    ttk.Label(frm, text="USB chunk size").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=chunk_var, width=10).grid(row=r, column=1, sticky="w", pady=4)
    ttk.Label(frm, text="(8…256, 64 recommended)").grid(row=r, column=2, sticky="w")

    r += 1
    ttk.Label(frm, text="USB inter-chunk delay (ms)").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=inter_var, width=10).grid(row=r, column=1, sticky="w", pady=4)

    r += 1
    ttk.Label(frm, text="Playback tick (ms)").grid(row=r, column=0, sticky="w", pady=4)
    ttk.Entry(frm, textvariable=tick_var, width=10).grid(row=r, column=1, sticky="w", pady=4)

    ttk.Checkbutton(frm, text="Always send frames (even if unchanged)",
                    variable=always_var).grid(row=r, column=0, columnspan=3, sticky="w", pady=(6,0))

    r += 1
    info = ttk.Label(frm, text="—", justify="left")
    info.grid(row=r, column=0, columnspan=3, sticky="w", pady=(10,0))

    def _update_info():
        try: chsz = max(1, int(chunk_var.get()))
        except Exception: chsz = 64
        chunks = (512 + chsz - 1) // chsz
        bps_m, fps_m = _usb.stats()
        lines = [
            f"USB status: {_usb.status_text()}",
            f"Chunks per frame: {chunks}",
            f"Measured USB: ~{fps_m:.1f} fps, {bps_m} B/s",
            f"Current output mode: {output_mode}",
        ]
        info.config(text="\n".join(lines))
        d.after(500, _update_info)

    btns = ttk.Frame(frm); btns.grid(row=r+1, column=0, columnspan=3, sticky="e", pady=(12,0))
    def _apply_and_close():
        global USB_SEND_MIN_INTERVAL_MS, USB_CHUNK_SIZE, USB_INTER_DELAY_MS
        global PLAYBACK_TICK_MS, USB_ALWAYS_SEND
        try: f = max(1, int(fps_var.get()))
        except Exception: f = 1
        USB_SEND_MIN_INTERVAL_MS = int(round(1000.0 / f))
        try: USB_CHUNK_SIZE = int(max(1, min(256, int(chunk_var.get()))))
        except Exception: USB_CHUNK_SIZE = 64
        try: USB_INTER_DELAY_MS = float(max(0.0, float(inter_var.get())))
        except Exception: USB_INTER_DELAY_MS = 0.0
        try: PLAYBACK_TICK_MS = int(max(1, int(tick_var.get())))
        except Exception: PLAYBACK_TICK_MS = DEFAULT_TICK_MS
        USB_ALWAYS_SEND = bool(always_var.get())
        save_settings()
        try: d.grab_release()
        except Exception: pass
        d.destroy()

    ok_btn = tk.Button(btns, text="OK", width=10, command=_apply_and_close)
    ok_btn.pack(side="right")

    for c in (0,1,2):
        frm.columnconfigure(c, weight=(1 if c==2 else 0))

    d.update_idletasks()
    try:
        px,py = root.winfo_rootx(), root.winfo_rooty()
        pw,ph = root.winfo_width(), root.winfo_height()
        ww = max(480, d.winfo_width()); wh = max(300, d.winfo_height())
        x = px + (pw - ww)//2; y = py + (ph - wh)//2
        d.geometry(f"{ww}x{wh}+{max(0,x)}+{max(0,y)}")
    except Exception: pass

    d.after(10, ok_btn.focus_set)
    d.bind("<Return>", lambda e: _apply_and_close())
    d.after(50, _update_info)

# ---------- Misc ----------
def _set_bpm():
    global bpm
    new_bpm = _ask_integer("BPM", "New BPM:", initialvalue=bpm,
                           minvalue=1, maxvalue=400, parent=root)
    if new_bpm is not None:
        bpm = int(new_bpm)
        try: bpm_label.config(text=f"BPM: {bpm}")
        except Exception: pass
        save_settings()

# -------- UI actions (scenes) --------
def _resize_active_sets():
    global active_by_block
    count = _visible_block_count()
    while len(active_by_block) < count:
        active_by_block.append(set())
    if len(active_by_block) > count:
        for aset in active_by_block[count:]:
            for sidx in list(aset):
                _stop_chase(sidx)
        active_by_block = active_by_block[:count]

def set_block_view(new_view):
    global block_view
    if str(new_view) not in ("1", "2", "3", "4", "6", "8"):
        return
    block_view = str(new_view)
    _ensure_block_slots()
    for aset in active_by_block:
        for sidx in list(aset):
            _stop_chase(sidx)
        aset.clear()
    _resize_active_sets()
    save_settings()
    update_gui()

def _page_display_name(idx):
    return f"{idx + 1}: {pages[idx]['name']}"

def _slot_page_index(block_idx):
    _ensure_block_slots()
    if not (0 <= block_idx < len(block_slots)):
        return None
    page = block_slots[block_idx].get("page")
    return page if page is not None and 0 <= page < len(pages) else None

def _ensure_page_for_block(block_idx):
    _ensure_block_slots()
    if not (0 <= block_idx < len(block_slots)):
        return
    if _slot_page_index(block_idx) is None:
        pages.append({"name": f"Page {len(pages)+1}", "solo": False, "chases": []})
        block_slots[block_idx]["page"] = len(pages) - 1
        _rebuild_flat_from_inline()
        save_scenes()

def _set_block_page(block_idx, selection):
    _ensure_block_slots()
    if not (0 <= block_idx < len(block_slots)):
        return
    if selection == "New page":
        name = _ask_text("New page", "Page name:", initialvalue=f"Page {len(pages)+1}", parent=root)
        if not name:
            update_gui()
            return
        pages.append({"name": name.strip(), "solo": False, "chases": []})
        block_slots[block_idx]["page"] = len(pages) - 1
    elif selection == "None":
        block_slots[block_idx]["page"] = None
    else:
        try:
            block_slots[block_idx]["page"] = int(str(selection).split(":", 1)[0]) - 1
        except Exception:
            block_slots[block_idx]["page"] = None
    for aset in active_by_block:
        for sidx in list(aset):
            _stop_chase(sidx)
        aset.clear()
    _rebuild_flat_from_inline()
    save_scenes()
    update_gui()

def delete_page(page_idx):
    if not (0 <= page_idx < len(pages)):
        return
    name = pages[page_idx].get("name", f"Page {page_idx+1}")
    if not messagebox.askyesno("Delete page", f"Delete page '{name}' and all scenes on it?", parent=root):
        return
    del pages[page_idx]
    for slot in block_slots:
        page = slot.get("page")
        if page == page_idx:
            slot["page"] = None
        elif page is not None and page > page_idx:
            slot["page"] = page - 1
    for aset in active_by_block:
        for sidx in list(aset):
            _stop_chase(sidx)
        aset.clear()
    _rebuild_flat_from_inline()
    save_scenes()
    update_gui()

def _build_page_selector(parent, block_idx):
    row = tk.Frame(parent)
    row.pack(fill="x", pady=(0, 6))
    page_idx = _slot_page_index(block_idx)
    current = "None" if page_idx is None else _page_display_name(page_idx)
    var = tk.StringVar(value=current)
    values = ["None"] + [_page_display_name(i) for i in range(len(pages))] + ["New page"]
    cb = ttk.Combobox(row, textvariable=var, values=values, state="readonly")
    cb.pack(side="left", fill="x", expand=True)
    cb.bind("<<ComboboxSelected>>", lambda e, i=block_idx, v=var: _set_block_page(i, v.get()))
    del_btn = tk.Button(
        row,
        text="X",
        width=2,
        bd=0,
        relief="flat",
        bg=row.cget("bg"),
        fg="#e81123",
        activebackground=row.cget("bg"),
        activeforeground="#a80000",
        font=("TkDefaultFont", 12, "bold"),
        command=lambda i=block_idx: delete_current_page_for_block(i),
    )
    del_btn.pack(side="left", padx=(4, 0), pady=0)
    if page_idx is None:
        del_btn.config(state="disabled", fg="#999999", disabledforeground="#999999")

def delete_current_page_for_block(block_idx):
    page_idx = _slot_page_index(block_idx)
    if page_idx is None:
        return
    delete_page(page_idx)

def _text_color_for_bg(bg):
    if not isinstance(bg, str) or not bg.startswith("#") or len(bg) != 7:
        return "black"
    try:
        r = int(bg[1:3], 16); g = int(bg[3:5], 16); b = int(bg[5:7], 16)
        return "white" if ((r * 299 + g * 587 + b * 114) / 1000) < 128 else "black"
    except Exception:
        return "black"

_drag_state = {"pressed": None, "dragged": False, "suppress_until": 0}

def _scene_button_click(block_idx, flat_idx):
    if _now_ms() < _drag_state.get("suppress_until", 0):
        return
    toggle_scene_in_block(block_idx, flat_idx)

def _move_chase_in_block(block_idx, from_local, to_local):
    if not (0 <= block_idx < len(blocks)) or blocks[block_idx].get("_none"):
        return
    chases = blocks[block_idx].get("chases", [])
    if not (0 <= from_local < len(chases)):
        return
    to_local = max(0, min(len(chases) - 1, int(to_local)))
    if from_local == to_local:
        return
    ch = chases.pop(from_local)
    chases.insert(to_local, ch)
    for aset in active_by_block:
        for sidx in list(aset):
            _stop_chase(sidx)
        aset.clear()
    _rebuild_flat_from_inline()
    save_scenes()
    update_gui()

def _bind_scene_drag(btn, block_idx, local_idx):
    def _press(event):
        _drag_state["pressed"] = {
            "block": block_idx,
            "local": local_idx,
            "root_y": event.y_root,
            "widget": btn,
        }
        _drag_state["dragged"] = False
    def _motion(event):
        press = _drag_state.get("pressed")
        if not press or press.get("widget") is not btn:
            return
        if abs(event.y_root - press["root_y"]) > 8:
            _drag_state["dragged"] = True
            try: btn.config(relief="sunken")
            except Exception: pass
    def _release(event):
        press = _drag_state.get("pressed")
        try: btn.config(relief="raised")
        except Exception: pass
        if not press or press.get("widget") is not btn:
            return
        _drag_state["pressed"] = None
        if not _drag_state.get("dragged"):
            return
        _drag_state["suppress_until"] = _now_ms() + 300
        chases = blocks[block_idx].get("chases", []) if 0 <= block_idx < len(blocks) else []
        target = press["local"]
        buttons = []
        for ci in range(len(chases)):
            flat_idx = None
            try:
                flat_idx = next(i for i, (b, l) in enumerate(zip(scene_to_block, scene_to_local)) if b == block_idx and l == ci)
            except Exception:
                pass
            if flat_idx is not None:
                widget = scene_buttons_map.get((block_idx, flat_idx))
                if widget:
                    buttons.append((ci, widget))
        for ci, widget in buttons:
            try:
                mid = widget.winfo_rooty() + widget.winfo_height() / 2
                if event.y_root >= mid:
                    target = ci
            except Exception:
                pass
        _move_chase_in_block(block_idx, press["local"], target)
        return "break"
    btn.bind("<ButtonPress-1>", _press, add="+")
    btn.bind("<B1-Motion>", _motion, add="+")
    btn.bind("<ButtonRelease-1>", _release, add="+")

def _make_scrollable_block(parent):
    canvas = tk.Canvas(parent, highlightthickness=0)
    scroll = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
    inner = tk.Frame(canvas)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")
    canvas.configure(yscrollcommand=scroll.set)
    def _sync(_event=None):
        try:
            canvas.itemconfigure(win_id, width=canvas.winfo_width())
            inner.update_idletasks()
            content_h = inner.winfo_reqheight()
            view_h = canvas.winfo_height()
            canvas.configure(scrollregion=(0, 0, canvas.winfo_width(), max(content_h, view_h)))
            if content_h > view_h + 2:
                if not scroll.winfo_ismapped():
                    scroll.grid(row=2, column=1, sticky="ns")
            else:
                canvas.yview_moveto(0)
                if scroll.winfo_ismapped():
                    scroll.grid_remove()
        except Exception:
            pass
    inner.bind("<Configure>", _sync)
    canvas.bind("<Configure>", _sync)
    def _wheel(event):
        try:
            if inner.winfo_reqheight() > canvas.winfo_height() + 2:
                canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
    canvas.bind("<MouseWheel>", _wheel)
    inner.bind("<MouseWheel>", _wheel)
    return canvas, scroll, inner, _wheel

def update_button_highlight():
    for (bi, sidx), btn in scene_buttons_map.items():
        try:
            ch = scenes[sidx] if 0 <= sidx < len(scenes) else {}
            bg = ch.get("button_color") or "SystemButtonFace"
            fg = _text_color_for_bg(bg)
            selected = sidx in active_by_block[bi]
            border = getattr(btn, "_border_frame", None)
            normal_border = getattr(btn, "_normal_border_bg", "SystemButtonFace")
            btn.config(
                bg=bg,
                fg=fg,
                activebackground=bg,
                activeforeground=fg,
                bd=getattr(btn, "_button_bd", 4),
                relief=("sunken" if selected else "raised"),
                highlightthickness=getattr(btn, "_button_highlight", 5),
                highlightbackground=("black" if selected else bg),
                highlightcolor=("black" if selected else bg),
                overrelief=("sunken" if selected else "raised"),
            )
            if border is not None:
                border.config(bg=normal_border)
        except Exception:
            pass

def toggle_scene_in_block(block_idx, flat_scene_index):
    if not (0 <= block_idx < len(blocks)) or not (0 <= flat_scene_index < len(scenes)):
        return
    if blocks[block_idx].get("solo", False):
        if flat_scene_index in active_by_block[block_idx]:
            active_by_block[block_idx].clear()
            _stop_chase(flat_scene_index)
        else:
            for sidx in list(active_by_block[block_idx]): _stop_chase(sidx)
            active_by_block[block_idx].clear()
            active_by_block[block_idx].add(flat_scene_index)
            _start_chase_if_needed(flat_scene_index, _now_ms())
    else:
        if flat_scene_index in active_by_block[block_idx]:
            active_by_block[block_idx].remove(flat_scene_index)
            _stop_chase(flat_scene_index)
        else:
            active_by_block[block_idx].add(flat_scene_index)
            _start_chase_if_needed(flat_scene_index, _now_ms())
    update_button_highlight()

def set_block_solo(block_idx, is_on):
    blocks[block_idx]["solo"] = bool(is_on)
    save_scenes()
    if blocks[block_idx]["solo"] and len(active_by_block[block_idx]) > 1:
        keep = max(active_by_block[block_idx])
        for sidx in list(active_by_block[block_idx]):
            if sidx != keep: _stop_chase(sidx)
        active_by_block[block_idx].clear()
        active_by_block[block_idx].add(keep)
    update_button_highlight()

def rename_block(block_idx):
    if adm_permission != "1": return
    if not (0 <= block_idx < len(blocks)) or blocks[block_idx].get("_none"):
        return
    new_name = _ask_text("Rename page", "New name:",
                         initialvalue=blocks[block_idx]["name"], parent=root)
    if new_name:
        blocks[block_idx]["name"] = new_name
        save_scenes(); update_gui()

def create_chase_and_open_editor(block_idx):
    if adm_permission != "1": return
    _ensure_page_for_block(block_idx)
    if blocks[block_idx].get("_none"):
        return
    new_ch = _empty_chase("New chase")
    blocks[block_idx]["chases"].append(new_ch)
    _rebuild_flat_from_inline()
    save_scenes()
    update_gui()
    for sidx in reversed(range(len(scenes))):
        if scene_to_block[sidx] == block_idx:
            open_scene_editor(sidx)
            break

def _remap_active_sets_after_delete(deleted_flat_idx):
    for aset in active_by_block:
        newset = set()
        for sidx in aset:
            if sidx == deleted_flat_idx:
                continue
            elif sidx > deleted_flat_idx:
                newset.add(sidx - 1)
            else:
                newset.add(sidx)
        aset.clear(); aset.update(newset)

def delete_scene(scene_index):
    if not (0 <= scene_index < len(scenes)): return
    _stop_chase(scene_index)
    bi = scene_to_block[scene_index]; ci = scene_to_local[scene_index]
    try: del blocks[bi]["chases"][ci]
    except Exception: pass
    _remap_active_sets_after_delete(scene_index)
    _rebuild_flat_from_inline()
    save_scenes(); update_gui()

def load_scene(scene_index):
    if not (0 <= scene_index < len(scenes)): return
    blk_idx = scene_to_block[scene_index]
    toggle_scene_in_block(blk_idx, scene_index)

def stop_all_scenes():
    for aset in active_by_block:
        for sidx in list(aset): _stop_chase(sidx)
        aset.clear()
    send_dmx([0]*dmx_channels)
    update_button_highlight()

def update_gui():
    global scene_buttons, scene_buttons_map, block_frames
    for child in scene_button_frame.winfo_children():
        try: child.destroy()
        except Exception: pass
    scene_buttons, scene_buttons_map, block_frames = [], {}, []

    _ensure_block_slots()
    _rebuild_flat_from_inline()

    flat_lookup, cursor = {}, 0
    for bi, blk in enumerate(blocks):
        for ci, _ in enumerate(blk["chases"]):
            flat_lookup[(bi, ci)] = cursor; cursor += 1

    visible_count = _visible_block_count()
    cols, rows = _block_grid_shape()
    try:
        scene_button_frame.grid_propagate(False)
    except Exception:
        pass
    for i in range(8):
        try:
            scene_button_frame.grid_columnconfigure(i, weight=0, minsize=0, uniform="")
        except Exception:
            pass
    for r in range(4):
        try:
            scene_button_frame.grid_rowconfigure(r, weight=0, minsize=0, uniform="")
        except Exception:
            pass
    for i in range(cols):
        try:
            scene_button_frame.grid_columnconfigure(i, weight=1, minsize=1, uniform=f"blocks{visible_count}")
        except Exception:
            pass
    for r in range(rows):
        try:
            scene_button_frame.grid_rowconfigure(r, weight=1, minsize=1, uniform=f"blockrows{visible_count}")
        except Exception:
            pass

    for bi, blk in enumerate(blocks[:visible_count]):
        col = tk.Frame(scene_button_frame, bd=2, relief="groove", padx=6, pady=6)
        col.grid(row=(bi // cols), column=(bi % cols), sticky="nsew", padx=6, pady=6)
        col.grid_columnconfigure(0, weight=1)
        col.grid_rowconfigure(2, weight=1)
        block_frames.append(col)

        if adm_permission == "1":
            selector_wrap = tk.Frame(col)
            selector_wrap.grid(row=0, column=0, sticky="ew", pady=(0, 6))
            _build_page_selector(selector_wrap, bi)

        if not (blk.get("_none") and adm_permission != "1"):
            title = tk.Label(col, text=blk["name"], font=("TkDefaultFont", 12, "bold"))
            title.grid(row=1, column=0, sticky="w", pady=(0, 4))
            if adm_permission == "1" and not blk.get("_none"):
                title.bind("<Button-3>", lambda e, i=bi: rename_block(i))

        scroll_canvas, scroll_bar, button_area, block_wheel = _make_scrollable_block(col)
        scroll_canvas.grid(row=2, column=0, sticky="nsew")
        compact_buttons = visible_count in (6, 8)
        button_gap_y = 1
        button_pad_y = 1
        button_pad_x = 4
        button_bd = 2 if compact_buttons else 4
        button_highlight = 3 if compact_buttons else 5
        button_font = ("TkDefaultFont", 10)

        if blk["chases"]:
            for ci, ch in enumerate(blk["chases"]):
                sname = ch.get("name", "Scene")
                flat_idx = flat_lookup[(bi, ci)]
                bg = ch.get("button_color") or "SystemButtonFace"
                normal_border_bg = button_area.cget("bg")
                border = tk.Frame(button_area, bg=normal_border_bg)
                border.pack(fill="x", pady=button_gap_y)
                border.grid_columnconfigure(0, weight=1)
                btn = tk.Button(border, text=sname,
                                command=lambda i=bi, j=flat_idx: _scene_button_click(i, j))
                btn.config(
                    bg=bg,
                    fg=_text_color_for_bg(bg),
                    activebackground=bg,
                    activeforeground=_text_color_for_bg(bg),
                    bd=button_bd,
                    relief="raised",
                    highlightthickness=button_highlight,
                    highlightbackground=bg,
                    highlightcolor=bg,
                    overrelief="raised",
                    font=button_font,
                )
                btn.grid(row=0, column=0, sticky="ew", padx=button_pad_x, pady=button_pad_y)
                btn._border_frame = border
                btn._normal_border_bg = normal_border_bg
                btn._button_bd = button_bd
                btn._button_highlight = button_highlight
                if adm_permission == "1":
                    btn.bind("<Button-3>", lambda e, j=flat_idx: open_scene_editor(j))
                    _bind_scene_drag(btn, bi, ci)
                btn.bind("<MouseWheel>", block_wheel)
                border.bind("<MouseWheel>", block_wheel)
                scene_buttons.append(btn)
                scene_buttons_map[(bi, flat_idx)] = btn
        else:
            if not (blk.get("_none") and adm_permission != "1"):
                empty_text = "(No page)" if blk.get("_none") else "(No chases)"
                empty = tk.Label(button_area, text=empty_text, justify="center")
                empty.pack(fill="x", pady=12, ipady=10)
            if adm_permission == "1":
                button_area.bind("<Button-3>", lambda e, i=bi: create_chase_and_open_editor(i))

        if adm_permission == "1":
            row = tk.Frame(col); row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            if not blk.get("_none"):
                solo_var = tk.BooleanVar(value=blk.get("solo", False))
                tk.Checkbutton(row, text="Solo", variable=solo_var,
                               command=lambda i=bi, v=solo_var: set_block_solo(i, v.get())
                               ).pack(side="left")
            tk.Button(row, text="+", width=3,
                      command=lambda i=bi: create_chase_and_open_editor(i)).pack(side="right")

    update_button_highlight()

# ---------- main ----------
def main():
    global root, scene_button_frame, scene_buttons, scene_buttons_map, block_frames
    global bpm_label, sound_label, menubar

    root = tk.Tk()
    root.title("LumiControLL")
    root.resizable(True, True)
    _set_window_icon(root)
    _update_window_title()

    menubar = tk.Menu(root); root.config(menu=menubar)
    update_menubar()

    top = tk.Frame(root); top.pack(fill="x")
    bpm_label = tk.Label(top, text=f"BPM: {bpm}", width=10); bpm_label.pack(side="right", padx=(0,8))
    bpm_label.bind("<Button-1>", lambda e: _set_bpm())
    sound_label = tk.Label(top, text="NO MIC", width=8, fg="red", cursor="hand2")
    sound_label.pack(side="right", padx=6)

    def _open_sound_settings(_evt=None):
        if not mic_status.get("available", False):
            _open_no_mic_dialog()
            return
        init = load_sound_settings()
        def apply_live(vals):
            if detector:
                detector.mode = vals["mode"]
                detector.threshold = vals["thr"]
                detector.min_interval_ms = vals["minint"]
                detector.hold_ms = vals["hold"]
                detector.min_slope = vals["slope"]
        def finalize(vals):
            current = load_sound_settings()
            current.update(vals)
            save_sound_settings(current)
        SoundSettingsDialog(root, init, apply_live, finalize)
    sound_label.bind("<Button-1>", _open_sound_settings)

    _flash = {"on": False}
    def _bpm_flash():
        _flash["on"] = not _flash["on"]
        try: bpm_label.config(fg=("red" if _flash["on"] else "green"))
        except Exception: pass
        try: root.after(int(60000 / max(1, bpm)), _bpm_flash)
        except Exception: pass
    _bpm_flash()

    scene_buttons, scene_buttons_map, block_frames = [], {}, []
    scene_button_frame = tk.Frame(root); scene_button_frame.pack(fill="both", expand=True)
    try: scene_button_frame.grid_rowconfigure(0, weight=1)
    except Exception: pass

    init_editor({
        "root": root,
        "icon_file": icon_file,
        "dmx_channels": dmx_channels,
        "BANK_SIZE": BANK_SIZE,
        "borderless_fill_workarea": borderless_fill_workarea,
        "ensure_len_128": _normalise_chase,
        "get_blocks": lambda: blocks,
        "get_scenes": lambda: scenes,
        "get_scene_to_block": lambda: scene_to_block,
        "get_scene_to_local": lambda: scene_to_local,
        "set_editor_preview_frame": set_editor_preview_frame,
        "clear_editor_preview_frame": clear_editor_preview_frame,
        "get_preview_on": lambda: editor_preview_on,
        "set_preview_on": lambda v: globals().__setitem__('editor_preview_on', bool(v)),
        "rebuild_flat_from_inline": _rebuild_flat_from_inline,
        "save_scenes": save_scenes,
        "update_gui": update_gui,
        "delete_scene_cb": delete_scene,
    })

    update_gui()

    try:
        root.update_idletasks()
        root.after(0, lambda: root.state('zoomed'))
    except Exception: pass

    # Admin hotkey
    if keyboard:
        try: keyboard.add_hotkey("alt+shift+s", toggle_admin_mode)
        except Exception: pass
    root.bind_all("<Alt-Shift-s>", lambda e: toggle_admin_mode())

    # Performance hotkey (Alt-Shift-P)
    if keyboard:
        try: keyboard.add_hotkey("alt+shift+p", lambda: open_performance_dialog())
        except Exception: pass
    root.bind_all("<Alt-Shift-p>", lambda e: open_performance_dialog())

    # USB opstart alleen als mode dit vereist
    if output_mode in ("usb", "both"):
        _usb.ensure_open(root=root, verbose=False, force=True)
    if output_mode in ("artnet", "both") and not ARTNET_AVAILABLE:
        messagebox.showerror(
            "Art-Net",
            f"StupidArtnet could not be loaded.\nArt-Net output is disabled.\n\n{ARTNET_IMPORT_ERROR}",
            parent=root,
        )

    # Audio detector
    _start_audio_detector(silent=True)

    # Hoofdlus
    def _tick():
        try:
            _handle_pending_events()
            _check_audio_detector_health()
            # probeer periodiek te openen met backoff (ipv bij elke send)
            if output_mode in ("usb","both"):
                _usb.ensure_open(root=root, verbose=False)
            render_and_send()
        finally:
            try: root.after(PLAYBACK_TICK_MS, _tick)
            except Exception: pass
    root.after(PLAYBACK_TICK_MS, _tick)

    def _on_quit():
        try: stop_all_scenes()
        except Exception: pass
        try:
            if detector: detector.stop()
        except Exception: pass
        try:
            if output_mode in ("usb","both"): _usb.blackout()
        except Exception: pass
        try:
            if output_mode in ("usb","both"): _usb.close()
        except Exception: pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", _on_quit)
    root.mainloop()

# ---------- Window helpers ----------
def _workarea_for_window(win):
    if sys.platform.startswith("win"):
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        MONITOR_DEFAULTTONEAREST = 0x00000002
        class RECT(ctypes.Structure):
            _fields_ = [("left", wintypes.LONG), ("top", wintypes.LONG),
                        ("right", wintypes.LONG), ("bottom", wintypes.LONG)]
        class MONITORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD),
                        ("rcMonitor", RECT),
                        ("rcWork", RECT),
                        ("dwFlags", wintypes.DWORD)]
        hwnd = win.winfo_id()
        hmon = user32.MonitorFromWindow(hwnd, MONITOR_DEFAULTTONEAREST)
        mi = MONITORINFO(); mi.cbSize = ctypes.sizeof(MONITORINFO)
        user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
        wa = mi.rcWork
        x, y = wa.left, wa.top
        w, h = wa.right - wa.left, wa.bottom - wa.top
        return x, y, w, h
    else:
        try: sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        except Exception: sw, sh = 1280, 800
        return 0, 0, sw, sh

def borderless_fill_workarea(win):
    try: win.update_idletasks()
    except Exception: pass
    try: win.overrideredirect(True)
    except Exception: pass
    x, y, w, h = _workarea_for_window(win)
    try: win.geometry(f"{w}x{h}+{x}+{y}")
    except Exception: pass
    try: win.lift(); win.focus_force()
    except Exception: pass

class SoundSettingsDialog(tk.Toplevel):
    def __init__(self, parent, init_values, on_apply, on_finalize):
        super().__init__(parent)
        self.title("Sound settings")
        _set_window_icon(self)
        self.resizable(False, False)
        self.configure(padx=16, pady=16)
        try: self.attributes("-topmost", True)
        except Exception: pass
        self.transient(parent); self.grab_set()

        self.on_apply = on_apply
        self.on_finalize = on_finalize

        self.mode_var   = tk.StringVar(value=init_values.get("mode", "Full RMS"))
        self.thr_var    = tk.DoubleVar(value=float(init_values.get("thr", 0.70)))
        self.minint_var = tk.IntVar(   value=int(init_values.get("minint", 180)))
        self.hold_var   = tk.IntVar(   value=int(init_values.get("hold", 120)))
        self.slope_var  = tk.DoubleVar(value=float(init_values.get("slope", 0.00)))

        for v in (self.mode_var, self.thr_var, self.minint_var, self.hold_var, self.slope_var):
            try: v.trace_add("write", lambda *_: self._apply_live())
            except Exception:
                try: v.trace("w", lambda *_: self._apply_live())
                except Exception: pass

        ttk.Label(self, text="Detection mode").grid(row=0, column=0, sticky="w", pady=6)
        mode_box = ttk.Combobox(self, values=AudioPulseDetector.DETECT_MODES,
                                textvariable=self.mode_var, state="readonly", width=28)
        mode_box.grid(row=0, column=1, sticky="ew", pady=6)

        self._row_slider("Threshold",           1, 0.05, 1.20, self.thr_var,   "{:.2f}")
        self._row_slider("Min. interval (ms)",  2, 40,   500,  self.minint_var,"{:.0f}")
        self._row_slider("Hold (ms)",           3, 0,    300,  self.hold_var,  "{:.0f}")
        self._row_slider("Min. slope",          4, 0.00, 0.10, self.slope_var, "{:.3f}")

        btns = ttk.Frame(self); btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12,0))
        tk.Button(btns, text="Select Input", command=self._select_input, width=12).pack(side="left", padx=(0, 8))
        okb = tk.Button(btns, text="Close", command=self._close, width=12); okb.pack(side="right")

        for c in (0, 1):
            self.columnconfigure(c, weight=(1 if c == 1 else 0))

        self.update_idletasks()
        try:
            px,py = parent.winfo_rootx(), parent.winfo_rooty()
            pw,ph = parent.winfo_width(), parent.winfo_height()
            ww,wh = self.winfo_width(), self.winfo_height()
            x  = px + (pw - ww)//2; y  = py + (ph - wh)//2
            self.geometry(f"+{max(0,x)}+{max(0,y)}")
        except Exception: pass

        self.bind("<Return>", lambda e: self._close())
        okb.focus_set()

    def _row_slider(self, label, row, vmin, vmax, var, fmt):
        ttk.Label(self, text=label).grid(row=row, column=0, sticky="w", pady=6)
        frm = ttk.Frame(self); frm.grid(row=row, column=1, sticky="ew", pady=6)
        frm.columnconfigure(0, weight=1)
        val_lbl = ttk.Label(frm, text=fmt.format(var.get()), width=8, anchor="e")
        val_lbl.grid(row=0, column=1, sticky="e", padx=(8,0))
        scl = ttk.Scale(frm, from_=vmin, to=vmax, orient="horizontal",
                        variable=var,
                        command=lambda *_: val_lbl.config(text=fmt.format(var.get())))
        scl.grid(row=0, column=0, sticky="ew")

    def _vals(self):
        return dict(
            mode   = self.mode_var.get(),
            thr    = float(self.thr_var.get()),
            minint = int(self.minint_var.get()),
            hold   = int(self.hold_var.get()),
            slope  = float(self.slope_var.get()),
        )

    def _apply_live(self):
        self.on_apply(self._vals())

    def _select_input(self):
        _open_input_select_dialog(no_mic=False, parent=self)

    def _close(self):
        vals = self._vals()
        self.on_apply(vals)
        self.on_finalize(vals)
        try: self.grab_release()
        except Exception: pass
        self.destroy()

if __name__ == "__main__":
    main()
