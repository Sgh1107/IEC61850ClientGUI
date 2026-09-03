# -*- coding: utf-8 -*-
"""控制操作标签页"""
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, DANGER, SECONDARY

from core import control


class ControlTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self._build()
        self.on_state_change()

    def _build(self):
        self.columnconfigure(0, weight=1)

        panel = tb.Labelframe(self, text=" 控制对象操作（直控 / SBO） ", padding=12)
        panel.grid(row=0, column=0, sticky="new")
        panel.columnconfigure(1, weight=1)

        tb.Label(panel, text="控制对象引用:").grid(row=0, column=0, sticky="w", pady=3)
        self.ref_var = tk.StringVar(value="")
        self.ref_combo = tb.Combobox(panel, textvariable=self.ref_var, width=44)
        self.ref_combo.grid(row=0, column=1, sticky="ew", pady=3)

        tb.Label(panel, text="控制值:").grid(row=1, column=0, sticky="w", pady=3)
        val_row = tb.Frame(panel)
        val_row.grid(row=1, column=1, sticky="ew", pady=3)
        self.value_var = tk.StringVar(value="true")
        tb.Entry(val_row, textvariable=self.value_var, width=16).pack(side="left")
        tb.Label(val_row, text="（布尔: true/false；模拟量: 数字；字符串直接输入）",
                 bootstyle=SECONDARY).pack(side="left", padx=8)

        tb.Label(panel, text="操作来源:").grid(row=2, column=0, sticky="w", pady=3)
        org_row = tb.Frame(panel)
        org_row.grid(row=2, column=1, sticky="w", pady=3)
        tb.Label(org_row, text="标识").pack(side="left")
        self.or_ident = tk.StringVar()
        tb.Entry(org_row, textvariable=self.or_ident, width=10).pack(side="left", padx=(4, 12))
        tb.Label(org_row, text="类别").pack(side="left")
        self.or_cat = tk.StringVar(value="3")
        tb.Combobox(org_row, textvariable=self.or_cat, width=8, state="readonly",
                    values=["0", "1", "2", "3", "4", "5"]).pack(side="left", padx=4)

        opt_row = tb.Frame(panel)
        opt_row.grid(row=3, column=1, sticky="w", pady=3)
        self.sbo_var = tk.BooleanVar(value=False)
        tb.Checkbutton(opt_row, text="SBO（先选择后操作）", variable=self.sbo_var,
                       bootstyle="primary-round-toggle").pack(side="left", padx=(0, 16))
        self.interlock_var = tk.BooleanVar(value=False)
        tb.Checkbutton(opt_row, text="联锁校验", variable=self.interlock_var,
                       bootstyle="primary-round-toggle").pack(side="left", padx=(0, 16))
        self.synchro_var = tk.BooleanVar(value=False)
        tb.Checkbutton(opt_row, text="同期校验", variable=self.synchro_var,
                       bootstyle="primary-round-toggle").pack(side="left")

        btn_row = tb.Frame(panel)
        btn_row.grid(row=4, column=0, columnspan=2, sticky="w", pady=(10, 0))
        self.btn_operate = tb.Button(btn_row, text="⚡ 执行操作", bootstyle=PRIMARY,
                                     command=self.on_operate)
        self.btn_operate.pack(side="left", padx=(0, 8))
        tb.Label(btn_row, text="注意：SBO 模型会自动执行 select → operate",
                 bootstyle=SECONDARY).pack(side="left")

        # 操作日志
        logf = tb.Labelframe(self, text=" 操作日志 ", padding=6)
        logf.grid(row=1, column=0, sticky="nsew", pady=(10, 0))
        self.rowconfigure(1, weight=1)
        self.log = tb.Text(logf, height=10, wrap="word", font=("Consolas", 10), state="disabled")
        vsb = tb.Scrollbar(logf, orient="vertical", command=self.log.yview, bootstyle="round")
        self.log.configure(yscrollcommand=vsb.set)
        self.log.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

    # ------------------------------------------------------------------
    def on_connected(self):
        self.on_state_change()

    def load_model(self, done=None):
        """扫描全部数据对象引用填充下拉框（app 链式调用）"""
        if not self.app.connected():
            if done:
                done()
            return
        client = self.app.client

        def work():
            return [r for r in client.get_all_data_objects()]

        def ok(refs):
            self.ref_combo.configure(values=refs)
            if refs:
                self.ref_var.set(refs[0])
            self.app.set_status("发现 %d 个数据对象" % len(refs) if refs
                                else "未发现数据对象")
            if done:
                done()

        self.app.run_async(work, ok=ok,
                           err=lambda _e: done and done(),
                           done_msg="已扫描数据对象列表")

    def on_disconnecting(self):
        pass

    def on_state_change(self):
        state = "normal" if self.app.connected() else "disabled"
        self.btn_operate.configure(state=state)

    def _log(self, text):
        self.log.configure(state="normal")
        self.log.insert("end", text + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def on_operate(self):
        ref = self.ref_var.get().strip()
        if not ref:
            self.app.set_status("请输入控制对象引用", is_error=True)
            return
        from core.mms_value import parse_text_value
        value = parse_text_value(self.value_var.get())
        client = self.app.client
        sbo = self.sbo_var.get()
        self._log("→ 操作 %s = %r%s" % (ref, value, " (SBO)" if sbo else ""))
        self.app.run_async(
            lambda: control.operate(client, ref, value, sbo=sbo,
                                    or_ident=self.or_ident.get(),
                                    or_cat=int(self.or_cat.get()),
                                    interlock_check=self.interlock_var.get(),
                                    synchro_check=self.synchro_var.get()),
            ok=lambda _: self._log("✔ 操作成功"),
            done_msg="控制操作成功",
            err=lambda e: self._log("✘ 操作失败：%s" % e))
