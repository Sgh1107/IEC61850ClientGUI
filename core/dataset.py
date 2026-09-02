# -*- coding: utf-8 -*-
"""数据集服务封装。"""
import ctypes

from . import ffi
from .connection import MmsError
from .mms_value import mms_value_to_python, python_to_mms_value, mms_value_to_text


class DataSet(object):
    """一次性读取的数据集快照"""

    def __init__(self, client, ref):
        self.client = client
        self.ref = ref
        self.err = ctypes.c_int(0)
        L = client._lib
        self._ds = L.IedConnection_readDataSetValues(
            client.con, ctypes.byref(self.err), ref.encode("utf-8"), None)
        if self.err.value != ffi.IED_ERROR_OK or not self._ds:
            raise MmsError(self.err.value or 128,
                                  "读取数据集失败：%s" % ffi.err_str(self.err.value or 128))

    @property
    def values(self):
        """成员值列表（Python 值）"""
        L = self.client._lib
        vals = L.ClientDataSet_getValues(self._ds)
        n = L.MmsValue_getArraySize(vals)
        return [mms_value_to_python(L.MmsValue_getElement(vals, i)) for i in range(n)]

    @property
    def texts(self):
        """成员值的文本形式列表"""
        L = self.client._lib
        vals = L.ClientDataSet_getValues(self._ds)
        n = L.MmsValue_getArraySize(vals)
        return [mms_value_to_text(L.MmsValue_getElement(vals, i)) for i in range(n)]

    def destroy(self):
        if self._ds:
            self.client._lib.ClientDataSet_destroy(self._ds)
            self._ds = None

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.destroy()


def get_members(client, ds_ref):
    """读取数据集成员引用列表（不取值）"""
    deletable = ctypes.c_int(0)
    err = ctypes.c_int(0)
    L = client._lib
    head = L.IedConnection_getDataSetDirectory(
        client.con, ctypes.byref(err), ds_ref.encode("utf-8"), ctypes.byref(deletable))
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)
    out = []
    node = L.LinkedList_getNext(head)
    while node:
        data = L.LinkedList_getData(node)
        if data:
            out.append(ctypes.cast(data, ctypes.c_char_p).value.decode("utf-8", "replace"))
        node = L.LinkedList_getNext(node)
    L.LinkedList_destroy(head)
    return out


def write_values(client, ds_ref, values):
    """按顺序写数据集成员值（values 数量需与成员数一致）"""
    L = client._lib
    err = ctypes.c_int(0)
    head = L.LinkedList_create()
    mvs = []
    try:
        for v in values:
            mv = python_to_mms_value(v)
            mvs.append(mv)
            L.LinkedList_add(head, mv)
        L.IedConnection_writeDataSetValues(
            client.con, ctypes.byref(err), ds_ref.encode("utf-8"), head, None)
    finally:
        for mv in mvs:
            L.MmsValue_delete(mv)
        L.LinkedList_destroy(head)
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)
