# -*- coding: utf-8 -*-
"""IEC 61850 客户端 GUI 工具 —— 入口

用法:
    python main.py [服务器IP] [端口]

依赖:
    pip install ttkbootstrap
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import App, APP_TITLE


def main():
    app = App()
    if len(sys.argv) > 1:
        app.host_var.set(sys.argv[1])
    if len(sys.argv) > 2:
        app.port_var.set(sys.argv[2])
    app.mainloop()


if __name__ == "__main__":
    main()
