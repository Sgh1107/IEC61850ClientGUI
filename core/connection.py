# -*- coding: utf-8 -*-
"""连接与数据模型浏览 / 读 / 写封装。"""
import ctypes

from . import ffi
from .mms_value import mms_value_to_python, python_to_mms_value

P = ctypes.c_void_p


class MmsError(Exception):
    """libiec61850 服务错误（携带 IedClientError 错误码）"""

    def __init__(self, code, message=""):
        self.code = code
        super().__init__(message or ffi.err_str(code))


class Client(object):
    """IEC 61850 客户端会话（对应一个 IedConnection）"""

    STATE_CLOSED, STATE_CONNECTING, STATE_CONNECTED, STATE_CLOSING = 0, 1, 2, 3

    def __init__(self):
        self._lib = ffi.lib()
        self.con = self._lib.IedConnection_create()
        self.err = ctypes.c_int(0)

    # ---------------- 连接管理 ----------------
    def connect(self, host, port=102, timeout_ms=10000):
        self.err.value = -1
        self._lib.IedConnection_setConnectTimeout(self.con, timeout_ms)
        self._lib.IedConnection_connect(self.con, ctypes.byref(self.err),
                                        host.encode("utf-8"), int(port))
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value, "连接 %s:%s 失败：%s"
                           % (host, port, ffi.err_str(self.err.value)))

    def disconnect(self, abort=True):
        self.err.value = 0
        if abort:
            self._lib.IedConnection_abort(self.con, ctypes.byref(self.err))
        else:
            self._lib.IedConnection_release(self.con, ctypes.byref(self.err))

    def close(self):
        try:
            self._lib.IedConnection_abort(self.con, ctypes.byref(self.err))
            self._lib.IedConnection_destroy(self.con)
        except Exception:  # noqa: BLE001
            pass

    @property
    def state(self):
        return self._lib.IedConnection_getState(self.con)

    @property
    def connected(self):
        return self.state == self.STATE_CONNECTED

    # ---------------- 内部工具 ----------------
    def _str_list(self, head):
        """遍历 LinkedList<char*> 并释放。head: LinkedList 句柄"""
        out = []
        if not head:
            return out
        node = self._lib.LinkedList_getNext(head)
        while node:
            data = self._lib.LinkedList_getData(node)
            if data:
                out.append(ctypes.cast(data, ctypes.c_char_p).value.decode("utf-8", "replace"))
            node = self._lib.LinkedList_getNext(node)
        self._lib.LinkedList_destroy(head)
        return out

    # ---------------- 数据模型浏览 ----------------
    def get_logical_devices(self):
        self.err.value = 0
        head = self._lib.IedConnection_getServerDirectory(
            self.con, ctypes.byref(self.err), 0)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        return self._str_list(head)

    def get_logical_nodes(self, ld_name):
        self.err.value = 0
        head = self._lib.IedConnection_getLogicalDeviceDirectory(
            self.con, ctypes.byref(self.err), ld_name.encode("utf-8"))
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        return self._str_list(head)

    def get_data_objects(self, ln_ref):
        self.err.value = 0
        head = self._lib.IedConnection_getLogicalNodeDirectory(
            self.con, ctypes.byref(self.err), ln_ref.encode("utf-8"),
            ffi.ACSI_DATA_OBJECT)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        return self._str_list(head)

    def get_data_attributes(self, do_ref, with_fc=True):
        """列出数据对象/属性的下级成员。with_fc=True 时返回 '名称[FC]' 形式"""
        self.err.value = 0
        fn = (self._lib.IedConnection_getDataDirectoryFC if with_fc
              else self._lib.IedConnection_getDataDirectory)
        head = fn(self.con, ctypes.byref(self.err), do_ref.encode("utf-8"))
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        return self._str_list(head)

    def get_rcbs(self, ln_ref, buffered):
        self.err.value = 0
        head = self._lib.IedConnection_getLogicalNodeDirectory(
            self.con, ctypes.byref(self.err), ln_ref.encode("utf-8"),
            ffi.ACSI_BRCB if buffered else ffi.ACSI_URCB)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        prefix = "BR" if buffered else "RP"
        return ["%s.%s.%s" % (ln_ref, prefix, n) for n in self._str_list(head)]

    def get_data_sets(self, ln_ref):
        self.err.value = 0
        head = self._lib.IedConnection_getLogicalNodeDirectory(
            self.con, ctypes.byref(self.err), ln_ref.encode("utf-8"),
            ffi.ACSI_DATA_SET)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
        return ["%s.%s" % (ln_ref, n) for n in self._str_list(head)]

    # ---------------- 读 / 写 ----------------
    def read(self, ref, fc):
        """读数据属性，返回 Python 值。

        :param ref: 数据属性引用，如 simpleIOGenericIO/GGIO1.AnIn1.mag.f
        :param fc:  功能约束代码（"MX"/"ST"/…）或整数
        """
        self.err.value = 0
        fc_code = ffi.FC_BY_NAME[fc] if isinstance(fc, str) else int(fc)
        val = self._lib.IedConnection_readObject(
            self.con, ctypes.byref(self.err), ref.encode("utf-8"), fc_code)
        if self.err.value != ffi.IED_ERROR_OK or not val:
            raise MmsError(self.err.value or 128, "读取失败：%s"
                           % ffi.err_str(self.err.value or 128))
        try:
            return mms_value_to_python(val)
        finally:
            self._lib.MmsValue_delete(val)

    def write(self, ref, fc, value):
        self.err.value = 0
        fc_code = ffi.FC_BY_NAME[fc] if isinstance(fc, str) else int(fc)
        mv = python_to_mms_value(value)
        try:
            self._lib.IedConnection_writeObject(
                self.con, ctypes.byref(self.err), ref.encode("utf-8"),
                fc_code, mv)
        finally:
            self._lib.MmsValue_delete(mv)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)
