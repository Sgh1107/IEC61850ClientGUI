# -*- coding: utf-8 -*-
"""AI 助手标签页：自然语言对话 + 工具调用（LLM 内置 Agent）。

- 兼容任意 OpenAI 兼容端点（OpenAI / DeepSeek / 通义 / Ollama / vLLM ...）
- 遥控操作(operate_control)必须经 messagebox 人工确认才会执行
"""
import json
import os
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb
from ttkbootstrap.constants import PRIMARY, SUCCESS, SECONDARY

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
        self.model_var = tk.StringVar(value="deepseek-chat")
        tb.Entry(cfg, textvariable=self.model_var, width=24).grid(row=2, column=1,
                                                                  sticky="w", padx=6)
        self.btn_clear = tb.Button(cfg, text="清空对话", bootstyle=SECONDARY + "-outline",
                                   command=self.on_clear, state="disabled")
        self.btn_clear.grid(row=2, column=2, padx=6)

        # ---------- 对话记录 ----------
        chatf = tb.Labelframe(self, text=" 对话（工具调用过程会同步显示） ", padding=6)
        chatf.grid(row=1, column=0, sticky="nsew", pady=(8, 6))
        chatf.columnconfigure(0, weight=1)
        chatf.rowconfigure(0, weight=1)
        self.chat_box = tb.Text(chatf, wrap="word", font=("Microsoft YaHei UI", 10),
                                state="disabled", height=14)
        vsb = tb.Scrollbar(chatf, orient="vertical", command=self.chat_box.yview,
                           bootstyle="round")
        self.chat_box.configure(yscrollcommand=vsb.set)
        self.chat_box.tag_configure("user", foreground="#3c78dc",
                                    font=("Microsoft YaHei UI", 10, "bold"))
        self.chat_box.tag_configure("tool_ok", foreground="#78a078")
        self.chat_box.tag_configure("tool_err", foreground="#c85a5a")
        self.chat_box.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        # ---------- 输入 ----------
        inrow = tb.Frame(self)
        inrow.grid(row=2, column=0, sticky="ew")
        inrow.columnconfigure(0, weight=1)
        self.input_var = tk.StringVar()
        self.input_box = tb.Entry(inrow, textvariable=self.input_var,
                                  font=("Microsoft YaHei UI", 10))
        self.input_box.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.input_box.bind("<Return>", lambda _e: self.on_send())
        self.btn_send = tb.Button(inrow, text="发送", bootstyle=PRIMARY,
                                  command=self.on_send, state="disabled")
        self.btn_send.grid(row=0, column=1)

        self.after(100, self._poll_queue)

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
    def _append(self, text, tag=None):
        self.chat_box.configure(state="normal")
        if tag:
            self.chat_box.insert("end", text + "\n", tag)
        else:
            self.chat_box.insert("end", text + "\n")
        self.chat_box.see("end")
        self.chat_box.configure(state="disabled")

    def on_clear(self):
        if self.session:
            self.session.reset()
        self.chat_box.configure(state="normal")
        self.chat_box.delete("1.0", "end")
        self.chat_box.configure(state="disabled")

    def on_state_change(self):
        state = "normal" if self.app.connected() else "disabled"
        self.btn_send.configure(state=state)

    def on_disconnecting(self):
        pass

    def on_send(self):
        if not self.app.connected():
            messagebox.showinfo("提示", "请先连接到服务器", parent=self)
            return
        if self.busy:
            return
        text = self.input_var.get().strip()
        if not text:
            return
        url, key, model = self.url_var.get().strip(), self.key_var.get().strip(), \
            self.model_var.get().strip()
        if not url or not model:
            messagebox.showinfo("提示", "请先填写 LLM 接口地址和模型名", parent=self)
            return
        self._save_settings()

        self._append("你：" + text, "user")
        self.input_var.set("")
        self.busy = True
        self.btn_send.configure(state="disabled")

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
        try:
            while True:
                item = self.ui_queue.get_nowait()
                kind = item[0]
                if kind == "tool":
                    _, name, args, result, ok = item
                    tag = "tool_ok" if ok else "tool_err"
                    self._append("[工具] %s %s\n→ %s" % (name, json.dumps(args, ensure_ascii=False), result),
                                 tag)
                elif kind == "status":
                    self.app.set_status("AI助手：" + item[1])
                elif kind == "answer":
                    self._append("AI：" + item[1])
                    self.busy = False
                    self.btn_send.configure(state="normal")
                elif kind == "error":
                    self._append("错误：" + item[1], "tool_err")
                    self.busy = False
                    self.btn_send.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._poll_queue)


