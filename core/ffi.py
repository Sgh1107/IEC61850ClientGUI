# -*- coding: utf-8 -*-
"""ctypes FFI 层：加载 libiec61850 动态库并声明所有用到函数的签名。

本模块只负责"绑定"，不含任何业务逻辑。
"""
import ctypes
import os

_HERE = os.path.dirname(os.path.abspath(__file__))
_LIB = None


def _find_library():
    """按优先级查找 iec61850 动态库"""
    names = ["iec61850.dll", "libiec61850.so", "libiec61850.so.1", "libiec61850.dylib"]
    roots = [
        os.path.normpath(os.path.join(_HERE, "..")),                      # 程序目录
        os.path.normpath(os.path.join(_HERE, "..", "..")),                # IEDEX 顶层
        os.path.normpath(os.path.join(_HERE, "..", "..", "build_iec61850_vs2022", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6", "MMSFileUI")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6",
                                      "build_win_vs2022", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6",
                                      "build2", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6", "build", "src")),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for name in names:
            p = os.path.join(root, name)
            if os.path.isfile(p):
                return p
    for name in names:  # 最后再试系统搜索路径
        try:
            ctypes.CDLL(name)
            return name
        except OSError:
            pass
    return None


# ---------------------------------------------------------------------------
# 错误码 / 枚举常量（与 iec61850_client.h、iec61850_common.h 对应）
# ---------------------------------------------------------------------------
IED_ERROR_OK = 0

FC_ST, FC_MX, FC_SP, FC_SV, FC_CF, FC_DC, FC_SG, FC_SE, FC_SR, FC_IE = 0, 1, 2, 3, 4, 5, 6, 7, 8, 9
FC_BL, FC_EX, FC_CO, FC_US, FC_MS, FC_RP, FC_BR, FC_LG = 10, 11, 12, 13, 14, 15, 16, 17

FC_NAMES = {
    FC_ST: "ST", FC_MX: "MX", FC_SP: "SP", FC_SV: "SV", FC_CF: "CF", FC_DC: "DC",
    FC_SG: "SG", FC_SE: "SE", FC_SR: "SR", FC_IE: "IE", FC_BL: "BL", FC_EX: "EX",
    FC_CO: "CO", FC_US: "US", FC_MS: "MS", FC_RP: "RP", FC_BR: "BR", FC_LG: "LG",
}
FC_BY_NAME = {v: k for k, v in FC_NAMES.items()}

# ACSI class 枚举（iec61850_common.h: ACSI_CLASS_DATA_OBJECT = 0）
ACSI_DATA_OBJECT, ACSI_DATA_SET, ACSI_BRCB, ACSI_URCB, ACSI_LCB = 0, 1, 2, 3, 4
ACSI_LOG, ACSI_SGCB, ACSI_GOCB, ACSI_GSCB, ACSI_MSVCB, ACSI_USVCB = 5, 6, 7, 8, 9, 10

# MmsType 枚举（mms_common.h）
MMS_ARRAY, MMS_STRUCTURE, MMS_BOOLEAN = 0, 1, 2
MMS_BIT_STRING, MMS_INTEGER, MMS_UNSIGNED, MMS_FLOAT = 3, 4, 5, 6
MMS_OCTET_STRING, MMS_VISIBLE_STRING, MMS_STRING = 7, 8, 9
MMS_UTC_TIME = 14

# RCB elements mask（iec61850_client.h）
RCB_RPT_ID, RCB_RPT_ENA, RCB_RESV, RCB_DATSET = 1, 2, 4, 8
RCB_CONF_REV, RCB_OPT_FLDS, RCB_BUF_TM, RCB_SQ_NUM = 16, 32, 64, 128
RCB_TRG_OPS, RCB_INTG_PD, RCB_GI, RCB_PURGE_BUF = 256, 512, 1024, 2048
RCB_ENTRY_ID, RCB_TIME_OF_ENTRY, RCB_RESV_TMS, RCB_OWNER = 4096, 8192, 16384, 32768

# 触发条件 TRG_OPS 位
TRG_DATA_CHANGED, TRG_QUALITY_CHANGED, TRG_DATA_UPDATE, TRG_INTEGRITY = 1, 2, 4, 16

# ReasonForInclusion
REASON_NOT_INCLUDED = 0
REASON_DATA_CHANGE, REASON_QUALITY_CHANGE = 1, 2
REASON_DATA_UPDATE, REASON_INTEGRITY, REASON_GI, REASON_UNKNOWN = 3, 4, 5, 6

REASON_NAMES = {
    REASON_NOT_INCLUDED: "未包含", REASON_DATA_CHANGE: "数据变化",
    REASON_QUALITY_CHANGE: "品质变化", REASON_DATA_UPDATE: "数据更新",
    REASON_INTEGRITY: "完整性", REASON_GI: "总召", REASON_UNKNOWN: "未知",
}

# IedClientError 错误码含义（iec61850_client.h）
IED_ERROR_NAMES = {
    0: "成功", 1: "连接已关闭/失败", 2: "连接失败", 3: "服务响应超时",
    4: "无法连接到服务器", 5: "TCP 连接失败", 6: "已发送断开/中止请求",
    11: "访问被禁止(访问控制拒绝)", 12: "对象不存在", 13: "访问超时",
    21: "对象值类型无效", 22: "类型不匹配", 24: "访问结果未定义",
    26: "服务不支持", 27: "实例已被占用(如控制对象被预留)",
    28: "对象访问被暂时不可用", 29: "对象访问不允许",
    128: "未知错误",
}


def err_str(code):
    return IED_ERROR_NAMES.get(code, "错误码 %d" % code)



def load_library():
    """加载动态库并完成函数签名绑定（幂等）。
    候选路径逐个尝试，某个文件损坏/位数不符时自动跳过下一个。"""
    global _LIB
    if _LIB is not None:
        return _LIB

    names = ["iec61850.dll", "libiec61850.so", "libiec61850.so.1", "libiec61850.dylib"]
    last_err = None
    for root in _find_library_roots():
        for name in names:
            path = os.path.join(root, name)
            if not os.path.isfile(path):
                continue
            try:
                L = _LIB = ctypes.CDLL(path)
                _bind_functions(L)
                return L
            except OSError as e:
                last_err = (path, e)

    # 系统搜索路径兜底
    for name in names:
        try:
            L = _LIB = ctypes.CDLL(name)
            _bind_functions(L)
            return L
        except OSError as e:
            last_err = (name, e)

    raise OSError("未找到可加载的 iec61850 动态库！请先编译 libiec61850，"
                  "或将 iec61850.dll / libiec61850.so 放到程序目录下。(%s)"
                  % (last_err,))


def _find_library_roots():
    return [
        os.path.normpath(os.path.join(_HERE, "..")),                      # 程序目录
        os.path.normpath(os.path.join(_HERE, "..", "..", "build_iec61850_vs2022", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6", "MMSFileUI")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6",
                                      "build_win_vs2022", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6",
                                      "build2", "src", "Debug")),
        os.path.normpath(os.path.join(_HERE, "..", "..", "libiec61850-1.6", "build", "src")),
    ]


def _bind_functions(L):
    """给用到的函数设置 argtypes/restypes"""
    P = ctypes.c_void_p
    PD = ctypes.POINTER(ctypes.c_int)   # IedClientError*
    PB = ctypes.POINTER(ctypes.c_int)   # bool*
    CH = ctypes.c_char_p
    I = ctypes.c_int

    # ---- 连接 ----
    L.IedConnection_create.restype = P
    L.IedConnection_connect.argtypes = [P, PD, CH, I]
    for fn in ("IedConnection_abort", "IedConnection_release"):
        getattr(L, fn).argtypes = [P, PD]
    L.IedConnection_close.argtypes = [P]
    L.IedConnection_destroy.argtypes = [P]
    L.IedConnection_setConnectTimeout.argtypes = [P, ctypes.c_uint32]
    L.IedConnection_getState.argtypes = [P]
    L.IedConnection_getState.restype = I

    # ---- 模型浏览（返回 LinkedList<char*>）----
    browses = {
        "IedConnection_getServerDirectory": [P, PD, I],
        "IedConnection_getLogicalDeviceDirectory": [P, PD, CH],
        "IedConnection_getLogicalNodeDirectory": [P, PD, CH, I],
        "IedConnection_getDataDirectory": [P, PD, CH],
        "IedConnection_getDataDirectoryFC": [P, PD, CH],
        "IedConnection_getDataDirectoryByFC": [P, PD, CH, I],
        "IedConnection_getDataSetDirectory": [P, PD, CH, PB],
    }
    for fn, at in browses.items():
        f = getattr(L, fn)
        f.restype = P
        f.argtypes = at
    L.LinkedList_getNext.argtypes = [P]
    L.LinkedList_getNext.restype = P
    L.LinkedList_getData.argtypes = [P]
    L.LinkedList_getData.restype = P
    L.LinkedList_size.argtypes = [P]
    L.LinkedList_size.restype = I
    L.LinkedList_destroy.argtypes = [P]
    L.LinkedList_create.restype = P
    L.LinkedList_add.argtypes = [P, P]

    # ---- 读 / 写 ----
    L.IedConnection_readObject.argtypes = [P, PD, CH, I]
    L.IedConnection_readObject.restype = P
    L.IedConnection_writeObject.argtypes = [P, PD, CH, I, P]

    
    # ---- 数据集 ----
    L.IedConnection_readDataSetValues.argtypes = [P, PD, CH, P]
    L.IedConnection_readDataSetValues.restype = P
    L.ClientDataSet_getValues.argtypes = [P]
    L.ClientDataSet_getValues.restype = P
    L.ClientDataSet_destroy.argtypes = [P]
    L.IedConnection_writeDataSetValues.argtypes = [P, PD, CH, P, P]

    # ---- 报告 ----
    L.IedConnection_getRCBValues.argtypes = [P, PD, CH, P]
    L.IedConnection_getRCBValues.restype = P
    L.IedConnection_setRCBValues.argtypes = [P, PD, P, ctypes.c_uint32, I]
    L.IedConnection_installReportHandler.argtypes = [P, CH, CH, P, P]
    L.ClientReportControlBlock_create.argtypes = [CH]
    L.ClientReportControlBlock_create.restype = P
    L.ClientReportControlBlock_destroy.argtypes = [P]
    L.ClientReportControlBlock_setRptId.argtypes = [P, CH]
    L.ClientReportControlBlock_setDataSetReference.argtypes = [P, CH]
    L.ClientReportControlBlock_setRptEna.argtypes = [P, I]
    L.ClientReportControlBlock_setResv.argtypes = [P, I]
    L.ClientReportControlBlock_setTrgOps.argtypes = [P, I]
    L.ClientReportControlBlock_setIntgPd.argtypes = [P, ctypes.c_uint32]
    L.ClientReportControlBlock_setGI.argtypes = [P, I]
    for fn, rt in (("ClientReportControlBlock_getRptId", CH),
                   ("ClientReportControlBlock_getDataSetReference", CH)):
        getattr(L, fn).argtypes = [P]
        getattr(L, fn).restype = rt
    for fn in ("ClientReportControlBlock_getRptEna",
               "ClientReportControlBlock_getTrgOps",
               "ClientReportControlBlock_isBuffered"):
        getattr(L, fn).argtypes = [P]
        getattr(L, fn).restype = I
    for fn in ("ClientReportControlBlock_getIntgPd",
               "ClientReportControlBlock_getConfRev"):
        getattr(L, fn).argtypes = [P]
        getattr(L, fn).restype = ctypes.c_uint32

    L.ClientReport_getRcbReference.argtypes = [P]
    L.ClientReport_getRcbReference.restype = CH
    L.ClientReport_getRptId.argtypes = [P]
    L.ClientReport_getRptId.restype = CH
    L.ClientReport_getDataSetValues.argtypes = [P]
    L.ClientReport_getDataSetValues.restype = P
    L.ClientReport_getReasonForInclusion.argtypes = [P, I]
    L.ClientReport_getReasonForInclusion.restype = I
    L.ClientReport_getSeqNum.argtypes = [P]
    L.ClientReport_getSeqNum.restype = ctypes.c_uint16
    L.ClientReport_getTimestamp.argtypes = [P]
    L.ClientReport_getTimestamp.restype = ctypes.c_uint64

    
    # ---- 控制 ----
    L.ControlObjectClient_create.argtypes = [CH, P]
    L.ControlObjectClient_create.restype = P
    L.ControlObjectClient_destroy.argtypes = [P]
    L.ControlObjectClient_operate.argtypes = [P, P, ctypes.c_uint64]
    L.ControlObjectClient_operate.restype = I
    L.ControlObjectClient_select.argtypes = [P]
    L.ControlObjectClient_select.restype = I
    L.ControlObjectClient_cancel.argtypes = [P]
    L.ControlObjectClient_cancel.restype = I
    L.ControlObjectClient_setOrigin.argtypes = [P, CH, I]
    L.ControlObjectClient_setInterlockCheck.argtypes = [P, I]
    L.ControlObjectClient_setSynchroCheck.argtypes = [P, I]
    L.ControlObjectClient_getCtlValType.argtypes = [P]
    L.ControlObjectClient_getCtlValType.restype = I

    # ---- MmsValue ----
    L.MmsValue_getType.argtypes = [P]
    L.MmsValue_getType.restype = I
    L.MmsValue_printToBuffer.argtypes = [P, CH, I]
    L.MmsValue_printToBuffer.restype = CH
    L.MmsValue_getBoolean.argtypes = [P]
    L.MmsValue_getBoolean.restype = I
    L.MmsValue_toFloat.argtypes = [P]
    L.MmsValue_toFloat.restype = ctypes.c_float
    L.MmsValue_toInt64.argtypes = [P]
    L.MmsValue_toInt64.restype = ctypes.c_int64
    L.MmsValue_toString.argtypes = [P]
    L.MmsValue_toString.restype = CH
    L.MmsValue_getArraySize.argtypes = [P]
    L.MmsValue_getArraySize.restype = I
    L.MmsValue_getElement.argtypes = [P, I]
    L.MmsValue_getElement.restype = P
    L.MmsValue_newBoolean.argtypes = [I]
    L.MmsValue_newBoolean.restype = P
    L.MmsValue_newFloat.argtypes = [ctypes.c_float]
    L.MmsValue_newFloat.restype = P
    L.MmsValue_newIntegerFromInt64.argtypes = [ctypes.c_int64]
    L.MmsValue_newIntegerFromInt64.restype = P
    L.MmsValue_newVisibleString.argtypes = [CH]
    L.MmsValue_newVisibleString.restype = P
    L.MmsValue_delete.argtypes = [P]

    return L


def lib():
    """获取已绑定的动态库句柄（未加载则自动加载）"""
    return _LIB if _LIB is not None else load_library()
