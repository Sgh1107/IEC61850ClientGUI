# -*- coding: utf-8 -*-
"""数据模型浏览 + 读/写标签页（重新设计版）。

布局：
    ┌─────────── 模型树 ───────────┐ ┌──── 详情面板 ────┐
    │ 服务器 → LD → LN → DO → DA  │ │ 引用 + FC        │
    │ （懒加载，点击即读）          │ │ ┌──────────────┐ │
    └──────────────────────────────┘ │ │  当前值(大字) │ │
                                     │ └──────────────┘ │
                                     │ 读 / 写          │
                                     └──────────────────┘
"""
import time
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, SECONDARY

from core import ffi
from core.connection import MmsError
from core.mms_value import parse_text_value


class DataBrowserTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self._current_ref = ""
        self._build()
        self.on_state_change()

    def _build(self):
        self.columnconfigure(0, weight=5)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(0, weight=1)

        # ================= 左：模型树卡片 =================
        left = tb.Labelframe(self, text=" 🌲 数据模型（双击展开 / 点击读取） ",
                             padding=8)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        left.columnconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)

        toolbar = tb.Frame(left)
        toolbar.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        self.btn_refresh = tb.Button(toolbar, text="⟳ 重新读取模型",
                                     bootstyle=SECONDARY + "-outline",
                                     command=self._reload, state="disabled")
        self.btn_refresh.pack(side="left")
        tb.Label(toolbar, text="点击叶子节点自动读取当前值",
                 bootstyle=SECONDARY).pack(side="right")

        tree_holder = tb.Frame(left, bootstyle=SECONDARY, padding=1)
        tree_holder.grid(row=1, column=0, sticky="nsew")

        self.tree = tb.Treeview(tree_holder, show="tree", bootstyle=PRIMARY)
        vsb = tb.Scrollbar(tree_holder, orient="vertical",
                           command=self.tree.yview, bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        self.tree.bind("<<TreeviewOpen>>", self._on_open_node)
        self.tree.bind("<<TreeviewSelect>>", self._on_select_node)

        
        # ================= 右：详情面板 =================
        right = tb.Frame(self)
        right.grid(row=0, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(3, weight=1)

        # --- 选中节点信息 ---
        info = tb.Labelframe(right, text=" 🎯 选中节点 ", padding=10)
        info.grid(row=0, column=0, sticky="ew")
        info.columnconfigure(0, weight=1)

        self.ref_var = tk.StringVar(value="（点击左侧树中的节点）")
        tb.Label(info, textvariable=self.ref_var, font=("Consolas", 11, "bold"),
                 wraplength=400, bootstyle=PRIMARY, anchor="w").grid(row=0, column=0, sticky="ew")

        fc_row = tb.Frame(info)
        fc_row.grid(row=1, column=0, sticky="ew", pady=(6, 0))
        tb.Label(fc_row, text="功能约束:").pack(side="left")
        self.fc_var = tk.StringVar(value="MX")
        self.fc_combo = tb.Combobox(fc_row, textvariable=self.fc_var, width=6,
                                    state="readonly", values=list(ffi.FC_NAMES.values()))
        self.fc_combo.pack(side="left", padx=(4, 12))
        self.btn_read = tb.Button(fc_row, text="📖 读取", bootstyle=PRIMARY,
                                  command=self.on_read)
        self.btn_read.pack(side="left")
        self.auto_read_var = tk.BooleanVar(value=True)
        tb.Checkbutton(fc_row, text="选中即读", variable=self.auto_read_var,
                       bootstyle="primary-round-toggle").pack(side="left", padx=(14, 0))

        # --- 当前值（深蓝仪表盘大字） ---
        self.value_var = tk.StringVar(value="--")
        self.value_label = tb.Label(right, textvariable=self.value_var,
                                    font=("Consolas", 26, "bold"),
                                    bootstyle="inverse-primary",
                                    anchor="w", padding=(18, 14))
        self.value_label.grid(row=1, column=0, sticky="ew", pady=(10, 0))

        # --- 写入区 ---
        write = tb.Labelframe(right, text=" ✏ 写入（true/false、数字或字符串） ", padding=10)
        write.grid(row=2, column=0, sticky="ew", pady=(10, 0))
        write.columnconfigure(0, weight=1)

        w_row = tb.Frame(write)
        w_row.grid(row=0, column=0, sticky="ew")
        self.write_var = tk.StringVar()
        tb.Entry(w_row, textvariable=self.write_var, font=("Consolas", 11)).pack(
            side="left", fill="x", expand=True, padx=(0, 8))
        self.btn_write = tb.Button(w_row, text="写入", bootstyle=SUCCESS, command=self.on_write)
        self.btn_write.pack(side="left")

        quick = tb.Frame(write)
        quick.grid(row=1, column=0, sticky="w", pady=(8, 0))
        tb.Label(quick, text="快捷值:", bootstyle=SECONDARY).pack(side="left")
        for label, val in (("true", "true"), ("false", "false"), ("0", "0"), ("1", "1")):
            tb.Button(quick, text=label, bootstyle=SECONDARY + "-outline", width=6,
                      command=lambda v=val: self.write_var.set(v)).pack(side="left", padx=(6, 0))

        # --- 读值历史 ---
        hist = tb.Labelframe(right, text=" 🕘 读值历史（最近在上） ", padding=8)
        hist.grid(row=3, column=0, sticky="nsew", pady=(10, 0))
        hist.columnconfigure(0, weight=1)
        hist.rowconfigure(0, weight=1)
        cols = ("time", "ref", "value")
        self.history = tb.Treeview(hist, columns=cols, show="headings",
                                   bootstyle=PRIMARY, height=7)
        self.history.heading("time", text="时间")
        self.history.heading("ref", text="引用")
        self.history.heading("value", text="值")
        self.history.column("time", width=80, anchor="center", stretch=False)
        self.history.column("ref", width=210)
        self.history.column("value", width=150)
        hvsb = tb.Scrollbar(hist, orient="vertical", command=self.history.yview,
                            bootstyle="round")
        self.history.configure(yscrollcommand=hvsb.set)
        self.history.grid(row=0, column=0, sticky="nsew")
        hvsb.grid(row=0, column=1, sticky="ns")

    
    # ------------------------------------------------------------------
    # 生命周期回调
    # ------------------------------------------------------------------
    def on_connected(self):
        self.on_state_change()
        self.on_connected_load()

    def on_connected_load(self):
        if not self.app.connected():
            return
        self.app.run_async(lambda: self.app.client.get_logical_devices(),
                           ok=self._fill_roots, done_msg="已读取逻辑设备列表")

    def _fill_roots(self, lds):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        for ld in lds:
            iid = self.tree.insert("", "end", text="🏠 " + ld,
                                   values=(ld, "ld"), open=False)
            self.tree.insert(iid, "end", text="…")   # 占位（懒加载）

    def on_disconnecting(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)

    def on_state_change(self):
        state = "normal" if self.app.connected() else "disabled"
        self.btn_refresh.configure(state=state)
        self.btn_read.configure(state=state)
        self.btn_write.configure(state=state)

    # ------------------------------------------------------------------
    # 树逻辑：懒加载 服务器 -> LD -> LN -> DO -> DA
    # ------------------------------------------------------------------
    def _reload(self):
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.on_connected_load()

    def _on_open_node(self, _e):
        iid = self.tree.focus()
        if not iid:
            return
        vals = self.tree.item(iid, "values")
        ref, kind = vals[0], vals[1]
        for child in self.tree.get_children(iid):
            self.tree.delete(child)
        try:
            if kind == "ld":
                for ln in self.app.client.get_logical_nodes(ref):
                    ln_ref = "%s/%s" % (ref, ln)
                    c = self.tree.insert(iid, "end", text="🔷 " + ln,
                                         values=(ln_ref, "ln"), open=False)
                    self.tree.insert(c, "end", text="…")
            elif kind == "ln":
                for do in self.app.client.get_data_objects(ref):
                    do_ref = "%s.%s" % (ref, do)
                    c = self.tree.insert(iid, "end", text="📦 " + do,
                                         values=(do_ref, "do"), open=False)
                    self.tree.insert(c, "end", text="…")
            elif kind in ("do", "da"):
                for name in self.app.client.get_data_attributes(ref, with_fc=True):
                    if "[" in name and name.endswith("]"):
                        nm, fc = name[:-1].rsplit("[", 1)
                    else:
                        nm, fc = name, ""
                    child_ref = "%s.%s" % (ref, nm)
                    label = "🔹 " + nm + (" [%s]" % fc if fc else "")
                    c = self.tree.insert(iid, "end", text=label,
                                         values=(child_ref, "da", fc), open=False)
                    self.tree.insert(c, "end", text="…")
        except MmsError as e:
            self.app.set_status("展开失败（可能为叶子节点）：%s" % e)
            self.tree.insert(iid, "end", text="· (叶子节点)")

    def _on_select_node(self, _e):
        iid = self.tree.focus()
        if not iid:
            return
        vals = self.tree.item(iid, "values")
        if len(vals) >= 2 and vals[1] == "da":
            self._current_ref = vals[0]
            self.ref_var.set(vals[0])
            if len(vals) >= 3 and vals[2]:
                self.fc_var.set(vals[2])
            if self.auto_read_var.get():
                self.on_read()
        elif len(vals) >= 2 and vals[1] == "do":
            self._current_ref = vals[0]
            self.ref_var.set(vals[0])

    # ------------------------------------------------------------------
    # 读 / 写
    # ------------------------------------------------------------------
    def on_read(self):
        ref, fc = self.ref_var.get().strip(), self.fc_var.get()
        if not ref or ref.startswith("（"):
            self.app.set_status("请先在左侧树中选择节点", is_error=True)
            return
        self.app.run_async(lambda: self.app.client.read(ref, fc),
                           ok=lambda v: self._show_read(v, ref),
                           done_msg="读取成功：%s" % ref)

    def _show_read(self, value, ref):
        text = str(value)
        self.value_var.set(text)
        # 值类型着色：布尔用醒目颜色
        color = "inverse-warning" if text in ("True", "False") else "inverse-primary"
        try:
            self.value_label.configure(bootstyle=color)
        except Exception:  # noqa: BLE001
            pass
        # 写入历史
        self.history.insert("", 0, values=(
            time.strftime("%H:%M:%S"), ref, text if len(text) < 60 else text[:57] + "…"))
        children = self.history.get_children()
        if len(children) > 100:
            for iid in children[100:]:
                self.history.delete(iid)

    def on_write(self):
        ref, fc = self.ref_var.get().strip(), self.fc_var.get()
        text = self.write_var.get()
        if not ref or ref.startswith("（") or not text:
            self.app.set_status("请选择节点并输入写入值", is_error=True)
            return
        value = parse_text_value(text)
        self.app.run_async(lambda: self.app.client.write(ref, fc, value),
                           ok=lambda _r: self.on_read(),
                           done_msg="写入成功：%s = %r" % (ref, value))
