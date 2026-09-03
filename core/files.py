# -*- coding: utf-8 -*-
"""
MMS 文件服务封装（作用于已有 Client 连接）
参考 examples/iec61850_client_example_files/file-tool.c 与 MMSFileUI 的实现。
"""
import ctypes
import os
from ctypes import CFUNCTYPE, POINTER, byref, c_bool, c_char_p, c_int
from ctypes import c_uint8, c_uint32, c_uint64, c_void_p

from . import ffi
from .connection import MmsError


class _LinkedList(ctypes.Structure):
    pass


_LinkedList._fields_ = [("data", c_void_p), ("next", POINTER(_LinkedList))]

# 文件下载回调: bool (*)(void* parameter, uint8_t* buffer, uint32_t bytesRead)
_DOWNLOAD_CB = CFUNCTYPE(c_bool, c_void_p, POINTER(c_uint8), c_uint32)
_VALUE_DELETE_FUNC = CFUNCTYPE(None, c_void_p)

_BOUND = False


def _bind(L):
    """把文件服务相关函数签名绑定到共享库句柄（幂等）"""
    global _BOUND
    if _BOUND:
        return
    Con = c_void_p
    Err = POINTER(c_int)

    L.IedConnection_getFileDirectory.restype = POINTER(_LinkedList)
    L.IedConnection_getFileDirectory.argtypes = [Con, Err, c_char_p]
    L.IedConnection_getFile.restype = None
    L.IedConnection_getFile.argtypes = [Con, Err, c_char_p, _DOWNLOAD_CB, c_void_p]
    L.IedConnection_setFilestoreBasepath.restype = None
    L.IedConnection_setFilestoreBasepath.argtypes = [Con, c_char_p]
    L.IedConnection_setFile.restype = None
    L.IedConnection_setFile.argtypes = [Con, Err, c_char_p, c_char_p]
    L.IedConnection_deleteFile.restype = None
    L.IedConnection_deleteFile.argtypes = [Con, Err, c_char_p]
    L.LinkedList_destroyDeep.restype = None
    L.LinkedList_destroyDeep.argtypes = [POINTER(_LinkedList), _VALUE_DELETE_FUNC]
    L.FileDirectoryEntry_destroy.restype = None
    L.FileDirectoryEntry_destroy.argtypes = [c_void_p]
    L.FileDirectoryEntry_getFileName.restype = c_char_p
    L.FileDirectoryEntry_getFileName.argtypes = [c_void_p]
    L.FileDirectoryEntry_getFileSize.restype = c_uint32
    L.FileDirectoryEntry_getFileSize.argtypes = [c_void_p]
    L.FileDirectoryEntry_getLastModified.restype = c_uint64
    L.FileDirectoryEntry_getLastModified.argtypes = [c_void_p]
    _BOUND = True


def _to_str(b):
    if b is None:
        return ""
    if isinstance(b, str):
        return b
    for enc in ("utf-8", "gbk"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            continue
    return b.decode("utf-8", errors="replace")


def list_dir(client, dirname=""):
    """列出目录内容。dirname 为 "" 表示根目录。返回 [{name, size, mtime}]"""
    L = client._lib
    _bind(L)
    err = c_int(0)
    dirname_c = dirname.encode("utf-8") if dirname else None
    lst = L.IedConnection_getFileDirectory(client.con, byref(err), dirname_c)
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)

    entries = []
    node = lst
    while node:
        entry = node.contents.data
        if entry:
            entries.append({
                "name": _to_str(L.FileDirectoryEntry_getFileName(entry)),
                "size": int(L.FileDirectoryEntry_getFileSize(entry)),
                "mtime": int(L.FileDirectoryEntry_getLastModified(entry)),
            })
        node = node.contents.next
    deleter = _VALUE_DELETE_FUNC(L.FileDirectoryEntry_destroy)
    L.LinkedList_destroyDeep(lst, deleter)
    return entries


def download(client, remote_filename, local_filename, progress_cb=None):
    """下载文件。progress_cb(received_bytes) 用于进度显示"""
    L = client._lib
    _bind(L)
    received = [0]

    @_DOWNLOAD_CB
    def handler(_param, buffer, nbytes):
        try:
            with open(local_filename, "ab") as fp:
                fp.write(ctypes.string_at(buffer, nbytes))
        except OSError:
            return False
        received[0] += int(nbytes)
        if progress_cb:
            try:
                progress_cb(received[0])
            except Exception:  # noqa: BLE001
                pass
        return True

    try:
        os.remove(local_filename)
    except OSError:
        pass

    err = c_int(0)
    L.IedConnection_getFile(client.con, byref(err),
                            remote_filename.encode("utf-8"), handler, None)
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)


def upload(client, local_filename, remote_filename=None):
    """上传本地文件。remote_filename 默认取本地文件名（上传到当前服务器目录由调用方拼接）"""
    L = client._lib
    _bind(L)
    local_filename = os.path.abspath(local_filename)
    if remote_filename is None:
        remote_filename = os.path.basename(local_filename)

    base_dir = os.path.dirname(local_filename)
    if not base_dir.endswith(("/", "\\")):
        base_dir += "/"
    L.IedConnection_setFilestoreBasepath(client.con, base_dir.encode("utf-8"))

    err = c_int(0)
    L.IedConnection_setFile(client.con, byref(err),
                            os.path.basename(local_filename).encode("utf-8"),
                            remote_filename.encode("utf-8"))
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)


def delete(client, remote_filename):
    L = client._lib
    _bind(L)
    err = c_int(0)
    L.IedConnection_deleteFile(client.con, byref(err), remote_filename.encode("utf-8"))
    if err.value != ffi.IED_ERROR_OK:
        raise MmsError(err.value)
