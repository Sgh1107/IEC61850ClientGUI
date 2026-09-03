# -*- coding: utf-8 -*-
"""控制操作封装（直控 / SBO 选择-执行）"""
import ctypes

from .connection import MmsError
from .mms_value import python_to_mms_value


def operate(client, obj_ref, value, sbo=False, or_ident="", or_cat=3,
            interlock_check=False, synchro_check=False):
    """对控制对象执行操作。

    :param obj_ref: 控制对象引用，如 simpleIOGenericIO/GGIO1.SPCSO1
    :param value:   控制值（bool/int/float/str，按服务器 ctlVal 类型）
    :param sbo:     True 时先 select 再 operate（SBO 模型）
    :param or_ident: 操作来源标识
    :param or_cat:  操作来源类别（3=bay-control 常用）
    :returns: 操作是否成功
    :raises MmsError: 服务错误
    """
    L = client._lib
    err = ctypes.c_int(0)
    ctl = L.ControlObjectClient_create(obj_ref.encode("utf-8"), client.con)
    if not ctl:
        raise MmsError(128, "创建控制对象失败（引用是否正确？）:%s" % obj_ref)
    mv = None
    try:
        L.ControlObjectClient_setOrigin(ctl, or_ident.encode("utf-8") or None, or_cat)
        L.ControlObjectClient_setInterlockCheck(ctl, 1 if interlock_check else 0)
        L.ControlObjectClient_setSynchroCheck(ctl, 1 if synchro_check else 0)

        if sbo:
            if not L.ControlObjectClient_select(ctl):
                raise MmsError(27, "SBO 选择(select)失败：对象可能已被其他客户端预留")

        mv = python_to_mms_value(value)
        ok = L.ControlObjectClient_operate(ctl, mv, 0)
        if not ok:
            raise MmsError(27, "操作(operate)被服务器拒绝")
        return True
    finally:
        if mv:
            L.MmsValue_delete(mv)
        L.ControlObjectClient_destroy(ctl)


def get_ctl_val_type(client, obj_ref):
    """查询控制对象的 ctlVal MMS 类型（用于界面提示可选值类型）"""
    L = client._lib
    ctl = L.ControlObjectClient_create(obj_ref.encode("utf-8"), client.con)
    if not ctl:
        raise MmsError(128, "无法创建控制对象：%s" % obj_ref)
    try:
        return L.ControlObjectClient_getCtlValType(ctl)
    finally:
        L.ControlObjectClient_destroy(ctl)
