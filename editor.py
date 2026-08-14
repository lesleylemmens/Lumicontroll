# editor.py
import copy
import math
import tkinter as tk
from tkinter import messagebox

_st = None  # global editor state

def _dmx():
    return int(_st["dmx_channels"])

def is_editor_open() -> bool:
    w = _st and _st.get("editor_win")
    try:
        return bool(w and w.winfo_exists())
    except Exception:
        return False

def init_editor(cfg: dict):
    """cfg expects:
       - root, icon_file, dmx_channels, BANK_SIZE
       - borderless_fill_workarea(win)
       - ensure_len_128(ch)
       - get_blocks(), get_scenes(), get_scene_to_block(), get_scene_to_local()
       - set_editor_preview_frame(frame), clear_editor_preview_frame()
       - get_preview_on(), set_preview_on(bool)
       - rebuild_flat_from_inline(), save_scenes(), update_gui(), delete_scene_cb(flat_idx)
    """
    global _st
    _st = dict(cfg)
    _st["editor_win"] = None

def _set_window_icon(win):
    try:
        icon = _st.get("icon_file")
        if icon:
            try:
                win.iconbitmap(default=icon)
            except Exception:
                win.iconbitmap(icon)
    except Exception:
        pass

def _ask_text(title, prompt, initialvalue="", parent=None):
    parent = parent or _st["root"]
    win = tk.Toplevel(parent)
    win.title(title)
    _set_window_icon(win)
    win.resizable(False, False)
    win.transient(parent); win.grab_set()
    frm = tk.Frame(win, padx=16, pady=16); frm.pack(fill="both", expand=True)
    tk.Label(frm, text=prompt, anchor="w").pack(fill="x", pady=(0, 8))
    var = tk.StringVar(value=str(initialvalue or ""))
    ent = tk.Entry(frm, textvariable=var, width=32); ent.pack(fill="x", pady=(0, 10))
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
    win.after(10, lambda: (ent.focus_set(), ent.selection_range(0, "end")))
    win.wait_window()
    return result["value"]

def _text_color_for_bg(bg):
    if not isinstance(bg, str) or not bg.startswith("#") or len(bg) != 7:
        return "black"
    try:
        r = int(bg[1:3], 16); g = int(bg[3:5], 16); b = int(bg[5:7], 16)
        return "white" if ((r * 299 + g * 587 + b * 114) / 1000) < 128 else "black"
    except Exception:
        return "black"

def _get_flat_maps():
    return (_st["get_blocks"](),
            _st["get_scenes"](),
            _st["get_scene_to_block"](),
            _st["get_scene_to_local"]())

def _get_ch_by_flat(flat_idx):
    blocks, scenes, s2b, s2l = _get_flat_maps()
    if not (0 <= flat_idx < len(scenes)):
        return None, None, None
    bi = s2b[flat_idx]
    ci = s2l[flat_idx]
    ch = blocks[bi]["chases"][ci]
    ch = _st["ensure_len_128"](ch)
    blocks[bi]["chases"][ci] = ch
    return bi, ci, ch

def _write_through_and_save(scene_flat_idx, ch6, rebuild=True):
    """Write the mutated chase back, optionally rebuild the flat maps,
    then save scenes to disk to avoid 'resurrected' steps."""
    blocks, _, s2b, s2l = _get_flat_maps()
    bi = s2b[scene_flat_idx]
    ci = s2l[scene_flat_idx]
    blocks[bi]["chases"][ci] = ch6
    if rebuild:
        _st["rebuild_flat_from_inline"]()
    _st["save_scenes"]()

def open_scene_editor(flat_scene_index: int):
    # close an existing editor window first
    if is_editor_open():
        try: _st["editor_win"].destroy()
        except Exception: pass
        _st["editor_win"] = None

    res = _get_ch_by_flat(flat_scene_index)
    if res == (None, None, None): return
    _, _, ch = res
    original_ch = copy.deepcopy(ch)

    root = _st["root"]
    win = tk.Toplevel(root)
    _st["editor_win"] = win
    win.title(f"LumiControLL — Edit: {ch.get('name','Chase')}")
    try:
        if _st.get("icon_file"):
            try:
                win.iconbitmap(default=_st["icon_file"])
            except Exception:
                win.iconbitmap(_st["icon_file"])
    except Exception: pass
    try:
        _st["borderless_fill_workarea"](win)  # fullscreen borderless
    except Exception: pass

    # local state
    st = {
        "scene_index": flat_scene_index,
        "original_ch": original_ch,
        "bank_idx": 0,
        "BANK_SIZE": int(_st["BANK_SIZE"]),
        "slider_vars": [],
        "slider_widgets": [],
        "layout_job": None,
        "last_cols": -1,
        "row_h_cache": None,
        "preview_var": tk.BooleanVar(value=bool(_st["get_preview_on"]())),
        "selected_step": 0,
    }

    # layout
    paned = tk.PanedWindow(win, orient="horizontal"); paned.pack(fill="both", expand=True)
    left = tk.Frame(paned, padx=8, pady=8);  paned.add(left, stretch="always")
    right= tk.Frame(paned, padx=8, pady=8);  paned.add(right)
    right.grid_columnconfigure(0, weight=1); right.grid_rowconfigure(1, weight=1)

    # left
    name_entry = tk.Entry(left)
    name_entry.insert(0, ch.get("name", "Chase"))
    name_entry.pack(fill="x", pady=(0, 6))

    bank_bar = tk.Frame(left); bank_bar.pack(fill="x", pady=(0, 6))
    total_banks = max(1, math.ceil(_dmx() / st["BANK_SIZE"]))
    btn_prev = tk.Button(bank_bar, text="◀", width=3)
    bank_label = tk.Label(bank_bar, text="", anchor="w")
    btn_next = tk.Button(bank_bar, text="▶", width=3)
    btn_prev.pack(side="left"); bank_label.pack(side="left", padx=8); btn_next.pack(side="left")

    ctl = tk.Frame(bank_bar); ctl.pack(side="right")
    cb_preview = tk.Checkbutton(ctl, text="Preview to DMX", variable=st["preview_var"],
                                command=lambda: _apply_preview_flag(st))
    cb_preview.pack(side="left", padx=(8, 4))

    sliders_frame = tk.Frame(left); sliders_frame.pack(fill="both", expand=True)

    # right – steps
    tk.Label(right, text="Steps", font=("TkDefaultFont", 11, "bold")).grid(row=0, column=0, sticky="w")
    list_wrap = tk.Frame(right); list_wrap.grid(row=1, column=0, sticky="nsew", pady=(2, 6))
    steps_list = tk.Listbox(list_wrap, exportselection=False)
    sc = tk.Scrollbar(list_wrap, orient="vertical", command=steps_list.yview)
    steps_list.configure(yscrollcommand=sc.set)
    steps_list.pack(side="left", fill="both", expand=True); sc.pack(side="right", fill="y")

    # timing
    timing = tk.LabelFrame(right, text="Timing"); timing.grid(row=2, column=0, sticky="ew", pady=(0,6))
    timing_mode = tk.StringVar(value=ch.get("timing_mode", "duration"))
    tk.Radiobutton(timing, text="Use durations", variable=timing_mode, value="duration",
                   command=lambda: _sync_inputs(timing_mode, durrow, cb_repeat)).pack(anchor="w")
    tk.Radiobutton(timing, text="Sync to BPM", variable=timing_mode, value="bpm",
                   command=lambda: _sync_inputs(timing_mode, durrow, cb_repeat)).pack(anchor="w")
    tk.Radiobutton(timing, text="Trigger by SOUND", variable=timing_mode, value="sound",
                   command=lambda: _sync_inputs(timing_mode, durrow, cb_repeat)).pack(anchor="w")

    # duration
    durrow = tk.Frame(right); durrow.grid(row=3, column=0, sticky="ew")
    tk.Label(durrow, text="Duration (ms)").pack(side="left")
    dur_var = tk.IntVar(value=ch.get("steps", [{}])[0].get("duration_ms", 500))
    tk.Entry(durrow, textvariable=dur_var, width=8).pack(side="left", padx=(6, 0))

    # fade
    fade_var = tk.BooleanVar(value=bool(ch.get("fade", False)))
    cb_fade = tk.Checkbutton(timing, text="Fade (duration-mode)", variable=fade_var)
    cb_fade.pack(anchor="w", pady=(4, 0))
    repeat_var = tk.BooleanVar(value=bool(ch.get("repeat", True)))
    cb_repeat = tk.Checkbutton(timing, text="Repeat", variable=repeat_var)
    cb_repeat.pack(anchor="w")

    # buttons
    btns = tk.Frame(right); btns.grid(row=4, column=0, sticky="ew", pady=(8, 0))
    for i in range(2): btns.grid_columnconfigure(i, weight=1)

    # helpers

    def _apply_preview_flag(st_):
        _st["set_preview_on"](bool(st_["preview_var"].get()))
        _update_editor_preview(st_)

    def _select_and_focus(idx: int):
        try:
            steps_list.select_clear(0, "end"); steps_list.select_set(idx); steps_list.see(idx)
        except Exception: pass
        st["selected_step"] = idx
        _load_bank_into_ui(st)
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        try:
            dur_var.set(int(ch6["steps"][idx].get("duration_ms", 500)))
        except Exception:
            pass
        _update_editor_preview(st)

    def _get_list_selected_index(lb: tk.Listbox):
        sel = lb.curselection()
        return (sel[0] if sel else None)

    def _ensure_base_values_from_first_step(ch6: dict):
        try:
            if ch6.get("steps"):
                ch6["values"] = ch6["steps"][0]["values"][:]
        except Exception:
            pass

    def _add_step():
        _save_current_bank_values(st, st["selected_step"])
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        new_name = f"Step {len(ch6['steps'])+1}"
        ch6["steps"].append({"name": new_name, "values": [0]*_dmx(), "duration_ms": 500})
        steps_list.insert("end", new_name)
        _ensure_base_values_from_first_step(ch6)
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        _select_and_focus(len(ch6["steps"]) - 1)

    def _dup_step():
        cur = st["selected_step"]
        if cur is None: return
        _save_current_bank_values(st, cur)
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        src = ch6["steps"][cur]
        ch6["steps"].insert(cur + 1, {
            "name": f"{src.get('name','Step')} copy",
            "values": src["values"][:],
            "duration_ms": int(src.get("duration_ms", 500))
        })
        steps_list.insert(cur + 1, ch6["steps"][cur + 1]["name"])
        _ensure_base_values_from_first_step(ch6)
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        _select_and_focus(cur + 1)

    def _del_step():
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        if len(ch6["steps"]) <= 1:
            messagebox.showwarning("Steps", "At least one step is required."); return
        cur = st["selected_step"]
        if cur is None: return
        _save_current_bank_values(st, cur)
        del ch6["steps"][cur]
        steps_list.delete(cur)
        new_idx = min(cur, max(0, len(ch6["steps"]) - 1))
        _ensure_base_values_from_first_step(ch6)
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        if steps_list.size() > 0:
            _select_and_focus(new_idx)
        else:
            st["selected_step"] = 0
            _load_bank_into_ui(st)
            _update_editor_preview(st)

    def _mv_up():
        cur = st["selected_step"]
        if cur is None or cur == 0: return
        _save_current_bank_values(st, cur)
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        ch6["steps"][cur - 1], ch6["steps"][cur] = ch6["steps"][cur], ch6["steps"][cur - 1]
        txt = steps_list.get(cur); steps_list.delete(cur); steps_list.insert(cur - 1, txt)
        _ensure_base_values_from_first_step(ch6)
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        _select_and_focus(cur - 1)

    def _mv_dn():
        cur = st["selected_step"]
        if cur is None: return
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        if cur >= len(ch6["steps"]) - 1: return
        _save_current_bank_values(st, cur)
        ch6["steps"][cur + 1], ch6["steps"][cur] = ch6["steps"][cur], ch6["steps"][cur + 1]
        txt = steps_list.get(cur); steps_list.delete(cur); steps_list.insert(cur + 1, txt)
        _ensure_base_values_from_first_step(ch6)
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        _select_and_focus(cur + 1)

    tk.Button(btns, text="Add",       command=_add_step, bg="#2d89ef", fg="white").grid(row=0, column=0, sticky="ew", padx=2, pady=2)
    tk.Button(btns, text="Duplicate", command=_dup_step, bg="#8750a1", fg="white").grid(row=0, column=1, sticky="ew", padx=2, pady=2)
    tk.Button(btns, text="Delete",    command=_del_step, bg="#e81123", fg="white").grid(row=1, column=0, sticky="ew", padx=2, pady=2)
    tk.Button(btns, text="Up",        command=_mv_up,    bg="#767676", fg="white").grid(row=1, column=1, sticky="ew", padx=2, pady=2)
    tk.Button(btns, text="Down",      command=_mv_dn,    bg="#767676", fg="white").grid(row=2, column=1, sticky="ew", padx=2, pady=2)

    # populate list
    steps_list.delete(0, "end")
    for s in ch["steps"]:
        steps_list.insert("end", s.get("name", "Step"))

    # initial selection
    st["selected_step"] = 0
    if steps_list.size() > 0:
        _select_and_focus(0)

    # list selection handler (save old, load new)
    def _on_list_select(_e=None):
        prev = st.get("selected_step", 0)
        new  = _get_list_selected_index(steps_list)
        if new is None: return
        _save_current_bank_values(st, prev)
        st["selected_step"] = new
        _load_bank_into_ui(st)
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        try:
            dur_var.set(int(ch6["steps"][new].get("duration_ms", 500)))
        except Exception:
            pass
        _update_editor_preview(st)

    steps_list.bind("<<ListboxSelect>>", _on_list_select)

    # rename on right-click
    def _rename_step_event(e):
        sel = steps_list.nearest(e.y)
        if sel < 0 or sel >= steps_list.size(): return
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        current = ch6["steps"][sel].get("name", f"Step {sel+1}")
        new_name = _ask_text("Rename step", "New name:", initialvalue=current, parent=win)
        if new_name and new_name.strip():
            ch6["steps"][sel]["name"] = new_name.strip()
            steps_list.delete(sel); steps_list.insert(sel, new_name.strip())
            steps_list.select_clear(0, "end"); steps_list.select_set(sel); steps_list.see(sel)
            st["selected_step"] = sel
            _write_through_and_save(st["scene_index"], ch6, rebuild=False)

    steps_list.bind("<Button-3>", _rename_step_event)

    # duration change
    def _on_dur_change(*_):
        cur = st.get("selected_step", 0)
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        try:
            ch6["steps"][cur]["duration_ms"] = int(dur_var.get())
        except Exception:
            pass
        _write_through_and_save(st["scene_index"], ch6, rebuild=False)

    try: dur_var.trace_add("write", _on_dur_change)
    except Exception:
        try: dur_var.trace("w", _on_dur_change)
        except Exception: pass

    # timing enable/disable
    _sync_inputs(timing_mode, durrow, cb_repeat)
    try: timing_mode.trace_add("write", lambda *a: _sync_inputs(timing_mode, durrow, cb_repeat))
    except Exception:
        try: timing_mode.trace("w", lambda *a: _sync_inputs(timing_mode, durrow, cb_repeat))
        except Exception: pass

    # slider layout
    def _measure_row_h():
        if st["row_h_cache"] is not None: return st["row_h_cache"]
        probe = tk.Frame(sliders_frame)
        tk.Label(probe, text="Ch 000", width=6, anchor="w").pack(side="left")
        tk.Scale(probe, from_=0, to=255, orient="horizontal", showvalue=True, length=200).pack(side="right")
        probe.pack()
        try:
            probe.update_idletasks(); h = max(1, probe.winfo_height())
        except Exception:
            h = 32
        try: probe.destroy()
        except Exception: pass
        st["row_h_cache"] = h + 6
        return st["row_h_cache"]

    def _bank_range():
        start = st["bank_idx"] * st["BANK_SIZE"]
        end   = min(_dmx(), start + st["BANK_SIZE"])
        return start, end, end - start

    def _update_bank_label():
        start, end, _ = _bank_range()
        bank_label.config(text=f"Bank {st['bank_idx']+1}/{total_banks}  (Ch {start+1:03d}–{end:03d})")

    def _compute_cols():
        try: left.update_idletasks()
        except Exception: pass
        lw = left.winfo_width() if left.winfo_exists() else 800
        neh = name_entry.winfo_height() if name_entry.winfo_exists() else 24
        avail_h = max(150, (left.winfo_height() or 600) - neh - 24 - bank_bar.winfo_height())
        rh = _measure_row_h()
        _, _, count = _bank_range()

        MIN_COL_W, GAP = 100, 12
        max_cols_w = 1
        for n in range(1, 16):
            req_w = n * MIN_COL_W + (n + 1) * GAP
            if req_w <= lw: max_cols_w = n
            else: break

        min_cols_h = max(1, math.ceil((count * rh) / max(1, avail_h)))
        cols = max(1, min(max_cols_w, min_cols_h))
        while cols < max_cols_w:
            rows = math.ceil(count / cols)
            if rows * rh <= avail_h: break
            cols += 1
        cols = max(1, min(cols, max_cols_w))
        return cols, lw

    def _layout_sliders():
        cols, avail_w = _compute_cols()
        if cols == st["last_cols"]:
            MIN_COL_W, GAP = 100, 12
            col_w = max(MIN_COL_W, int((avail_w - (cols + 1) * GAP) / cols))
            for s in st["slider_widgets"]:
                try: s.config(length=col_w)
                except Exception: pass
            _update_bank_label()
            return

        for w in list(sliders_frame.winfo_children()):
            try: w.destroy()
            except Exception: pass
        st["slider_vars"].clear(); st["slider_widgets"].clear()

        MIN_COL_W, GAP = 100, 12
        col_w = max(MIN_COL_W, int((avail_w - (cols + 1) * GAP) / cols))
        start, end, count = _bank_range()
        rows = (count + cols - 1) // cols

        idx = 0
        for c in range(cols):
            for r in range(rows):
                if idx >= count: break
                rowf = tk.Frame(sliders_frame)
                rowf.grid(row=r, column=c, sticky="ew", padx=6, pady=2)
                tk.Label(rowf, text=f"Ch {start+idx+1:03d}", width=6, anchor="w").pack(side="left")
                v = tk.IntVar(value=0)
                s = tk.Scale(rowf, from_=0, to=255, orient="horizontal", showvalue=True,
                             length=col_w, variable=v,
                             command=lambda *_: _update_editor_preview(st))
                s.pack(side="right")
                st["slider_vars"].append(v); st["slider_widgets"].append(s)
                idx += 1

        try:
            cols_now = min(cols, sliders_frame.grid_size()[0] or cols)
            for c2 in range(cols_now):
                sliders_frame.grid_columnconfigure(c2, weight=1)
        except Exception: pass

        st["last_cols"] = cols
        _update_bank_label()
        _load_bank_into_ui(st)
        _update_editor_preview(st)

    def _request_layout(_e=None):
        if st["layout_job"] is not None:
            try: win.after_cancel(st["layout_job"])
            except Exception: pass
        st["layout_job"] = win.after(60, _layout_sliders)

    win.bind("<Configure>", _request_layout)
    win.after(80, _layout_sliders)

    def _go_prev_bank():
        _save_current_bank_values(st, st["selected_step"])
        st["bank_idx"] = (st["bank_idx"] - 1) % total_banks
        st["last_cols"] = -1
        _request_layout()
        win.after(90, lambda: (_load_bank_into_ui(st), _update_editor_preview(st)))

    def _go_next_bank():
        _save_current_bank_values(st, st["selected_step"])
        st["bank_idx"] = (st["bank_idx"] + 1) % total_banks
        st["last_cols"] = -1
        _request_layout()
        win.after(90, lambda: (_load_bank_into_ui(st), _update_editor_preview(st)))

    btn_prev.config(command=_go_prev_bank)
    btn_next.config(command=_go_next_bank)
    win.bind("<Left>",  lambda e: _go_prev_bank())
    win.bind("<Right>", lambda e: _go_next_bank())

    # bottom
    bottom = tk.Frame(win, bd=1, relief="solid"); bottom.pack(side="bottom", fill="x")
    color_values = [
        ("Default", ""),
        ("White", "#ffffff"),
        ("Gray", "#808080"),
        ("Red", "#e81123"),
        ("Orange", "#ff8c00"),
        ("Yellow", "#fff100"),
        ("Green", "#107c10"),
        ("Cyan", "#00b7c3"),
        ("Blue", "#0078d4"),
        ("Purple", "#5c2d91"),
        ("Pink", "#ff69b4"),
    ]
    color_by_label = {label: value for label, value in color_values}
    label_by_color = {value: label for label, value in color_values}
    color_var = tk.StringVar(value=label_by_color.get(ch.get("button_color", ""), "Default"))
    color_row = tk.Frame(bottom)
    color_row.pack(side="left", padx=6, pady=6)
    tk.Label(color_row, text="Button color").pack(side="left", padx=(0, 4))
    color_menu = tk.OptionMenu(color_row, color_var, *[label for label, _ in color_values])
    color_menu.pack(side="left")
    def _paint_color_menu(*_):
        color = color_by_label.get(color_var.get(), "")
        bg = color or "SystemButtonFace"
        fg = _text_color_for_bg(bg)
        try:
            color_menu.config(bg=bg, fg=fg, activebackground=bg, activeforeground=fg)
            color_menu["menu"].config(bg=bg if color else "SystemButtonFace", fg=fg)
        except Exception:
            pass
    try:
        color_var.trace_add("write", _paint_color_menu)
    except Exception:
        try: color_var.trace("w", _paint_color_menu)
        except Exception: pass
    _paint_color_menu()

    def _save_and_close():
        _save_current_bank_values(st, st["selected_step"])
        _, _, ch6 = _get_ch_by_flat(st["scene_index"])
        ch6["name"] = name_entry.get()
        ch6["timing_mode"] = timing_mode.get()
        ch6["repeat"] = bool(repeat_var.get())
        ch6["fade"] = bool(fade_var.get())
        ch6["button_color"] = color_by_label.get(color_var.get(), "")
        if ch6["steps"]:
            ch6["values"] = ch6["steps"][0]["values"][:]
        _write_through_and_save(st["scene_index"], ch6, rebuild=True)
        _st["update_gui"]()
        _cleanup_and_close(win)

    def _cancel_and_close():
        blocks, _, s2b, s2l = _get_flat_maps()
        flat_idx = st["scene_index"]
        if 0 <= flat_idx < len(s2b):
            try:
                blocks[s2b[flat_idx]]["chases"][s2l[flat_idx]] = copy.deepcopy(st["original_ch"])
                _st["rebuild_flat_from_inline"]()
                _st["save_scenes"]()
                _st["update_gui"]()
            except Exception:
                pass
        _cleanup_and_close(win)

    def _delete_scene_and_close():
        flat_idx = st["scene_index"]
        _cleanup_and_close(win)
        _st["delete_scene_cb"](flat_idx)

    tk.Button(bottom, text="Delete Scene", command=_delete_scene_and_close,
              bg="#e81123", fg="white").pack(side="left", padx=6, pady=6)
    tk.Button(bottom, text="Cancel", command=_cancel_and_close,
              bg="#767676", fg="white").pack(side="right", padx=6, pady=6)
    tk.Button(bottom, text="Save", command=_save_and_close,
              bg="#107c10", fg="white").pack(side="right", padx=6, pady=6)
    win.bind("<Return>", lambda e: _save_and_close())
    win.bind("<Escape>", lambda e: _cancel_and_close())
    win.protocol("WM_DELETE_WINDOW", _cancel_and_close)
    win.focus_force()

# ---------- helpers ----------

def _cleanup_and_close(win):
    try:
        _st["set_preview_on"](False)
        _st["clear_editor_preview_frame"]()
    except Exception: pass
    try:
        if win and win.winfo_exists():
            win.destroy()
    finally:
        _st["editor_win"] = None

def _save_current_bank_values(st, step_idx: int):
    if step_idx is None: return
    res = _get_ch_by_flat(st["scene_index"])
    if res == (None, None, None): return
    _, _, ch6 = res
    if not (0 <= step_idx < len(ch6["steps"])): return
    start, end, count = _bank_range_static(st)
    vals = ch6["steps"][step_idx]["values"][:]
    for i in range(count):
        try: vals[start + i] = int(st["slider_vars"][i].get())
        except Exception: pass
    ch6["steps"][step_idx]["values"] = vals
    _write_through_and_save(st["scene_index"], ch6, rebuild=False)

def _load_bank_into_ui(st):
    res = _get_ch_by_flat(st["scene_index"])
    if res == (None, None, None): return
    _, _, ch6 = res
    idx = st.get("selected_step", 0)
    if not ch6["steps"]: return
    start, end, count = _bank_range_static(st)
    vals = ch6["steps"][idx]["values"]
    for i in range(min(count, len(st["slider_vars"]))):
        try: st["slider_vars"][i].set(int(vals[start + i]))
        except Exception: pass

def _bank_range_static(st):
    start = st["bank_idx"] * st["BANK_SIZE"]
    end   = min(_dmx(), start + st["BANK_SIZE"])
    return start, end, end - start

def _update_editor_preview(st):
    if not st["preview_var"].get():
        _st["clear_editor_preview_frame"](); return
    res = _get_ch_by_flat(st["scene_index"])
    if res == (None, None, None):
        _st["clear_editor_preview_frame"](); return
    _, _, ch6 = res
    idx = st.get("selected_step", 0)
    frame = ch6["steps"][idx]["values"][:]
    start, end, count = _bank_range_static(st)
    for i in range(min(count, len(st["slider_vars"]))):
        try: frame[start + i] = int(st["slider_vars"][i].get())
        except Exception: pass
    _st["set_editor_preview_frame"](frame)

def _sync_inputs(timing_mode: tk.StringVar, durrow, repeat_widget=None):
    mode = timing_mode.get()
    # duration only enabled in 'duration' mode
    for w in durrow.winfo_children():
        try: w.config(state=("normal" if mode == "duration" else "disabled"))
        except Exception: pass
    if repeat_widget is not None:
        try: repeat_widget.config(state=("normal" if mode == "duration" else "disabled"))
        except Exception: pass
