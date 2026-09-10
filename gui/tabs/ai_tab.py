# -*- coding: utf-8 -*-
"""AI 助手标签页：自然语言对话 + 工具调用（LLM 内置 Agent）
- 兼容任意 OpenAI 兼容端点（OpenAI / DeepSeek / 通义 / Ollama / vLLM ...）
- 遥控操作(operate_control)必须经 messagebox 人工确认才会执行
"""
import json
import os.path
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

_PLACEHOLDER = "输入问题，回车发送（Shift+回车换行）…"


class AiTab(tb.Frame):
    def __init__(self, app):
        super().__init__(app, padding=(10, 8))
        self.app = app
        self.session = None
        self.busy = False
        self.ui_queue = queue.Queue()
        self._build()
        self._load_settings()

    # ------------------------------------------------------------------
    # 界面
    # ------------------------------------------------------------------
    def _build(self):
        self.columnconfigure(0, weight=1)
        self.rowconfigure(1, weight=1)

        # ---------- LLM 设置 ----------
        sf = tb.Labelframe(self, text=" LLM 设置（OpenAI 兼容接口） ", padding=8)
        sf.grid(row=0, column=0, sticky="ew")

        tb.Label(sf, text="接口地址:").grid(row=0, column=0, sticky="w")
        self.url_var = tk.StringVar(value="https://api.deepseek.com/v1")
        tb.Entry(sf, textvariable=self.url_var, width=44)\
            .grid(row=0, column=1, sticky="ew", padx=(4, 10))

        tb.Label(sf, text="API Key:").grid(row=0, column=2, sticky="w")
        self.key_var = tk.StringVar(value="")
        tb.Entry(sf, textvariable=self.key_var, show="*", width=22)\
            .grid(row=0, column=3, sticky="ew", padx=(4, 10))

        tb.Label(sf, text="模型:").grid(row=0, column=4, sticky="w")
        self.model_var = tk.StringVar(value="")
        self.model_combo = tb.Combobox(sf, textvariable=self.model_var, width=28)
        self.model_combo.grid(row=0, column=5, sticky="ew", padx=(4, 6))

        self.btn_fetch_models = tb.Button(sf, text="⟳ 获取模型",
                                          bootstyle=SECONDARY,
                                          command=self.on_fetch_models)
        self.btn_fetch_models.grid(row=0, column=6, padx=(2, 2))
        self.btn_clear = tb.Button(sf, text="清空对话", bootstyle=SECONDARY,
                                   command=self.on_clear)
        self.btn_clear.grid(row=0, column=7, padx=(2, 0))

        # ---------- 对话区 ----------
        cf = tb.Labelframe(self, text=" 对话（工具调用过程会同步显示） ")
        cf.grid(row=1, column=0, sticky="nsew", pady=(8, 0))
        cf.columnconfigure(0, weight=1)
        cf.rowconfigure(0, weight=1)

        self.chat_canvas = tk.Canvas(cf, bg=self._get_bg_color(),
                                     highlightthickness=0, relief="flat")
        self.chat_canvas.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=(6, 6))
        self.chat_canvas.columnconfigure(0, weight=1)
        self.chat_canvas.rowconfigure(0, weight=1)

        self.chat_box = tk.Text(self.chat_canvas, wrap="word",
                                font=("Microsoft YaHei UI", 10), state="disabled",
                                height=18, padx=18, pady=14, spacing1=5, spacing3=10,
                                bg="#e8f4fd", relief="flat",
                                highlightthickness=0, borderwidth=0)
        self.chat_box.grid(row=0, column=0, sticky="nsew")

        sb = tb.Scrollbar(self.chat_canvas, orient="vertical",
                          command=self.chat_box.yview, bootstyle="round")
        self.chat_box.configure(yscrollcommand=sb.set)
        sb.grid(row=0, column=1, sticky="ns")

        self.chat_canvas.bind("<Configure>", self._on_container_resize)
        self._draw_rounded_bg()

        # 文本样式 tag
        self.chat_box.tag_configure("user", foreground="#2f6fd6",
                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_box.tag_configure("ai", foreground="#1f7a3d",
                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_box.tag_configure("content", foreground="#333333")
        self.chat_box.tag_configure("tool", foreground="#8a8f98",
                                    font=("Consolas", 9))
        self.chat_box.tag_configure("tool_err", foreground="#c0392b")
        self.chat_box.tag_configure("sep", foreground="#c8cdd4")

        # ---------- 输入区 ----------
        self.input_canvas = tk.Canvas(cf, bg=self._get_bg_color(),
                                      highlightthickness=0, relief="flat")
        self.input_canvas.grid(row=1, column=0, sticky="ew", padx=(8, 8), pady=(4, 8))
        self.input_canvas.columnconfigure(0, weight=1)

        self.input_box = tk.Text(self.input_canvas, height=4, wrap="word",
                                 font=("Microsoft YaHei UI", 10), padx=12, pady=8,
                                 bg="#e8f4fd", relief="flat",
                                 highlightthickness=0, borderwidth=0)
        self.input_box.grid(row=0, column=0, sticky="ew")
        self.input_box.bind("<Return>", self._on_enter_key)
        self.input_box.bind("<Key>", self._on_input_key)
        self.input_box.bind("<Configure>", self._on_input_resize)
        self._draw_input_bg()
        self._set_input_placeholder()

        self.btn_send = RoundButton(self.input_canvas, text="发 送",
                                    command=self.on_send, bg="#2e8c5a",
                                    hover="#3caa6e", width=110)
        self.btn_send.grid(row=0, column=1, padx=(8, 8))
        self._sync_btn_bg()

        self._placeholder_active = True
        self.after(100, self._poll_queue)

    # ------------------------------------------------------------------
    # 圆角背景绘制
    # ------------------------------------------------------------------
    def _get_bg_color(self):
        try:
            return self.tk.call("ttk::style", "lookup", "TFrame", "-background") or "#f5f6f7"
        except Exception:  # noqa: BLE001
            return "#f5f6f7"

    def _get_border_color(self):
        try:
            return self.tk.call("ttk::style", "lookup", "TFrame", "-bordercolor") or "#c8cdd4"
        except Exception:  # noqa: BLE001
            return "#c8cdd4"

    def _round_pts(self, w, h, r=14):
        x2, y2 = w - 1, h - 1
        return [1 + r, 1, x2 - r, 1, x2, 1, x2, 1 + r,
                x2, y2 - r, x2, y2, x2 - r, y2, 1 + r, y2,
                1, y2, 1, y2 - r, 1, 1 + r, 1, 1]

    def _draw_rounded_bg(self, _e=None):
        c = self.chat_canvas
        c.delete("bgrect")
        w = c.winfo_width() or 10
        h = c.winfo_height() or 10
        c.create_polygon(self._round_pts(w, h), smooth=True,
                         fill="#e8f4fd", outline="", tags="bgrect")

    def _draw_input_bg(self, _e=None):
        c = self.input_canvas
        c.delete("bgrect")
        w = c.winfo_width() or 10
        h = c.winfo_height() or 10
        c.create_polygon(self._round_pts(w, h, 12), smooth=True,
                         fill="#e8f4fd", outline="", tags="bgrect")

    def _on_container_resize(self, e):
        self._draw_rounded_bg(e)

    def _on_input_resize(self, e):
        self._draw_input_bg(e)

    # ------------------------------------------------------------------
    # 模型列表 / 设置
    # ------------------------------------------------------------------
    def on_fetch_models(self):
        url = self.url_var.get().strip()
        key = self.key_var.get().strip()
        self.btn_fetch_models.configure(state="disabled")

        def run():
            try:
                ids = LLMClient(url, key).list_models()
                self.after(0, lambda: self._fill_models(ids))
            except Exception as e:  # noqa: BLE001
                self.after(0, lambda: self._models_failed(e))

        threading.Thread(target=run, daemon=True).start()

    def _fill_models(self, ids):
        self.model_combo.configure(values=ids)
        if ids and not self.model_var.get():
            self.model_var.set(ids[0])
        self.btn_fetch_models.configure(state="normal")
        self.app.set_status("获取到 %d 个可用模型" % len(ids))

    def _models_failed(self, e):
        self.btn_fetch_models.configure(state="normal")
        self.app.set_status("获取模型失败：%s" % e, is_error=True)

    def _load_settings(self):
        try:
            with open(_SETTINGS_FILE, encoding="utf-8") as f:
                cfg = json.load(f)
            self.url_var.set(cfg.get("url", self.url_var.get()))
            self.key_var.set(cfg.get("key", ""))
            self.model_var.set(cfg.get("model", ""))
        except Exception:  # noqa: BLE001
            pass

    def _save_settings(self):
        try:
            with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({"url": self.url_var.get(),
                           "key": self.key_var.get(),
                           "model": self.model_var.get()}, f)
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # 消息显示 / 状态
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

    def _update_send_state(self):
        # 只要不在处理中就允许发送；未连接 IED 时聊天仍可用，
        # 工具会提示先连接（由 Agent 转告用户）。
        self.btn_send.set_enabled(not self.busy)

    def on_state_change(self):
        self._update_send_state()

    def on_theme_changed(self):
        self._sync_btn_bg()
        self._draw_rounded_bg()
        self._draw_input_bg()

    def _tab_bg(self):
        try:
            return self.tk.call("ttk::style", "lookup", "TFrame", "-background")
        except Exception:  # noqa: BLE001
            return "#f5f6f7"

    def _sync_btn_bg(self):
        bg = self._tab_bg()
        self.btn_send.sync_bg(bg)

    # ------------------------------------------------------------------
    # 输入占位 / 发送
    # ------------------------------------------------------------------
    def _set_input_placeholder(self):
        self._placeholder_active = True
        self.input_box.insert("1.0", _PLACEHOLDER)
        self.input_box.configure(foreground="#7ba9c9")

    def _on_input_key(self, e):
        # 首次输入时清掉占位文字
        if self._placeholder_active and e.keysym not in (
                "Shift_L", "Shift_R", "Control_L", "Control_R",
                "Alt_L", "Alt_R", "Return"):
            self.input_box.delete("1.0", "end")
            self.input_box.configure(foreground="#222222")
            self._placeholder_active = False

    def _on_enter_key(self, e):
        if self._placeholder_active:
            return "break"
        if int(e.state) & 0x1:          # Shift+回车 → 换行
            return
        self.on_send()
        return "break"

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

        self._append([("你 ", "user"), (time.strftime("%H:%M:%S"), "tool"), "\n",
                      (text, "content"),
                      ("────────────────────────────────────────────────────────────",
                       "sep")])
        self._clear_input()
        self.busy = True
        self._update_send_state()

        llm = LLMClient(url, key, model)
        if self.session is None:
            dispatcher = ToolDispatcher(self.app.client, confirm_cb=self._confirm)
            self.session = AgentSession(llm, dispatcher)
            self.session.on_tool = lambda name, args, res, q=self.ui_queue: \
                q.put(("tool", (name, args, res)))
            self.session.on_status = lambda text_, q=self.ui_queue: \
                q.put(("status", text_))
        else:
            self.session.llm = llm
            self.session.dispatcher.client = self.app.client
            self.session.dispatcher._model_cache = None

        def worker():
            try:
                answer = self.session.chat(text)
                self.ui_queue.put(("answer", answer))
            except LLMError as e:
                self.ui_queue.put(("error", str(e)))
            except Exception as e:  # noqa: BLE001
                self.ui_queue.put(("error", "处理失败：%s" % e))

        threading.Thread(target=worker, daemon=True).start()

    # ------------------------------------------------------------------
    # 遥控确认（messagebox 人工确认，带超时保护）
    # ------------------------------------------------------------------
    def _confirm(self, text):
        evt = threading.Event()
        ok = [False]

        def ask():
            ok[0] = messagebox.askyesno("遥控确认", text, parent=self)
            evt.set()

        self.after(120, ask)
        return evt.wait(120) and ok[0]

    # ------------------------------------------------------------------
    # UI 队列
    # ------------------------------------------------------------------
    def _poll_queue(self):
        try:
            self._update_send_state()
            while True:
                kind, payload = self.ui_queue.get_nowait()
                if kind == "tool":
                    name, args, (result, ok) = payload
                    tag = "tool" if ok else "tool_err"
                    self._append([
                        ("· [", "tool"), (name, "tool"), ("] ", "tool"),
                        (json.dumps(args, ensure_ascii=False).replace("\n", " "),
                         "tool"),
                        ("\n  → ", "tool"), (str(result), tag), "\n",
                    ])
                elif kind == "status":
                    self.app.set_status("AI助手：" + str(payload))
                elif kind == "answer":
                    self._append([("AI ", "ai"),
                                  (time.strftime("%H:%M:%S"), "tool"), "\n",
                                  (str(payload), "content"),
                                  ("────────────────────────────────────────────────"
                                   "────────────", "sep")])
                    self.busy = False
                elif kind == "error":
                    self._append([("错误：", "tool_err"), (str(payload), "tool_err")])
                    self.busy = False
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)
