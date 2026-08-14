#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys, os, socket, struct, threading, time, traceback, queue, tkinter as tk, re
from tkinter import ttk

# -------- Config --------
ARTNET_PORT = 6454
DEFAULT_BIND_IP = "0.0.0.0"
DEFAULT_UNIVERSE = 1

# Grid & UI
ROWS = 32
COLS = 16
VISIBLE_COLS = 4
PADDING = 10
COL_GAP_X = 12
ROW_GAP_Y = 6
LABEL_W = 52
BAR_MARGIN = 6
BAR_H = 20
TITLE_FONT = ("Segoe UI", 10, "bold")
FONT = ("Segoe UI", 9)
UPDATE_INTERVAL_MS = 15  # ~66 Hz

# -------- Art-Net helpers --------
def is_artnet_packet(data: bytes) -> bool:
    return len(data) >= 10 and data[:8] == b'Art-Net\x00'

OP_POLL, OP_POLLREPLY, OP_DMX = 0x2000, 0x2100, 0x5000

def parse_opcode(data: bytes) -> int:
    import struct
    return struct.unpack_from("<H", data, 8)[0]

def parse_artdmx_fields(data: bytes):
    import struct
    if len(data) < 18 or not is_artnet_packet(data) or parse_opcode(data) != OP_DMX:
        return None
    seq, subuni, net = data[12], data[14], data[15]
    length = (data[16] << 8) | data[17]
    if length < 2 or length > 512:
        return None
    dmx = data[18:18+length]
    return {"seq": seq, "subuni": subuni, "net": net, "length": length, "dmx": dmx}

def ip_bytes(ip_str: str):
    return bytes(map(int, ip_str.split(".")))

def pad_ascii(s: str, length: int) -> bytes:
    b = s.encode("ascii", errors="ignore")
    if len(b) >= length:
        return b[:length-1] + b"\x00"
    return b + b"\x00" + b"\x00"*(length-len(b)-1)

def build_artpoll_reply(src_ip: str):
    ID = b"Art-Net\x00"; import struct
    OpPollReply = struct.pack("<H", OP_POLLREPLY)
    ip = ip_bytes(src_ip); port = struct.pack("<H", ARTNET_PORT)
    VersInfoH, VersInfoL = bytes([1]), bytes([0])
    NetSwitch, SubSwitch = bytes([0]), bytes([0])
    Oem = struct.pack("<H", 0xFFFF)
    UbeaVersion, Status1 = bytes([0]), bytes([0])
    EstaMan = struct.pack(">H", 0)
    ShortName = pad_ascii("VirtualNode", 18)
    LongName  = pad_ascii("Virtual Art-Net Testnode", 64)
    NodeReport = pad_ascii("#0001 OK", 64)
    NumPortsHi, NumPortsLo = bytes([0]), bytes([1])
    PortTypes = bytes([0xC0, 0, 0, 0])
    GoodInput  = bytes([0, 0, 0, 0]); GoodOutput = bytes([0, 0, 0, 0])
    SwIn, SwOut = bytes([0x01, 0, 0, 0]), bytes([0x01, 0, 0, 0])
    SwVideo, SwMacro, SwRemote = bytes([0]), bytes([0]), bytes([0])
    Spare, Style = b"\x00\x00\x00", bytes([0x00])
    Mac = bytes([0x00, 0x12, 0x34, 0x56, 0x78, 0x9A])
    BindIp, BindIndex, Status2 = ip, bytes([1]), bytes([0x00])
    Filler = b"\x00" * 26
    return (ID + OpPollReply + ip + port + VersInfoH + VersInfoL + NetSwitch + SubSwitch + Oem +
            UbeaVersion + Status1 + EstaMan + ShortName + LongName + NodeReport + NumPortsHi + NumPortsLo +
            PortTypes + GoodInput + GoodOutput + SwIn + SwOut + SwVideo + SwMacro + SwRemote + Spare +
            Style + Mac + BindIp + BindIndex + Status2 + Filler)

# -------- NIC listing (fysiek-filter + blacklist) --------
BLACKLIST_PATTERNS = [r"loopback", r"bluetooth", r"lan"]  # case-insensitive
import re
def looks_virtual(label: str) -> bool:
    s = (label or "")
    for pat in BLACKLIST_PATTERNS:
        if re.search(pat, s, flags=re.I):
            return True
    return False

def list_ipv4_interfaces(only_physical=True):
    items = [("All interfaces (0.0.0.0)", "0.0.0.0")]
    added = set()
    # Windows API
    try:
        import ctypes
        from ctypes import wintypes
        AF_INET = 2
        IF_TYPE_ETHERNET = 6
        IF_TYPE_IEEE80211 = 71
        class SOCKET_ADDRESS(ctypes.Structure):
            _fields_ = [("lpSockaddr", ctypes.c_void_p), ("iSockaddrLength", ctypes.c_int)]
        class IP_ADAPTER_UNICAST_ADDRESS(ctypes.Structure): pass
        LP_U = ctypes.POINTER(IP_ADAPTER_UNICAST_ADDRESS)
        IP_ADAPTER_UNICAST_ADDRESS._fields_ = [("Length", ctypes.c_ulong), ("Flags", ctypes.c_ulong),
                                               ("Next", LP_U), ("Address", SOCKET_ADDRESS)]
        class IP_ADAPTER_ADDRESSES(ctypes.Structure): pass
        LP_A = ctypes.POINTER(IP_ADAPTER_ADDRESSES)
        IP_ADAPTER_ADDRESSES._fields_ = [
            ("Length", ctypes.c_ulong), ("IfIndex", ctypes.c_ulong), ("Next", LP_A),
            ("AdapterName", ctypes.c_char_p), ("FirstUnicastAddress", LP_U),
            ("FirstAnycastAddress", ctypes.c_void_p), ("FirstMulticastAddress", ctypes.c_void_p),
            ("FirstDnsServerAddress", ctypes.c_void_p), ("DnsSuffix", ctypes.c_wchar_p),
            ("Description", ctypes.c_wchar_p), ("FriendlyName", ctypes.c_wchar_p),
            ("PhysicalAddress", ctypes.c_ubyte * 8), ("PhysicalAddressLength", ctypes.c_ulong),
            ("Flags", ctypes.c_ulong), ("Mtu", ctypes.c_ulong), ("IfType", ctypes.c_ulong),
            ("OperStatus", ctypes.c_int), ("Ipv6IfIndex", ctypes.c_ulong),
            ("ZoneIndices", ctypes.c_ulong * 16), ("FirstPrefix", ctypes.c_void_p),
        ]
        GetAdaptersAddresses = ctypes.windll.iphlpapi.GetAdaptersAddresses
        GetAdaptersAddresses.restype = ctypes.c_ulong
        size = ctypes.c_ulong(15000)
        buff = ctypes.create_string_buffer(size.value)
        args = (2, 0x0002 | 0x0004 | 0x0008 | 0x0010, None, buff, ctypes.byref(size))
        ret = GetAdaptersAddresses(*args)
        if ret == 111:
            buff = ctypes.create_string_buffer(size.value); ret = GetAdaptersAddresses(*args)
        if ret == 0:
            addr = ctypes.cast(buff, LP_A)
            while addr:
                name = addr.contents.FriendlyName or ""
                if only_physical and addr.contents.IfType not in (IF_TYPE_ETHERNET, IF_TYPE_IEEE80211):
                    addr = addr.contents.Next if addr.contents.Next else None
                    continue
                u = addr.contents.FirstUnicastAddress
                while u:
                    try:
                        fam = ctypes.cast(u.contents.Address.lpSockaddr, ctypes.POINTER(ctypes.c_ushort)).contents.value
                        if fam == AF_INET:
                            raw = (ctypes.c_ubyte * 16).from_address(u.contents.Address.lpSockaddr)
                            ip = f"{raw[4]}.{raw[5]}.{raw[6]}.{raw[7]}"
                            label = f"{name} ({ip})" if name else ip
                            if ip != "127.0.0.1" and ip not in added:
                                if (not only_physical) or (only_physical and not looks_virtual(label)):
                                    items.append((label, ip)); added.add(ip)
                    except Exception:
                        pass
                    u = u.contents.Next if u.contents.Next else None
                addr = addr.contents.Next if addr.contents.Next else None
            if "127.0.0.1" not in added:
                items.append(("Loopback (127.0.0.1)", "127.0.0.1"))
            return items
    except Exception:
        pass
    # Fallback
    try:
        for fam, _, _, _, sa in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = sa[0]
            label = ip
            if ip != "127.0.0.1" and ip not in added:
                if (not only_physical) or (only_physical and not looks_virtual(label)):
                    items.append((label, ip)); added.add(ip)
    except Exception:
        pass
    if "127.0.0.1" not in added:
        items.append(("Loopback (127.0.0.1)", "127.0.0.1"))
    return items

# -------- Work area helpers --------
def get_work_area_rect_and_bottom_margin():
    try:
        import ctypes
        from ctypes import wintypes
        user32 = ctypes.windll.user32
        try: user32.SetProcessDPIAware()
        except Exception: pass
        SPI_GETWORKAREA = 0x0030
        wa = wintypes.RECT()
        ok = user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(wa), 0)
        sw = user32.GetSystemMetrics(0); sh = user32.GetSystemMetrics(1)
        if ok: x, y, w, h = wa.left, wa.top, wa.right-wa.left, wa.bottom-wa.top
        else:  x, y, w, h = 0, 0, sw, sh
        bottom_margin = max(0, sh - (y + h))
        return x, y, w, h, bottom_margin
    except Exception:
        return 0, 0, 0, 0, 0

def apply_work_area_geometry(root: tk.Tk):
    x, y, w, h, bottom_margin = get_work_area_rect_and_bottom_margin()
    if w and h:
        root.geometry(f"{w}x{h}+{x}+{y}"); root.update_idletasks()
    else:
        try: root.state("zoomed")
        except Exception:
            sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
            root.geometry(f"{sw}x{sh}+0+0")
    return bottom_margin

# -------- Icon helpers --------
def set_app_icon(window: tk.Tk, icon_filename: str = "an.ico"):
    candidates = []
    try:
        candidates.append(os.path.abspath(icon_filename))  # cwd
        script_dir = os.path.dirname(os.path.abspath(__file__))
        candidates.append(os.path.join(script_dir, icon_filename))  # naast script
    except Exception:
        candidates.append(os.path.abspath(icon_filename))
    tried = set()
    for path in candidates:
        if not path or path in tried: continue
        tried.add(path)
        if os.path.exists(path):
            try:
                if sys.platform == "win32":
                    window.iconbitmap(path)
                    return True
                else:
                    try:
                        img = tk.PhotoImage(file=path)
                        window.iconphoto(True, img)
                        return True
                    except Exception:
                        pass
            except Exception:
                pass
    print("[INFO] an.ico niet gevonden of kon niet geladen worden; ga door zonder custom icoon.")
    return False

# -------- Windows fullscreen helpers --------
def _win32_virtual_screen_rect():
    import ctypes
    user32 = ctypes.windll.user32
    try: user32.SetProcessDPIAware()
    except Exception: pass
    SM_XVIRTUALSCREEN = 76
    SM_YVIRTUALSCREEN = 77
    SM_CXVIRTUALSCREEN = 78
    SM_CYVIRTUALSCREEN = 79
    x = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    y = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    w = user32.GetSystemMetrics(SM_CXVIRTUALSCREEN)
    h = user32.GetSystemMetrics(SM_CYVIRTUALSCREEN)
    if w <= 0 or h <= 0:
        x, y = 0, 0
        w = user32.GetSystemMetrics(0)
        h = user32.GetSystemMetrics(1)
    return x, y, w, h

def _win32_force_fullscreen(hwnd, x, y, w, h):
    import ctypes
    user32 = ctypes.windll.user32
    HWND_TOPMOST = -1
    SWP_SHOWWINDOW = 0x0040
    # Forceer topmost + exacte geometry
    user32.SetWindowPos(ctypes.wintypes.HWND(hwnd), ctypes.wintypes.HWND(HWND_TOPMOST),
                        x, y, w, h, SWP_SHOWWINDOW)

# -------- UI / Node --------
class VirtualArtnetNode:
    def __init__(self, root):
        self.root = root
        self.root.title("Art-Net viewer")
        try: set_app_icon(self.root, "an.ico")
        except Exception: pass

        self.dmx = [0] * 512
        self._pps_window = []
        self.pps = 0.0
        self.queue = queue.Queue()

        self.col_w = 300; self.bar_w = 240
        self.content_w = 0; self.content_h = 0
        self.items = {}

        self.bind_ip = DEFAULT_BIND_IP
        self.accept_universe = DEFAULT_UNIVERSE

        self.sock = None
        self.running = True
        self.thread = None

        # V-Light
        self.vlight_active = False
        self.vlight_start = 1
        self.vlight_win = None
        self.vlight_fill = None
        self.vlight_dirty = False

        self._build_ui()
        self.safe_bottom_px = apply_work_area_geometry(self.root)
        self._apply_safe_bottom_padding()
        self._start_udp_thread()

        # UI bindings
        self.root.bind_all("<Shift-MouseWheel>", self._on_shift_wheel)
        self.root.bind("<Configure>", self._on_root_configure)
        self.canvas.bind("<Configure>", self._on_canvas_resize)
        self._schedule_ui_update()

    # ---- UI ----
    def _build_ui(self):
        top = ttk.Frame(self.root, padding=(PADDING, PADDING)); top.pack(fill="x")

        # NIC + checkbox in 1 regel
        nic_row = ttk.Frame(top); nic_row.pack(fill="x", pady=(0, 6))
        nic_row.columnconfigure(1, weight=1)
        ttk.Label(nic_row, text="Luisteren op:").grid(row=0, column=0, sticky="w", padx=(0,6))

        self.nic_var = tk.StringVar()
        self.nic_box = ttk.Combobox(nic_row, textvariable=self.nic_var, state="readonly")
        self.nic_items = list_ipv4_interfaces(only_physical=True)
        self.nic_box["values"] = [lbl for (lbl, ip) in self.nic_items]
        self.nic_box.current(0)
        self.nic_box.grid(row=0, column=1, sticky="ew")

        self.only_phys_var = tk.BooleanVar(value=True)
        self.only_phys_chk = ttk.Checkbutton(
            nic_row, text="Toon alleen fysieke adapters",
            variable=self.only_phys_var, command=self._on_only_physical_changed
        )
        self.only_phys_chk.grid(row=0, column=2, sticky="e", padx=(8,0))
        self.nic_box.bind("<<ComboboxSelected>>", self._on_nic_changed)

        # Universe
        uni_row = ttk.Frame(top); uni_row.pack(fill="x", pady=(0, 6))
        ttk.Label(uni_row, text="Universe:").pack(side="left")
        self.uni_var = tk.IntVar(value=self.accept_universe)
        self.uni_spin = tk.Spinbox(uni_row, from_=0, to=255, textvariable=self.uni_var, width=6)
        self.uni_spin.pack(side="left", padx=(6, 12))
        self.uni_var.trace_add("write", lambda *args: self._on_universe_changed())
        self.uni_spin.bind("<FocusOut>", lambda e: self._on_universe_changed())
        self.uni_spin.bind("<Return>", lambda e: self._on_universe_changed())

        # Status + V-Light in dezelfde regel
        status_row = ttk.Frame(top); status_row.pack(fill="x", pady=(0, 6))
        status_row.columnconfigure(0, weight=1)
        self.status_var = tk.StringVar(value=f"Luistert op {self.bind_ip}:{ARTNET_PORT}  |  PPS: 0.0")
        ttk.Label(status_row, textvariable=self.status_var, font=TITLE_FONT).grid(row=0, column=0, sticky="w")
        ttk.Button(status_row, text="V-Light", command=self._open_vlight_prompt).grid(row=0, column=1, sticky="e")

        # Canvas + scrollbar
        self.wrap = ttk.Frame(self.root); self.wrap.pack(fill="both", expand=True, padx=PADDING, pady=(0, PADDING))
        self.wrap.columnconfigure(0, weight=1); self.wrap.rowconfigure(0, weight=1)
        self.canvas = tk.Canvas(self.wrap, bg="#202020", highlightthickness=0)
        self.hbar = ttk.Scrollbar(self.wrap, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(xscrollcommand=self.hbar.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.hbar.grid(row=1, column=0, sticky="ew")

        self._render_grid(initial=True)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---- V-Light ----
    def _center_dialog(self, dlg):
        dlg.update_idletasks()
        rw = self.root.winfo_width(); rh = self.root.winfo_height()
        rx = self.root.winfo_rootx(); ry = self.root.winfo_rooty()
        dw = dlg.winfo_width(); dh = dlg.winfo_height()
        x = rx + (rw - dw) // 2; y = ry + (rh - dh) // 2
        dlg.geometry(f"+{max(0,x)}+{max(0,y)}")

    def _open_vlight_prompt(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("V-Light")
        dlg.transient(self.root)
        dlg.grab_set()
        try: set_app_icon(dlg, "an.ico")
        except Exception: pass

        ttk.Label(dlg, text="Start DMX Chanel:").pack(padx=12, pady=(12, 6), anchor="w")
        start_var = tk.StringVar(value="1")  # default 1
        start_box = ttk.Combobox(dlg, state="readonly",
                                 values=[str(i) for i in range(0, 511)],
                                 textvariable=start_var, width=8)
        start_box.pack(padx=12, pady=(0, 12), anchor="w")

        btn_row = ttk.Frame(dlg); btn_row.pack(fill="x", padx=12, pady=(0, 12))
        def on_ok():
            try: v = int(start_var.get())
            except Exception: v = 1
            v = max(0, min(510, v))
            self.vlight_start = v
            dlg.destroy()
            self._open_vlight_fullscreen()
        def on_cancel(): dlg.destroy()

        ttk.Button(btn_row, text="OK", command=on_ok).pack(side="right")
        ttk.Button(btn_row, text="Annuleren", command=on_cancel).pack(side="right", padx=(0,8))

        start_box.focus_set()
        dlg.bind("<Return>", lambda e: on_ok())
        dlg.bind("<Escape>", lambda e: on_cancel())
        self._center_dialog(dlg)

    def _open_vlight_fullscreen(self):
        # sluit bestaande
        if self.vlight_active and self.vlight_win is not None:
            try: self.vlight_win.destroy()
            except Exception: pass

        self.vlight_win = tk.Toplevel(self.root)
        self.vlight_win.title("V-Light")
        self.vlight_win.configure(background="#000000")
        try: set_app_icon(self.vlight_win, "an.ico")
        except Exception: pass

        # Overrideredirect + topmost + exacte geometry over virtual screen
        if sys.platform == "win32":
            try:
                x, y, w, h = _win32_virtual_screen_rect()
                try: self.vlight_win.overrideredirect(True)
                except Exception: pass
                self.vlight_win.geometry(f"{w}x{h}+{x}+{y}")
                self.vlight_win.update_idletasks()
                try: self.vlight_win.attributes("-topmost", True)
                except Exception: pass
                # <<< harde zet tegen schermranden en boven alles >>>
                try:
                    hwnd = self.vlight_win.winfo_id()
                    _win32_force_fullscreen(hwnd, x, y, w, h)
                except Exception:
                    pass
            except Exception:
                # fallback
                try: self.vlight_win.attributes("-fullscreen", True)
                except Exception: pass
                try: self.vlight_win.attributes("-topmost", True)
                except Exception: pass
        else:
            try: self.vlight_win.attributes("-fullscreen", True)
            except Exception: pass
            try: self.vlight_win.attributes("-topmost", True)
            except Exception: pass

        # Kleurvlak edge-to-edge
        self.vlight_fill = tk.Frame(self.vlight_win, bg="#000000", bd=0, highlightthickness=0)
        self.vlight_fill.place(x=0, y=0, relwidth=1, relheight=1)

        # Sluiten met Esc of dubbelklik
        self.vlight_win.bind("<Escape>", lambda e: self._close_vlight())
        self.vlight_win.bind("<Double-Button-1>", lambda e: self._close_vlight())
        self.vlight_fill.bind("<Double-Button-1>", lambda e: self._close_vlight())

        # Focus + grab
        self.vlight_win.update_idletasks()
        try: self.vlight_win.lift()
        except Exception: pass
        try: self.vlight_win.focus_force()
        except Exception: pass
        try: self.vlight_win.grab_set()
        except Exception: pass
        self.vlight_win.after(50, lambda: self.vlight_win.focus_force())

        self.vlight_active = True
        self.vlight_dirty = True

    def _close_vlight(self):
        self.vlight_active = False
        try:
            if self.vlight_win is not None:
                try: self.vlight_win.grab_release()
                except Exception: pass
                try: self.vlight_win.attributes("-fullscreen", False)
                except Exception: pass
                try: self.vlight_win.overrideredirect(False)
                except Exception: pass
                self.vlight_win.destroy()
        except Exception:
            pass
        self.vlight_win = None
        self.vlight_fill = None
        self.vlight_dirty = False

    def _update_vlight_color(self):
        if not (self.vlight_active and self.vlight_fill and self.vlight_dirty):
            return
        start_1b = self.vlight_start
        idx = max(0, start_1b - 1)
        r = self.dmx[idx] if 0 <= idx <= 511 else 0
        g = self.dmx[idx+1] if 0 <= idx+1 <= 511 else 0
        b = self.dmx[idx+2] if 0 <= idx+2 <= 511 else 0
        color = f"#{r:02x}{g:02x}{b:02x}"
        try: self.vlight_fill.configure(bg=color)
        except Exception: pass
        self.vlight_dirty = False

    # ---- Auto-apply & reset ----
    def _reset_levels(self):
        for i in range(512): self.dmx[i] = 0
        for ch in range(512): self._update_cell_visual(ch, 0)
        self._pps_window.clear(); self.pps = 0.0
        self.vlight_dirty = True
        self._update_status()

    def _on_only_physical_changed(self):
        current_label = self.nic_var.get()
        self.nic_items = list_ipv4_interfaces(only_physical=self.only_phys_var.get())
        self.nic_box["values"] = [lbl for (lbl, ip) in self.nic_items]
        new_index = 0
        for i, (lbl, ip) in enumerate(self.nic_items):
            if lbl == current_label:
                new_index = i; break
        self.nic_box.current(new_index)
        self._on_nic_changed(None)

    def _on_nic_changed(self, event):
        idx = self.nic_box.current()
        if 0 <= idx < len(self.nic_items):
            _, ip = self.nic_items[idx]
            self._rebind_socket(ip)
            self._reset_levels()

    def _on_universe_changed(self):
        try: u = int(self.uni_var.get())
        except Exception: u = DEFAULT_UNIVERSE
        u = max(0, min(255, u))
        if u != self.accept_universe:
            self.accept_universe = u
            self._reset_levels()

    # -------- Work area ----------
    def _apply_safe_bottom_padding(self):
        extra = max(8, int(self.safe_bottom_px))
        self.wrap.pack_configure(pady=(0, PADDING + extra))
    def _on_root_configure(self, event):
        self.safe_bottom_px = get_work_area_rect_and_bottom_margin()[-1]
        self._apply_safe_bottom_padding()

    # -------- Canvas/layout ----------
    def _on_shift_wheel(self, event):
        direction = -1 if event.delta > 0 else 1
        self.canvas.xview_scroll(direction, "units")
    def _on_canvas_resize(self, event): self._render_grid()

    def _calc_sizes(self):
        vis_w = max(100, self.canvas.winfo_width())
        total_gap = (VISIBLE_COLS - 1) * COL_GAP_X
        self.col_w = (vis_w - 2*PADDING - total_gap) / VISIBLE_COLS
        if self.col_w < (LABEL_W + 60): self.col_w = LABEL_W + 60
        self.bar_w = self.col_w - LABEL_W - BAR_MARGIN
        self.content_w = (COLS * self.col_w) + (COLS - 1) * COL_GAP_X + 2*PADDING
        self.content_h = (ROWS * (BAR_H + ROW_GAP_Y)) - ROW_GAP_Y + 2*PADDING

    def _render_grid(self, initial=False):
        self._calc_sizes()
        self.canvas.delete("all"); self.items.clear()
        top_y = PADDING
        for c in range(COLS):
            col_x = PADDING + c * (self.col_w + COL_GAP_X)
            for r in range(ROWS):
                ch = r + c * ROWS
                y = top_y + r * (BAR_H + ROW_GAP_Y)
                ch_label = self.canvas.create_text(col_x, y + BAR_H/2, text=f"{ch+1:03d}",
                                                   anchor="w", fill="#bbbbbb", font=FONT)
                x_bar1 = col_x + LABEL_W; x_bar2 = x_bar1 + self.bar_w
                bg = self.canvas.create_rectangle(x_bar1, y, x_bar2, y + BAR_H, fill="#111", outline="#3a3a3a")
                fill = self.canvas.create_rectangle(x_bar1, y, x_bar1, y + BAR_H, fill="#00b400", outline="")
                val = self.dmx[ch]
                val_text = self.canvas.create_text(x_bar1 + BAR_MARGIN, y + BAR_H/2, text=str(val),
                                                   anchor="w", fill="#ffffff", font=FONT)
                self.items[ch] = (bg, fill, val_text, ch_label)
                self._update_cell_visual(ch, val, initial=True)
        self.canvas.config(scrollregion=(0, 0, self.content_w, self.content_h))

    def _update_cell_visual(self, ch: int, value: int, initial=False):
        if ch not in self.items: return
        bg, fill, val_text, _ = self.items[ch]
        v = max(0, min(255, int(value)))
        x1, y1, x2, y2 = self.canvas.coords(bg)
        new_w = x1 + (v / 255.0) * (x2 - x1)
        self.canvas.coords(fill, x1, y1, new_w, y2)
        self.canvas.itemconfig(val_text, text=str(v))
        tx, ty = self.canvas.coords(val_text)
        self.canvas.coords(val_text, x1 + BAR_MARGIN, ty)

    # -------- Networking --------
    def _start_udp_thread(self):
        self.thread = threading.Thread(target=self._udp_loop, daemon=True)
        self.thread.start()

    def _rebind_socket(self, new_ip: str):
        try:
            if self.sock: self.sock.close()
        except Exception: pass
        self.sock = None
        self.bind_ip = new_ip
        time.sleep(0.05)
        self._start_udp_thread()

    def _udp_loop(self):
        local_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try: local_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception: pass
        try: local_sock.bind((self.bind_ip, ARTNET_PORT))
        except OSError as e:
            self.queue.put(("fatal", f"Bind mislukt op {self.bind_ip}:{ARTNET_PORT}: {e}"))
            try: local_sock.close()
            except Exception: pass
            return

        self.sock = local_sock
        local_sock.settimeout(0.5)

        while self.running and self.sock is local_sock:
            try:
                data, addr = local_sock.recvfrom(2048)
            except socket.timeout:
                continue
            except OSError:
                break
            except Exception:
                traceback.print_exc(); continue

            if not data or not is_artnet_packet(data): continue
            op = parse_opcode(data)
            now = time.time()

            if op == OP_DMX:
                f = parse_artdmx_fields(data)
                if not f: continue
                subuni, net, length, seq = f["subuni"], f["net"], f["length"], f["seq"]
                if net == 0 and subuni == self.accept_universe:
                    changed = []
                    dmx_bytes = f["dmx"]
                    for i in range(min(512, len(dmx_bytes))):
                        v = dmx_bytes[i]
                        if v != self.dmx[i]:
                            self.dmx[i] = v; changed.append(i)
                    if changed:
                        self.queue.put(("dmx", changed))
                        self.vlight_dirty = True

                # PPS bijhouden
                self._pps_window.append(now)
                one_sec_ago = now - 1.0
                while self._pps_window and self._pps_window[0] < one_sec_ago:
                    self._pps_window.pop(0)
                self.pps = float(len(self._pps_window))

            elif op == OP_POLL:
                try:
                    reply = build_artpoll_reply(self.bind_ip if self.bind_ip != "0.0.0.0" else addr[0])
                    local_sock.sendto(reply, addr)
                except Exception:
                    pass

        try: local_sock.close()
        except Exception: pass

    def _schedule_ui_update(self):
        self._drain_queue()
        self._update_status()
        self._update_vlight_color()
        self.root.after(UPDATE_INTERVAL_MS, self._schedule_ui_update)

    def _drain_queue(self):
        changed = set()
        try:
            while True:
                msg = self.queue.get_nowait()
                if not msg: break
                kind = msg[0]
                if kind == "dmx": changed.update(msg[1])
                elif kind == "fatal": self.status_var.set(str(msg[1]))
        except queue.Empty:
            pass
        for ch in changed:
            self._update_cell_visual(ch, self.dmx[ch])

    def _update_status(self):
        self.status_var.set(f"Luistert op {self.bind_ip}:{ARTNET_PORT}  |  PPS: {self.pps:.1f}")

    def _on_close(self):
        self.running = False
        try:
            if self.sock: self.sock.close()
        except Exception: pass
        try: self._close_vlight()
        except Exception: pass
        self.root.after(100, self.root.destroy)

# ---- bootstrap ----
def main():
    root = tk.Tk()
    try: set_app_icon(root, "an.ico")
    except Exception: pass
    try:
        style = ttk.Style()
        if "vista" in style.theme_names(): style.theme_use("vista")
        elif "clam" in style.theme_names(): style.theme_use("clam")
    except Exception:
        pass
    app = VirtualArtnetNode(root)
    root.after(80, lambda: app._on_root_configure(None))
    root.mainloop()

if __name__ == "__main__":
    main()
