# -*- coding: utf-8 -*-
"""主窗口：连接栏 + 功能标签页 + 状态栏。

各标签页通过 app 对象获得共享资源：
- app.client       core.connection.Client 实例
- app.run_async()  在工作线程执行阻塞 MMS 操作
- app.set_status() 状态栏
- app.connected()  是否已连接
"""
import queue
import threading
import tkinter as tk

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SECONDARY, DANGER

from core.connection import Client

from .tabs.data_browser import DataBrowserTab
from .tabs.dataset_tab import DataSetTab
from .tabs.control_tab import ControlTab
from .tabs.report_tab import ReportTab
from .tabs.file_tab import FileTab

APP_TITLE = "IEC 61850 客户端工具 (libiec61850)"


class App(tb.Window):
    def __init__(self):
        super().__init__(themename="flatly", iconphoto='')
        self.title(APP_TITLE)
        self.geometry("1080x720")
        self.minsize(900, 560)

        self.client = None
        self.busy = False
        self.ui_queue = queue.Queue()

        self._build_ui()
        self.after(80, self._poll_queue)

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build_ui(self):
        # ---------- 顶部：深色标题栏（含连接控件） ----------
        header = tb.Frame(self, bootstyle="primary", padding=(18, 12, 18, 12))
        header.pack(fill="x")

        tb.Label(header, text="⚡ IEC 61850 客户端工具",
                 font=("Microsoft YaHei UI", 15, "bold"),
                 bootstyle="inverse-primary").pack(side="left", padx=(0, 24))

        tb.Label(header, text="服务器 IP:", bootstyle="inverse-primary").pack(side="left")
        self.host_var = tk.StringVar(value="127.0.0.1")
        tb.Entry(header, textvariable=self.host_var, width=17).pack(side="left", padx=(4, 10))

        tb.Label(header, text="端口:", bootstyle="inverse-primary").pack(side="left")
        self.port_var = tk.StringVar(value="8102")
        tb.Entry(header, textvariable=self.port_var, width=6).pack(side="left", padx=(4, 10))

        self.btn_connect = tb.Button(header, text="🔌 连接", bootstyle=PRIMARY, command=self.on_connect)
        self.btn_connect.pack(side="left", padx=(0, 6))
        self.btn_disconnect = tb.Button(header, text="断开", bootstyle="secondary-outline",
                                        command=self.on_disconnect, state="disabled")
        self.btn_disconnect.pack(side="left")

        self.conn_state = tb.Label(header, text="● 未连接", bootstyle="danger",
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.conn_state.pack(side="right")

        self.notebook = tb.Notebook(self, bootstyle=PRIMARY, padding=(6, 4))
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(10, 0))

        self.tab_data = DataBrowserTab(self)
        self.tab_dataset = DataSetTab(self)
        self.tab_control = ControlTab(self)
        self.tab_report = ReportTab(self)
        self.tab_file = FileTab(self)
        self.notebook.add(self.tab_data, text=" 📂 数据浏览 ")
        self.notebook.add(self.tab_dataset, text=" 📋 数据集 ")
        self.notebook.add(self.tab_control, text=" 🎛 控制操作 ")
        self.notebook.add(self.tab_report, text=" 📡 报告订阅 ")
        self.notebook.add(self.tab_file, text=" 🗃 文件服务 ")

        bottom = tb.Frame(self, padding=(14, 6, 14, 10))
        bottom.pack(fill="x")
        self.status_var = tk.StringVar(value="就绪")
        self.status_label = tb.Label(bottom, textvariable=self.status_var, anchor="w",
                                     padding=(12, 7), bootstyle=SECONDARY)
        self.status_label.pack(fill="x")

    
    # ------------------------------------------------------------------
    # 共享工具（供各标签页使用）
    # ------------------------------------------------------------------
    def connected(self):
        return bool(self.client and self.client.connected)

    def set_status(self, text, is_error=False):
        self.status_var.set(text)
        try:
            self.status_label.configure(bootstyle="danger" if is_error else "secondary")
        except Exception:  # noqa: BLE001
            pass

    def _post(self, fn, *args):
        self.ui_queue.put((fn, args))

    def _poll_queue(self):
        try:
            while True:
                fn, args = self.ui_queue.get_nowait()
                fn(*args)
        except queue.Empty:
            pass
        self.after(80, self._poll_queue)

    def run_thread(self, work, ok=None, err=None, done_msg=None):
        """在工作线程执行阻塞操作（work() 返回值/异常经队列回主线程）"""
        if self.busy:
            self.set_status("有操作正在进行中，请稍候…", is_error=True)
            return

        def worker():
            try:
                result = ("OK", work())
            except Exception as e:  # noqa: BLE001
                result = ("ERR", e)
            self._post(self._on_done, result, ok, err, done_msg)

        self.busy = True
        self._update_connection_ui()
        threading.Thread(target=worker, daemon=True).start()

    def _on_done(self, result, ok, err, done_msg):
        self.busy = False
        state, payload = result
        if state == "OK":
            self.set_status(done_msg or "操作完成")
            if ok:
                ok(payload)
        else:
            if err:
                err(payload)
            else:
                self.set_status("错误：%s" % payload, is_error=True)
        self._update_connection_ui()

    def run_async(self, fn, ok=None, err=None, done_msg=None):
        """要求已连接的 run_thread 封装"""
        if not self.connected():
            self.set_status("未连接到服务器", is_error=True)
            return
        self.run_thread(fn, ok=ok, err=err, done_msg=done_msg)

    # ------------------------------------------------------------------
    # 连接 / 断开
    # ------------------------------------------------------------------
    def on_connect(self):
        if self.busy:
            return
        host = self.host_var.get().strip()
        port = int(self.port_var.get().strip() or "102")
        self.set_status("正在连接 %s:%d …" % (host, port))

        def work():
            c = Client()
            c.connect(host, port)
            return c

        def ok(client):
            self.client = client
            self._notify_tabs("on_connected")
            self._notify_tabs("on_state_change")

        self.run_thread(work, ok=ok, done_msg="已连接 %s:%d" % (host, port))

    def on_disconnect(self):
        if self.client:
            self._notify_tabs("on_disconnecting")
            self.client.close()
            self.client = None
        self.set_status("已断开")
        self._update_connection_ui()
        self._notify_tabs("on_state_change")

    def _notify_tabs(self, method):
        for tab in self.notebook.tabs():
            w = self.nametowidget(tab)
            if hasattr(w, method):
                getattr(w, method)()

    def _update_connection_ui(self):
        if self.connected():
            self.conn_state.configure(text="● 已连接", bootstyle="success")
            self.btn_connect.configure(state="disabled")
            self.btn_disconnect.configure(state="normal")
        else:
            self.conn_state.configure(text="● 未连接", bootstyle="danger")
            self.btn_connect.configure(state="normal" if not self.busy else "disabled")
            self.btn_disconnect.configure(state="disabled")
