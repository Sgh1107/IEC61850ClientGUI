# -*- coding: utf-8 -*-
"""数据集查看/写值标签页。"""
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, SECONDARY

from core.connection import MmsError
from core import dataset as ds_svc
from core.mms_value import parse_text_value


class DataSetTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self.members = []    # 成员引用
        self.values = []     # 当前值（Python）
        self._build()
        self.on_state_change()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        top = tb.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
        tb.Label(top, text="数据集引用:").pack(side="left")
        self.ref_var = tk.StringVar(value="")
        self.ref_combo = tb.Combobox(top, textvariable=self.ref_var, width=46)
        self.ref_combo.pack(side="left", fill="x", expand=True, padx=6)
        self.btn_read = tb.Button(top, text="📖 读取数据集", bootstyle=PRIMARY, command=self.on_read)
        self.btn_read.pack(side="left")

        self.info_var = tk.StringVar()
        tb.Label(self, textvariable=self.info_var, bootstyle=SECONDARY).grid(
            row=1, column=0, sticky="w")

        # 成员表格
        cols = ("idx", "ref", "value")
        frame = tb.Labelframe(self, text=" 成员（选中行后可在下方修改值） ", padding=6)
        frame.grid(row=2, column=0, sticky="nsew", pady=(4, 6))
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)
        self.table = tb.Treeview(frame, columns=cols, show="headings", bootstyle=PRIMARY)
        self.table.heading("idx", text="#")
        self.table.heading("ref", text="成员引用")
        self.table.heading("value", text="当前值")
        self.table.column("idx", width=40, anchor="e", stretch=False)
        self.table.column("ref", width=380)
        self.table.column("value", width=220)
        vsb = tb.Scrollbar(frame, orient="vertical", command=self.table.yview, bootstyle="round")
        self.table.configure(yscrollcommand=vsb.set)
        self.table.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        bottom = tb.Frame(self)
        bottom.grid(row=3, column=0, sticky="ew", pady=(0, 4))
        tb.Label(bottom, text="新值:").pack(side="left")
        self.value_var = tk.StringVar()
        tb.Entry(bottom, textvariable=self.value_var, width=24).pack(side="left", padx=6)
        self.btn_write = tb.Button(bottom, text="✏ 写入选中成员", bootstyle=SUCCESS,
                                   command=self.on_write, state="disabled")
        self.btn_write.pack(side="left", padx=(0, 8))
        self.btn_write_all = tb.Button(bottom, text="⬇ 写入全部（用逗号分隔的值）",
                                       bootstyle=SUCCESS + "-outline",
                                       command=self.on_write_all, state="disabled")
        self.btn_write_all.pack(side="left")

    # ------------------------------------------------------------------
    def on_connected(self):
        self.on_state_change()

    def load_model(self, done=None):
        """扫描全模型数据集引用填充下拉框（app 链式调用）"""
        if not self.app.connected():
            if done:
                done()
            return
        client = self.app.client
        self.app.run_async(lambda: client.get_all_datasets(),
                           ok=lambda refs: (self._fill_refs(refs), done and done()),
                           done_msg="已扫描数据集列表")

    def _fill_refs(self, refs):
        self.ref_combo.configure(values=refs)
        if refs:
            self.ref_var.set(refs[0])
        self.app.set_status("发现 %d 个数据集" % len(refs) if refs else "未发现数据集")

    def on_disconnecting(self):
        self.members, self.values = [], []
        for iid in self.table.get_children(""):
            self.table.delete(iid)

    def on_state_change(self):
        state = "normal" if self.app.connected() else "disabled"
        self.btn_read.configure(state=state)

    def on_read(self):
        ref = self.ref_var.get().strip()
        if not ref:
            self.app.set_status("请输入数据集引用", is_error=True)
            return
        client = self.app.client

        def work():
            with ds_svc.DataSet(client, ref) as d:
                return (ds_svc.get_members(client, ref), d.values, d.texts)

        self.app.run_async(work, ok=lambda r: self._fill(ref, r),
                           done_msg="读取数据集成功：%s" % ref)

    def _fill(self, ref, result):
        members, values, texts = result
        self.members, self.values = members, values
        for iid in self.table.get_children(""):
            self.table.delete(iid)
        for i, (m, t) in enumerate(zip(members, texts)):
            self.table.insert("", "end", values=(i + 1, m, t))
        self.info_var.set("数据集 %s：共 %d 个成员" % (ref, len(members)))
        for b in (self.btn_write, self.btn_write_all):
            b.configure(state="normal")

    def on_write(self):
        sel = self.table.selection()
        if not sel:
            self.app.set_status("请先在表格中选择要写的成员", is_error=True)
            return
        idx = int(self.table.item(sel[0], "values")[0]) - 1
        text = self.value_var.get().strip()
        if not text:
            self.app.set_status("请输入新值", is_error=True)
            return
        values = list(self.values)
        values[idx] = parse_text_value(text)
        self._write(self.ref_var.get().strip(), values, "写入成员 #%d 成功" % (idx + 1))

    def on_write_all(self):
        text = self.value_var.get().strip()
        if not text:
            self.app.set_status("请在“新值”框输入逗号分隔的值列表", is_error=True)
            return
        values = [parse_text_value(x) for x in text.split(",")]
        if len(values) != len(self.values):
            self.app.set_status("值的数量(%d)与数据集成员数(%d)不一致"
                                % (len(values), len(self.values)), is_error=True)
            return
        self._write(self.ref_var.get().strip(), values, "写入全部成员成功")

    def _write(self, ref, values, msg):
        client = self.app.client
        self.app.run_async(lambda: ds_svc.write_values(client, ref, values),
                           ok=lambda _: self.on_read(), done_msg=msg)
