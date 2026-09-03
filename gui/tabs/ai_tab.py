# -*- coding: utf-8 -*-
"""
AI 助手标签页：自然语言对话 + 工具调用（LLM 内置 Agent）
- 兼容任意 OpenAI 兼容端点（OpenAI / DeepSeek / 通义 / Ollama / vLLM ...）
- 遥控操作(operate_control)必须经 messagebox 人工确认才会执行
"""
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, SECONDARY

from ..widgets import RoundButton
from agent.llm import LLMClient, LLMError
from agent.tools import ToolDispatcher
from agent.assistant import AgentSession

_SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "..", "ai_settings.json")


class AiTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self.session = None
        self.busy = False
        self.ui_queue = queue.Queue()
        self._build()
        self._load_settings()

    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        # ---------- LLM 设置 ----------
        cfg = tb.Labelframe(self, text=" LLM 设置（OpenAI 兼容接口） ", padding=8)
        cfg.grid(row=0, column=0, sticky="ew")
        cfg.columnconfigure(1, weight=1)

        tb.Label(cfg, text="接口地址:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value="https://api.deepseek.com/v1")
        tb.Entry(cfg, textvariable=self.url_var).grid(row=0, column=1, sticky="ew", padx=6)

        tb.Label(cfg, text="API Key:").grid(row=1, column=0, sticky="w")
        self.key_var = tk.StringVar(value="")
        tb.Entry(cfg, textvariable=self.key_var, show="*").grid(row=1, column=1, sticky="ew", padx=6)

        tb.Label(cfg, text="模型:").grid(row=2, column=0, sticky="w")
        self.model_var = tk.StringVar(value="")
        self.model_combo = tb.Combobox(cfg, textvariable=self.model_var, width=28)
        self.model_combo.grid(row=2, column=1, sticky="w", padx=6)
        self.btn_fetch_models = tb.Button(cfg, text="⟳ 获取模型",
                                          bootstyle=SECONDARY + "-outline",
                                          command=self.on_fetch_models)
        self.btn_fetch_models.grid(row=2, column=2, padx=6)
        self.btn_clear = tb.Button(cfg, text="清空对话", bootstyle=SECONDARY + "-outline", command=self.on_clear, state="disabled")
        self.btn_clear.grid(row=2, column=3, padx=(6, 0))

        # ---------- 对话记录（圆角 + 灰色边框） ----------
        chatf = tb.Labelframe(self, text=" 对话（工具调用过程会同步显示） ", padding=8)
        chatf.grid(row=1, column=0, sticky="nsew", pady=(8, 6))
        chatf.columnconfigure(0, weight=1)
        chatf.rowconfigure(0, weight=1)
        
        # 创建容器 Frame 用于实现圆角效果
        chat_container = tb.Frame(chatf, bootstyle="light")
        chat_container.grid(row=0, column=0, sticky="nsew")
        chat_container.columnconfigure(0, weight=1)
        chat_container.rowconfigure(0, weight=1)
        
        # 使用 Canvas 绘制圆角矩形背景
        self.chat_canvas = tk.Canvas(
            chat_container,
            highlightthickness=0,
            bg=self._get_bg_color(),
            relief="flat"
        )
        self.chat_canvas.grid(row=0, column=0, sticky="nsew")
        
        # 在 Canvas 上创建圆角矩形
        self._draw_rounded_bg()
        
        # 聊天框 Text 组件（背景透明，无边框）
        self.chat_box = tk.Text(
            chat_container,
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            state="disabled",
            height=18,
            padx=14,
            pady=10,
            spacing1=2,
            spacing3=6,
            bg=self._get_bg_color(),
            relief="flat",
            highlightthickness=0,
            borderwidth=0
        )
        self.chat_box.grid(row=0, column=0, sticky="nsew")
        
        # 滚动条
        vsb = tb.Scrollbar(chat_container, orient="vertical", 
                          command=self.chat_box.yview, bootstyle="round")
        self.chat_box.configure(yscrollcommand=vsb.set)
        vsb.grid(row=0, column=1, sticky="ns", padx=(0, 6))
        
        # 绑定窗口大小变化事件重绘圆角
        chat_container.bind("<Configure>", self._on_container_resize)

        self.chat_box.tag_configure("user", foreground="#2f6fd6", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_box.tag_configure("ai", foreground="#1f7a3d", font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_box.tag_configure("content", foreground="#333333", font=("Microsoft YaHei UI", 10))
        self.chat_box.tag_configure("tool", foreground="#8a8f98", font=("Consolas", 9))
        self.chat_box.tag_configure("tool_err", foreground="#c0392b", font=("Consolas", 9))
        self.chat_box.tag_configure("sep", foreground="#c8cdd4")

        # ---------- 输入区（浅蓝色背景 + 圆角） ----------
        inrow = tb.Frame(self)
        inrow.grid(row=5, column=0, sticky="ew", pady=(4, 0))
        inrow.columnconfigure(0, weight=1)

        # 输入框容器（浅蓝色边框 + 圆角）
        input_container = tb.Frame(inrow, bootstyle="light")
        input_container.grid(row=0, column=0, sticky="ew")
        input_container.columnconfigure(0, weight=1)
        
        # 使用 Canvas 绘制输入框圆角背景（浅蓝色）
        self.input_canvas = tk.Canvas(
            input_container,
            highlightthickness=0,
            bg="#e8f4fd",  # 浅蓝色背景
            relief="flat"
        )
        self.input_canvas.grid(row=0, column=0, sticky="nsew")
        self._draw_input_bg()
        
        # 输入框 Text（浅蓝色背景）
        self.input_box = tk.Text(
            input_container,
            height=4,  # 4行
            wrap="word",
            font=("Microsoft YaHei UI", 10),
            padx=12,
            pady=10,
            relief="flat",
            highlightthickness=0,
            borderwidth=0,
            bg="#e8f4fd"  # 浅蓝色背景
        )
        self.input_box.grid(row=0, column=0, sticky="nsew")
        
        # 绑定输入框大小变化
        input_container.bind("<Configure>", self._on_input_resize)
        
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Key>", self._on_input_key)
        self._set_input_placeholder()

        # ---------- 按钮区（调大按钮） ----------
        btns = tb.Frame(inrow)
        btns.grid(row=0, column=1, sticky="ns", padx=(10, 0))
        
        # 发送按钮 - 调大
        self.btn_send = RoundButton(
            btns, 
            text="发 送", 
            command=self.on_send,
            bg="#2e8c5a", 
            hover="#3caa6e", 
            width=100,   # 从88增加到100
            height=40,   # 从34增加到40
            radius=20,   # 从17增加到20
            font=("Microsoft YaHei UI", 11, "bold")  # 字体调大
        )
        self.btn_send.pack(fill="x", pady=(2, 4))
        
        # 清空按钮 - 调大
        self.btn_clear = RoundButton(
            btns, 
            text="清空对话", 
            command=self.on_clear,
            bg="#6d7889", 
            hover="#7e8a9c", 
            width=100,   # 从88增加到100
            height=36,   # 从30增加到36
            radius=18,   # 从15增加到18
            font=("Microsoft YaHei UI", 10)  # 字体调大
        )
        self.btn_clear.pack(fill="x", pady=(4, 2))
        self._sync_btn_bg()

        self.after(100, self._poll_queue)

    def _get_bg_color(self):
        """获取背景色（浅灰/白）"""
        try:
            return self.tk.call("ttk::style", "lookup", "TFrame", "-background") or "#f7f8fa"
        except Exception:
            return "#f7f8fa"

    def _get_border_color(self):
        """获取边框灰色"""
        return "#d0d4da"

    def _draw_rounded_bg(self, event=None):
        """绘制聊天框的圆角矩形背景"""
        self.chat_canvas.delete("bg_rect")
        w = self.chat_canvas.winfo_width()
        h = self.chat_canvas.winfo_height()
        if w < 10 or h < 10:
            return
        radius = 14  # 圆角半径
        # 绘制圆角矩形（灰色边框 + 浅色填充）
        self.chat_canvas.create_rounded_rect(
            0, 0, w, h,
            radius=radius,
            fill=self._get_bg_color(),
            outline=self._get_border_color(),
            width=1.5,
            tags="bg_rect"
        )
        # 将聊天框置于顶层
        self.chat_box.lift()

    def _draw_input_bg(self, event=None):
        """绘制输入框的圆角矩形背景（浅蓝色边框）"""
        self.input_canvas.delete("bg_rect")
        w = self.input_canvas.winfo_width()
        h = self.input_canvas.winfo_height()
        if w < 10 or h < 10:
            return
        radius = 12  # 圆角半径
        # 浅蓝色边框和背景
        self.input_canvas.create_rounded_rect(
            0, 0, w, h,
            radius=radius,
            fill="#e8f4fd",      # 浅蓝色填充
            outline="#7bb8e0",   # 浅蓝色边框（比背景深一点）
            width=1.5,
            tags="bg_rect"
        )
        self.input_box.lift()

    def _on_container_resize(self, event):
        """容器大小变化时重绘圆角"""
        self._draw_rounded_bg()

    def _on_input_resize(self, event):
        """输入框大小变化时重绘圆角"""
        self._draw_input_bg()

    def on_fetch_models(self):
        """从 LLM 服务端拉取可用模型列表填充下拉框（工作线程执行）"""
        url = self.url_var.get().strip()
        if not url:
            messagebox.showinfo("提示", "请先填写接口地址", parent=self)
            return
        self.btn_fetch_models.configure(state="disabled")
        self.app.set_status("AI助手：正在获取模型列表…")
        llm = LLMClient(url, self.key_var.get().strip(), self.model_var.get().strip())

        def worker():
            try:
                models = llm.list_models()
                self.after(0, lambda: self._fill_models(models))
            except LLMError as e:
                self.after(0, lambda: self._models_failed(str(e)))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: self._models_failed(str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _fill_models(self, models):
        current = self.model_var.get().strip()
        self.model_combo.configure(values=models)
        if current in models:
            self.model_var.set(current)
        else:
            self.model_var.set(models[0])
        self.btn_fetch_models.configure(state="normal")
        self.app.set_status("获取到 %d 个可用模型" % len(models))

    def _models_failed(self, msg):
        self.btn_fetch_models.configure(state="normal")
        self.app.set_status("获取模型失败：%s" % msg, is_error=True)

    # ------------------------------------------------------------------
    # 设置持久化
    # ------------------------------------------------------------------
    def _load_settings(self):
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            self.url_var.set(cfg.get("url", self.url_var.get()))
            self.key_var.set(cfg.get("key", ""))
            self.model_var.set(cfg.get("model", self.model_var.get()))
        except Exception:  # noqa: BLE001
            pass

    def _save_settings(self):
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"url": self.url_var.get(), "key": self.key_var.get(),
                           "model": self.model_var.get()}, f)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 对话
    # ------------------------------------------------------------------
    def _append(self, parts):
        """parts: [(text, tag), ...] 顺序插入"""
        self.chat_box.configure(state="normal")
        for text, tag in parts:
            self.chat_box.insert("end", text, tag)
        self.chat_box.insert("end", "\n")
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    def on_clear(self):
        if self.session:
            self.session.reset()
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")

    # ---- 发送按钮状态（轮询式刷新，杜绝任何卡死） ----
    def _update_send_state(self):
        """只要不在处理中就允许发送；未连接 IED 时聊天仍可用，
        工具会提示先连接（由 Agent 转告用户）。"""
        self.btn_send.set_enabled(not self.busy)

    def on_state_change(self):
        self._update_send_state()

    def on_theme_changed(self):
        self._sync_btn_bg()
        # 主题变化时刷新背景
        self._draw_rounded_bg()
        self._draw_input_bg()

    def _tab_bg(self):
        try:
            return self.tk.call("ttk::style", "lookup", "TFrame", "-background") or "#f5f6f7"
        except Exception:  # noqa: BLE001
            return "#f5f6f7"

    def _sync_btn_bg(self):
        bg = self._tab_bg()
        self.btn_send.sync_bg(bg)
        self.btn_clear.sync_bg(bg)

    # ---- 多行输入框 ----
    _PLACEHOLDER = "输入问题，回车发送（Shift+回车换行）…"

    def _set_input_placeholder(self):
        self._placeholder_active = True
        self.input_box.insert("1.0", self._PLACEHOLDER)
        self.input_box.configure(foreground="#7ba9c9")  # 浅蓝色占位文字

    def _on_input_key(self, e):
        """首次输入时清掉占位文字"""
        if self._placeholder_active and e.keysym not in (
                "Shift_L", "Shift_R", "Control_L", "Control_R",
                "Alt_L", "Alt_R", "Return"):
            self.input_box.delete("1.0", "end")
            self.input_box.configure(foreground="#222222")  # 深色文字
            self._placeholder_active = False

    def _on_enter_key(self, e):
        if self._placeholder_active:
            return "break"
        # Shift+回车 = 换行；回车 = 发送
        if not (int(e.state) & 0x0001):
            self.on_send()
            return "break"
        return None

    def _get_input(self):
        if self._placeholder_active:
            return ""
        return self.input_box.get("1.0", "end").strip()

    def _clear_input(self):
        self.input_box.delete("1.0", "end")

    def on_send(self):
        if self.busy:
            return
        text = self._get_input()
        if not text:
            return
        url = self.url_var.get().strip()
        key = self.key_var.get().strip()
        model = self.model_var.get().strip()
        if not url or not model:
            messagebox.showinfo("提示", "请先填写 LLM 接口地址和模型名", parent=self)
            return
        self._save_settings()

        if not self.app.connected():
            self._append([("提示：当前未连接 IED 服务器，涉及数据操作的回答将不可用。",
                           "tool_err")])
        self._append([("你 ", "user"), (time.strftime("%H:%M:%S"), "tool"),
                      ("\n" + text + "\n", "content"),
                      ("─" * 60, "sep")])
        self._clear_input()
        self.busy = True
        self._update_send_state()

        llm = LLMClient(url, key, model)
        if self.session is None:
            self.session = AgentSession(
                llm, ToolDispatcher(self.app.client, confirm_cb=self._confirm))
        else:
            self.session.llm = llm
            self.session.dispatcher.client = self.app.client
            self.session.dispatcher._model_cache = None

        self.session.on_tool = lambda n, a, r, ok: self.ui_queue.put(
            ("tool", n, a, r, ok))
        self.session.on_status = lambda s: self.ui_queue.put(("status", s))

        def worker():
            try:
                answer = self.session.chat(text)
                self.ui_queue.put(("answer", answer))
            except LLMError as e:
                self.ui_queue.put(("error", str(e)))
            except Exception as e:  # noqa: BLE001
                self.ui_queue.put(("error", "处理失败：%s" % e))

        threading.Thread(target=worker, daemon=True).start()

    # ---- 工具确认（operate 需人工确认） ----
    def _confirm(self, msg):
        done = threading.Event()
        result = [False]

        def ask():
            try:
                result[0] = messagebox.askyesno("遥控确认", msg, parent=self)
            finally:
                done.set()

        self.after(0, ask)
        done.wait(120)
        return result[0]

    # ---- 队列消费（主线程） ----
    def _poll_queue(self):
        self._update_send_state()   # 轮询式刷新发送按钮，任何异常后都能自动恢复
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "tool":
                    _, name, args, result, ok = item
                    t1 = "tool_err" if not ok else "tool"
                    self._append([
                        ("· [" + name + "] ", t1),
                        (json.dumps(args, ensure_ascii=False), t1),
                        ("\n  → " + result.replace("\n", "\n  "), t1),
                    ])
                elif kind == "status":
                    self.app.set_status("AI助手：" + item[1])
                elif kind == "answer":
                    self._append([("AI ", "ai"),
                                  (time.strftime("%H:%M:%S"), "tool"),
                                  ("\n" + item[1] + "\n", "content"),
                                  ("─" * 60, "sep")])
                    self.busy = False
                    self._update_send_state()
                elif kind == "error":
                    self._append([("错误：", "tool_err"), (item[1], "tool_err")])
                    self.busy = False
                    self._update_send_state()
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)
