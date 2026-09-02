# -*- coding: utf-8 -*-
"""MmsValue 与 Python 值的互转。"""
import ctypes

from . import ffi

_L = None


def _lib():
    global _L
    if _L is None:
        _L = ffi.lib()
    return _L


TYPE_NAMES = {
    ffi.MMS_ARRAY: "数组", ffi.MMS_STRUCTURE: "结构体", ffi.MMS_BOOLEAN: "布尔",
    ffi.MMS_BIT_STRING: "位串", ffi.MMS_INTEGER: "整数", ffi.MMS_UNSIGNED: "无符号整数",
    ffi.MMS_FLOAT: "浮点数", ffi.MMS_OCTET_STRING: "八位串",
    ffi.MMS_VISIBLE_STRING: "字符串", ffi.MMS_STRING: "字符串", ffi.MMS_UTC_TIME: "时间",
}


def mms_value_to_python(ptr):
    """把 MmsValue* 转为 Python 值（递归处理结构体/数组）。"""
    if not ptr:
        return None
    L = _lib()
    t = L.MmsValue_getType(ptr)
    if t in (ffi.MMS_ARRAY, ffi.MMS_STRUCTURE):
        n = L.MmsValue_getArraySize(ptr)
        return [mms_value_to_python(L.MmsValue_getElement(ptr, i)) for i in range(n)]
    if t == ffi.MMS_BOOLEAN:
        return bool(L.MmsValue_getBoolean(ptr))
    if t in (ffi.MMS_INTEGER, ffi.MMS_UNSIGNED):
        return L.MmsValue_toInt64(ptr)
    if t == ffi.MMS_FLOAT:
        return L.MmsValue_toFloat(ptr)
    if t == ffi.MMS_VISIBLE_STRING:
        s = L.MmsValue_toString(ptr)
        return s.decode("utf-8", "replace") if s else ""
    # 其余类型（位串/时间/八位串等）用库自带的打印函数转字符串
    buf = ctypes.create_string_buffer(512)
    L.MmsValue_printToBuffer(ptr, buf, 512)
    return buf.value.decode("utf-8", "replace")


def mms_value_to_text(ptr):
    """把任意 MmsValue* 用库的打印函数转成单行文本（显示用）。"""
    if not ptr:
        return "(空)"
    buf = ctypes.create_string_buffer(1024)
    _lib().MmsValue_printToBuffer(ptr, buf, 1024)
    return buf.value.decode("utf-8", "replace").strip()


def python_to_mms_value(value):
    """把 Python 值转为 MmsValue*（调用方负责 MmsValue_delete 释放）。"""
    L = _lib()
    if isinstance(value, bool):
        return L.MmsValue_newBoolean(1 if value else 0)
    if isinstance(value, int):
        return L.MmsValue_newIntegerFromInt64(value)
    if isinstance(value, float):
        return L.MmsValue_newFloat(value)
    if isinstance(value, str):
        return L.MmsValue_newVisibleString(value.encode("utf-8"))
    raise TypeError("不支持的值类型: %s" % type(value).__name__)


def parse_text_value(text):
    """把用户输入的文本智能解析为 Python 值。"""
    t = text.strip()
    if t.lower() in ("true", "1", "on", "开", "合"):
        return True
    if t.lower() in ("false", "0", "off", "关", "分"):
        return False
    try:
        return int(t)
    except ValueError:
        pass
    try:
        return float(t)
    except ValueError:
        pass
    return t
