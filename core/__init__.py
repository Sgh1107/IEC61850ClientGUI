# -*- coding: utf-8 -*-
"""IEC 61850 客户端 GUI —— core 包

通过 ctypes 链接 libiec61850 动态库，封装客户端常用服务：
- 数据模型浏览 / 读 / 写      (connection.py)
- 数据集服务                  (dataset.py)
- 控制操作                    (control.py)
- 报告订阅                    (reports.py)
- MmsValue 与 Python 值互转   (mms_value.py)
"""
