# -*- coding: utf-8 -*-
"""
主窗口：连接栏 + 功能标签页 + 状态栏
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

from .widgets import RoundButton
from .tabs.data_browser import DataBrowserTab
from .tabs.dataset_tab import DataSetTab
from .tabs.control_tab import ControlTab
from .tabs.report_tab import ReportTab
from .tabs.file_tab import FileTab

APP_TITLE = "IEC 61850 客户端工具 (v1.6.1)"


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
        self.port_var = tk.StringVar(value="102")
        tb.Entry(header, textvariable=self.port_var, width=6).pack(side="left", padx=(4, 10))

        self.btn_connect = RoundButton(header, text="连 接", command=self.on_conn_toggle,
                                       bg="#2e8c5a", hover="#3caa6e", width=100)
        self.btn_connect.pack(side="left", padx=(12, 6))
        self.btn_theme = RoundButton(header, text="夜间模式", command=self.on_toggle_theme,
                                     bg="#5b6472", hover="#6d7889", width=96,
                                     font=("Microsoft YaHei UI", 10))
        self.btn_theme.pack(side="left")

        self.conn_state = tb.Label(header, text="● 未连接", bootstyle="inverse-danger",
                                   font=("Microsoft YaHei UI", 10, "bold"))
        self.conn_state.pack(side="right", padx=(0, 12))

        self._dark = False

        # ---------- 按钮样式：去掉虚线焦点框 ----------
        st = self.style
        for cls in ("TButton", "success.TButton", "danger.TButton",
                    "secondary.TButton", "secondary-outline.TButton"):
            st.map(cls, focuscolor=[("focus", "")])

        self._sync_round_btn_bg()   # 圆角按钮画布底色与标题栏融合

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
        self._update_connection_ui()   # 先恢复 UI 状态，回调异常也不会卡住按钮
        state, payload = result
        try:
            if state == "OK":
                self.set_status(done_msg or "操作完成")
                if ok:
                    ok(payload)
            else:
                if err:
                    err(payload)
                else:
                    self.set_status("错误：%s" % payload, is_error=True)
        except Exception as e:  # noqa: BLE001
            import traceback
            traceback.print_exc()
            self.set_status("界面回调异常：%s" % e, is_error=True)
        self._update_connection_ui()

    def run_async(self, fn, ok=None, err=None, done_msg=None):
        """ 要求已连接的 run_thread 封装 """
        if not self.connected():
            self.set_status("未连接到服务器", is_error=True)
            return
        self.run_thread(fn, ok=ok, err=err, done_msg=done_msg)

    # ------------------------------------------------------------------
    # 主题切换（日间 flatly / 夜间 darkly）
    # ------------------------------------------------------------------
    def on_toggle_theme(self):
        self._dark = not self._dark
        theme = "darkly" if self._dark else "flatly"
        self.style.theme_use(theme)
        self.btn_theme.set_text("日间模式" if self._dark else "夜间模式")
        self._sync_round_btn_bg()
        self.set_status("已切换到%s" % ("夜间模式" if self._dark else "日间模式"))

    def _header_bg(self):
        """查询当前主题下标题栏的实际背景色，让圆角按钮画布与之融合"""
        try:
            color = self.tk.call("ttk::style", "lookup", "primary.TFrame", "-background")
            return color or "#2c3e50"
        except Exception:  # noqa: BLE001
            return "#2c3e50"

    def _sync_round_btn_bg(self):
        bg = self._header_bg()
        self.btn_connect.sync_bg(bg)
        self.btn_theme.sync_bg(bg)

    # ------------------------------------------------------------------
    # 连接 / 断开（同一按钮，按状态切换）
    # ------------------------------------------------------------------
    def on_conn_toggle(self):
        if self.connected():
            self.on_disconnect()
        else:
            self.on_connect()
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
            self._notify_tabs("on_state_change")
            # 顺序扫描各页所需的服务器模型（同一连接不能并发 MMS 请求）
            chain = [self.tab_data, self.tab_dataset, self.tab_control, self.tab_report]

            def run_chain(i=0):
                if i < len(chain):
                    tab = chain[i]
                    try:
                        tab.load_model(done=lambda: run_chain(i + 1))
                    except Exception as e:  # noqa: BLE001
                        import traceback
                        traceback.print_exc()
                        self.set_status("模型扫描跳过（%s）：%s" % (type(tab).__name__, e),
                                        is_error=True)
                        run_chain(i + 1)
            run_chain()

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
            self.btn_connect.set_text("断开连接")
            self.btn_connect.set_color("#c0392b", "#e74c3c")   # 红色 = 断开操作
            self.btn_connect.set_enabled(not self.busy)
        else:
            self.conn_state.configure(text="● 未连接", bootstyle="danger")
            self.btn_connect.set_text("连 接")
            self.btn_connect.set_color("#2e8c5a", "#3caa6e")   # 绿色 = 连接操作
            self.btn_connect.set_enabled(not self.busy)
            
