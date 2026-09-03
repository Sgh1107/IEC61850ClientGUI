# -*- coding: utf-8 -*-
"""自绘圆角按钮（ttk 原生不支持圆角，用 Canvas 实现）。"""
import tkinter as tk


def _round_rect_points(x1, y1, x2, y2, r):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r,
           x2, y2 - r, x2, y2, x2 - r, y2, x1 + r, y2,
           x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return pts


class RoundButton(tk.Canvas):
    """圆角按钮：支持悬停变色、文字/颜色动态修改、禁用状态。"""

    def __init__(self, master, text, command=None, bg="#2e8c5a", hover="#3caa6e",
                 disabled="#9aa3af", fg="#ffffff", width=110, height=36,
                 font=("Microsoft YaHei UI", 10, "bold"), radius=17, **kw):
        try:
            canvas_bg = master["bg"]
        except (KeyError, tk.TclError):
            canvas_bg = None
        super().__init__(master, width=width, height=height,
                         highlightthickness=0, bd=0,
                         bg=canvas_bg if canvas_bg else "#000000", **kw)
        self._text = text
        self._command = command
        self._bg, self._hover, self._disabled = bg, hover, disabled
        self._fg = fg
        self._enabled = True
        self._hovering = False
        self._radius = radius
        self._font = font

        self._rect = self._draw(bg)
        self._label = self.create_text(width / 2, height / 2, text=text,
                                       fill=fg, font=font)

        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Button-1>", self._on_click)

    # ---- 绘制 ----
    def _draw(self, color):
        w = int(self["width"])
        h = int(self["height"])
        return self.create_polygon(
            _round_rect_points(1, 1, w - 2, h - 2, self._radius),
            smooth=True, fill=color, outline="")

    def _redraw(self, color):
        self.itemconfigure(self._rect, fill=color)

    # ---- 事件 ----
    def _on_enter(self, _e):
        self._hovering = True
        if self._enabled:
            self._redraw(self._hover)

    def _on_leave(self, _e):
        self._hovering = False
        self._redraw(self._bg if self._enabled else self._disabled)

    def _on_click(self, _e):
        if self._enabled and self._command:
            self._command()

    # ---- 公共接口 ----
    def sync_bg(self, color):
        """让画布背景与所在容器颜色一致（主题切换后调用）"""
        self.configure(bg=color)

    def set_text(self, text):
        self._text = text
        self.itemconfigure(self._label, text=text)

    def set_color(self, bg, hover=None):
        self._bg = bg
        self._hover = hover or bg
        self._redraw(self._disabled if not self._enabled
                     else (self._hover if self._hovering else self._bg))

    def set_enabled(self, enabled):
        self._enabled = bool(enabled)
        cursor = "hand2" if self._enabled else "arrow"
        self.configure(cursor=cursor)
        color = self._bg if self._enabled else self._disabled
        self._redraw(color)
        self.itemconfigure(self._label, fill=self._fg if self._enabled else "#e8eaed")
