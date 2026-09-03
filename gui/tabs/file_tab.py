# -*- coding: utf-8 -*-
"""MMS 文件服务标签页（浏览/下载/上传/删除）。"""
import os
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, DANGER, SECONDARY

from core.connection import MmsError
from core import files as filesvc


def fmt_size(n):
    if n < 1024:
        return "%d B" % n
    for unit in ("KB", "MB", "GB"):
        n /= 1024.0
        if n < 1024:
            return "%.1f %s" % (n, unit)
    return "%.1f TB" % n


def fmt_mtime(ms):
    if not ms:
        return "-"
    try:
        return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ms / 1000.0))
    except (ValueError, OverflowError):
        return "-"


class FileTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self.current_path = ""     # 当前服务器目录（"" 为根）
        self.entries = []
        self._build()
        self.on_state_change()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ---------- 工具栏 ----------
        bar = tb.Frame(self)
        bar.grid(row=0, column=0, sticky="ew", pady=(0, 6))

        self.btn_up = tb.Button(bar, text="⬅ 上级", bootstyle=SECONDARY + "-outline",
                                command=self.on_go_up, state="disabled")
        self.btn_up.pack(side="left", padx=(0, 6))
        self.btn_refresh = tb.Button(bar, text="⟳ 刷新", bootstyle=SECONDARY + "-outline",
                                     command=self.on_refresh, state="disabled")
        self.btn_refresh.pack(side="left", padx=(0, 14))

        tb.Label(bar, text="路径:").pack(side="left")
        self.path_var = tk.StringVar(value="/")
        tb.Label(bar, textvariable=self.path_var, font=("Consolas", 11, "bold"),
                 bootstyle=PRIMARY).pack(side="left", padx=(6, 0))

        # ---------- 文件表 ----------
        frame = tb.Labelframe(self, text=" 服务器文件（双击目录进入） ", padding=6)
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        cols = ("size", "mtime")
        self.tree = tb.Treeview(frame, columns=cols, show="tree headings",
                                selectmode="extended", bootstyle=PRIMARY)
        self.tree.heading("#0", text="名称", anchor="w")
        self.tree.heading("size", text="大小", anchor="e")
        self.tree.heading("mtime", text="修改时间", anchor="w")
        self.tree.column("#0", width=200, minwidth=200)
        self.tree.column("size", width=200, anchor="e", stretch=False)
        self.tree.column("mtime", width=500, anchor="w", stretch=False)
        self.tree.tag_configure("dir", font=("Microsoft YaHei UI", 10, "bold"))

        vsb = tb.Scrollbar(frame, orient="vertical", command=self.tree.yview, bootstyle="round")
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        self.tree.bind("<Double-1>", self.on_double_click)
        self.tree.bind("<Return>", self.on_double_click)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_state_change())

        # ---------- 操作栏 ----------
        act = tb.Frame(self)
        act.grid(row=2, column=0, sticky="ew", pady=(6, 0))

        self.btn_download = tb.Button(act, text="⬇ 下载…", bootstyle=PRIMARY,
                                      command=self.on_download, state="disabled")
        self.btn_download.pack(side="left", padx=(0, 8))
        self.btn_upload = tb.Button(act, text="⬆ 上传文件…", bootstyle=SUCCESS,
                                    command=self.on_upload, state="disabled")
        self.btn_upload.pack(side="left", padx=(0, 8))
        self.btn_delete = tb.Button(act, text="🗑 删除", bootstyle=DANGER + "-outline",
                                    command=self.on_delete, state="disabled")
        self.btn_delete.pack(side="left", padx=(0, 8))
        tb.Label(act, text="提示：双击目录名进入子目录；上传到当前浏览的目录",
                 bootstyle=SECONDARY).pack(side="right")

    
    # ------------------------------------------------------------------
    def on_connected(self):
        self.on_state_change()
        self.on_refresh()

    def on_disconnecting(self):
        self.current_path = ""
        self.entries = []
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        self.path_var.set("/")

    def on_state_change(self):
        connected = self.app.connected()
        self.btn_refresh.configure(state="normal" if connected else "disabled")
        self.btn_upload.configure(state="normal" if connected else "disabled")
        self.btn_up.configure(state="normal" if (connected and self.current_path) else "disabled")
        has_sel = bool(self.tree.selection()) and connected
        self.btn_download.configure(state="normal" if has_sel else "disabled")
        self.btn_delete.configure(state="normal" if has_sel else "disabled")

    # ---- 目录操作 ----
    def on_refresh(self):
        client = self.app.client
        path = self.current_path
        self.app.run_async(lambda: filesvc.list_dir(client, path),
                           ok=self._fill, done_msg="已读取目录：%s" % (path or "/"))

    def _fill(self, entries):
        self.entries = entries
        for iid in self.tree.get_children(""):
            self.tree.delete(iid)
        for e in entries:
            self.tree.insert("", "end",
                             text=("📁 " if e.get("is_dir") else "📄 ") + e["name"],
                             values=(fmt_size(e["size"]), fmt_mtime(e["mtime"])),
                             tags=("dir",) if e.get("is_dir") else ())
        self.path_var.set("/" + self.current_path)
        self.on_state_change()

    def on_go_up(self):
        if not self.current_path:
            return
        if "/" in self.current_path:
            self.current_path = self.current_path.rsplit("/", 1)[0]
        else:
            self.current_path = ""
        self.on_refresh()

    def on_double_click(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        iid = sel[0]
        name = self.tree.item(iid, "text")[2:]   # 去掉 emoji 前缀
        sub = (self.current_path + "/" + name) if self.current_path else name
        client = self.app.client

        def work():
            # 探测是否为目录：能列出即目录
            entries = filesvc.list_dir(client, sub)
            return ("dir", entries)

        def ok(result):
            kind, entries = result
            self.current_path = sub
            self._fill(entries)

        def fail(_e):
            # 列失败 → 视为文件，提示可下载
            self.app.set_status("“%s” 是文件（可选中后下载）" % name)

        self.app.run_async(work, ok=ok, err=fail, done_msg="已进入目录：%s" % sub)

    # ---- 下载 ----
    def on_download(self):
        sel = self.tree.selection()
        if not sel:
            return
        name = self.tree.item(sel[0], "text")[2:]
        remote = (self.current_path + "/" + name) if self.current_path else name
        local = filedialog.asksaveasfilename(title="保存文件", initialfile=name,
                                             parent=self)
        if not local:
            return
        client = self.app.client

        def work():
            filesvc.download(client, remote, local)
            return local

        self.app.run_async(work, done_msg="下载完成：%s → %s" % (remote, local))

    # ---- 上传 ----
    def on_upload(self):
        local = filedialog.askopenfilename(title="选择要上传的文件", parent=self)
        if not local:
            return
        remote = (self.current_path + "/" + os.path.basename(local)) \
            if self.current_path else os.path.basename(local)
        client = self.app.client

        def work():
            filesvc.upload(client, local, remote)
            return remote

        self.app.run_async(work,
                           ok=lambda _r: self.on_refresh(),
                           done_msg="上传完成：%s" % remote)

    # ---- 删除 ----
    def on_delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        names = [self.tree.item(i, "text")[2:] for i in sel]
        if not messagebox.askyesno("确认删除",
                                   "确定删除服务器上的 %d 个文件？\n%s"
                                   % (len(names), "\n".join(names)), parent=self):
            return
        client = self.app.client

        def work():
            for name in names:
                remote = (self.current_path + "/" + name) if self.current_path else name
                filesvc.delete(client, remote)

        self.app.run_async(work,
                           ok=lambda _r: self.on_refresh(),
                           done_msg="已删除 %d 个文件" % len(names))
