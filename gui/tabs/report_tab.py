# -*- coding: utf-8 -*-
"""报告(RCB)订阅标签页。"""
import time
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, DANGER, SUCCESS, SECONDARY

from core import ffi
from core.reports import ReportSubscription


class ReportTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self.subscriptions = []   # 当前订阅
        self._build()
        self.on_state_change()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ---------- 扫描/选择 RCB ----------
        scan = tb.Labelframe(self, text=" 1. 选择报告控制块(RCB)（连接后自动扫描） ", padding=8)
        scan.grid(row=0, column=0, sticky="ew")
        scan.columnconfigure(1, weight=1)

        tb.Label(scan, text="RCB 引用:").grid(row=0, column=0, sticky="w")
        self.ref_var = tk.StringVar(value="")
        self.ref_combo = tb.Combobox(scan, textvariable=self.ref_var, width=52)
        self.ref_combo.grid(row=1, column=0, sticky="ew", pady=(2, 6))
        self.btn_scan = tb.Button(scan, text="⟳ 重新扫描", bootstyle=SECONDARY + "-outline",
                                  command=self.load_model)
        self.btn_scan.grid(row=1, column=1, padx=(8, 0), pady=(2, 6))

        btn_col = tb.Frame(scan)
        btn_col.grid(row=2, column=0, sticky="w", pady=(2, 0))
        self.btn_sub = tb.Button(btn_col, text="📡 订阅", bootstyle=SUCCESS,
                                 command=self.on_subscribe)
        self.btn_sub.pack(side="left", padx=(0, 8))
        self.btn_unsub = tb.Button(btn_col, text="取消所有订阅",
                                   bootstyle=SECONDARY + "-outline",
                                   command=self.on_unsubscribe)
        self.btn_unsub.pack(side="left")

        # ---------- 订阅参数 ----------
        opt = tb.Labelframe(self, text=" 2. 订阅参数（触发条件） ", padding=8)
        opt.grid(row=1, column=0, sticky="ew", pady=(8, 0))
        self.trg_changed = tk.BooleanVar(value=True)
        self.trg_quality = tk.BooleanVar(value=True)
        self.trg_update = tk.BooleanVar(value=False)
        self.trg_integrity = tk.BooleanVar(value=True)
        tb.Checkbutton(opt, text="数据变化", variable=self.trg_changed,
                       bootstyle="success-round-toggle").pack(side="left", padx=(0, 10))
        tb.Checkbutton(opt, text="品质变化", variable=self.trg_quality,
                       bootstyle="success-round-toggle").pack(side="left", padx=(0, 10))
        tb.Checkbutton(opt, text="数据更新", variable=self.trg_update,
                       bootstyle="success-round-toggle").pack(side="left", padx=(0, 10))
        tb.Checkbutton(opt, text="完整性", variable=self.trg_integrity,
                       bootstyle="success-round-toggle").pack(side="left", padx=(0, 14))
        tb.Label(opt, text="IntgPd(ms):").pack(side="left")
        self.intg_var = tk.StringVar(value="5000")
        tb.Entry(opt, textvariable=self.intg_var, width=8).pack(side="left", padx=(4, 14))
        self.btn_gi = tb.Button(opt, text="📣 总召(GI)", bootstyle=SECONDARY + "-outline",
                                command=self.on_gi)
        self.btn_gi.pack(side="left")

        # ---------- 报告事件表 ----------
        evf = tb.Labelframe(self, text=" 3. 报告事件（实时） ", padding=6)
        evf.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        evf.columnconfigure(0, weight=1)
        evf.rowconfigure(0, weight=1)
        cols = ("time", "seq", "reasons", "value")
        self.events = tb.Treeview(evf, columns=cols, show="headings", bootstyle=PRIMARY)
        self.events.heading("time", text="时间", anchor="w")
        self.events.heading("seq", text="序号", anchor="w")
        self.events.heading("reasons", text="原因", anchor="w")
        self.events.heading("value", text="数据值", anchor="w")
        self.events.column("time", width=260, minwidth=260, anchor="w", stretch=False)
        self.events.column("seq", width=110, minwidth=110, anchor="w", stretch=False)
        self.events.column("reasons", width=500, minwidth=400, anchor="w", stretch=False)
        self.events.column("value", width=1000, minwidth=700, anchor="w", stretch=True)
        vsb = tb.Scrollbar(evf, orient="vertical", command=self.events.yview, bootstyle="round")
        self.events.configure(yscrollcommand=vsb.set)
        self.events.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

    
    # ------------------------------------------------------------------
    def on_connected(self):
        self.on_state_change()

    def load_model(self, done=None):
        """扫描全部 RCB 引用填充下拉框（app 链式调用）"""
        if not self.app.connected():
            if done:
                done()
            return
        client = self.app.client

        def work():
            return client.get_all_rcbs()

        def ok(rcbs):
            self.ref_combo.configure(values=rcbs)
            if rcbs:
                self.ref_var.set(rcbs[0])
            self.app.set_status("发现 %d 个 RCB" % len(rcbs) if rcbs else "未发现 RCB")
            self._update_sub_btn()
            if done:
                done()

        self.app.run_async(work, ok=ok,
                           err=lambda _e: done and done(),
                           done_msg="已扫描 RCB 列表")

    def on_disconnecting(self):
        self._unsubscribe_all()

    def on_state_change(self):
        state = "normal" if self.app.connected() else "disabled"
        self.btn_scan.configure(state=state)
        self._update_sub_btn()

    def _update_sub_btn(self):
        has_ref = bool(self.ref_var.get().strip())
        self.btn_sub.configure(state="normal" if (self.app.connected() and has_ref) else "disabled")
        self.btn_unsub.configure(state="normal" if self.subscriptions else "disabled")
        self.btn_gi.configure(state="normal" if self.subscriptions else "disabled")

    # ---- 订阅 ----
    def on_subscribe(self):
        rcb_ref = self.ref_var.get().strip()
        if not rcb_ref:
            self.app.set_status("请先选择 RCB 引用", is_error=True)
            return
        client = self.app.client

        def work():
            sub = ReportSubscription(client, rcb_ref, self._on_report)
            return sub

        def ok(sub):
            self.subscriptions.append(sub)
            trg = ((1 if self.trg_changed.get() else 0) * ffi.TRG_DATA_CHANGED
                   | (1 if self.trg_quality.get() else 0) * ffi.TRG_QUALITY_CHANGED
                   | (1 if self.trg_update.get() else 0) * ffi.TRG_DATA_UPDATE
                   | (1 if self.trg_integrity.get() else 0) * ffi.TRG_INTEGRITY)
            try:
                intg = int(self.intg_var.get() or "0")
            except ValueError:
                intg = 0
            self.app.run_async(lambda: sub.enable(trg_ops=trg, intg_pd=intg, gi=True),
                               done_msg="已订阅并使能：%s" % rcb_ref)
            self._update_sub_btn()

        self.app.run_async(work, ok=ok, done_msg="读取 RCB 参数成功")

    def on_unsubscribe(self):
        self._unsubscribe_all()
        self._update_sub_btn()
        self.app.set_status("已停止所有报告订阅")

    def _unsubscribe_all(self):
        for sub in self.subscriptions:
            try:
                sub.disable()
                sub.destroy()
            except Exception:  # noqa: BLE001
                pass
        self.subscriptions = []

    def on_gi(self):
        for sub in self.subscriptions:
            self.app.run_async(lambda s=sub: s.trigger_gi(), done_msg="已发送总召")

    # ---- 报告回调（库后台线程 -> 队列 -> 主线程） ----
    def _on_report(self, info):
        # 注意：此回调在库线程执行，只做入队
        self.app._post(self._show_report, info)

    def _show_report(self, info):
        ts = time.strftime("%H:%M:%S", time.localtime(info["ts"] / 1000.0)) if info["ts"] else "-"
        reasons = ",".join(info["reasons"]) if info["reasons"] else ""
        values = " | ".join(info["texts"]) if info["texts"] else ""
        self.events.insert("", 0, values=(ts, info["seq"], reasons, values))
        # 限制条数
        children = self.events.get_children()
        if len(children) > 300:
            for iid in children[300:]:
                self.events.delete(iid)
