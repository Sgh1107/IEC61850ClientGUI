# -*- coding: utf-8 -*-
"""
报告(RCB)订阅封装
用法：
    sub = ReportSubscription(client, rcb_ref, rpt_id, callback)
    sub.enable(trg_ops=..., intg_pd=...)   # 启用报告
    sub.disable()                          # 停止并注销回调

callback 签名: callback(info: dict)
    info = {"rcb": 引用, "rpt_id": 报告ID, "seq": 序列号, "ts": 毫秒时间戳,
            "values": [Python值...], "texts": [文本...], "reasons": [原因...]}
"""
import ctypes

from . import ffi
from .connection import MmsError
from .mms_value import mms_value_to_python, mms_value_to_text

_REPORT_CB = ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)


def _s(b):
    """c_char_p 返回值(bytes) -> str"""
    if isinstance(b, bytes):
        return b.decode("utf-8", "replace")
    return b or ""


class ReportSubscription(object):
    """一个 RCB 的订阅会话"""

    def __init__(self, client, rcb_ref, callback):
        self.client = client
        self.rcb_ref = rcb_ref
        self.callback = callback          # Python 回调（经队列转发到 UI）
        self.err = ctypes.c_int(0)
        L = client._lib

        self._cb_ref = _REPORT_CB(self._on_report)   # 防止被 GC
        self.rcb = L.IedConnection_getRCBValues(
            client.con, ctypes.byref(self.err), rcb_ref.encode("utf-8"), None)
        if self.err.value != ffi.IED_ERROR_OK or not self.rcb:
            raise MmsError(self.err.value or 128,
                           "读取 RCB 失败：%s" % ffi.err_str(self.err.value or 128))

        # 安装原生回调（rptId 用 RCB 里配置的，避免覆盖）
        self.rpt_id = _s(L.ClientReportControlBlock_getRptId(self.rcb))
        L.IedConnection_installReportHandler(
            client.con, rcb_ref.encode("utf-8"),
            self.rpt_id.encode("utf-8") if isinstance(self.rpt_id, str) else self.rpt_id,
            self._cb_ref, None)

    # ---- 原生回调（库的后台线程调用，只做数据提取，不做 UI） ----
    def _on_report(self, _param, report):
        if not report:
            return
        L = self.client._lib
        vals_ptr = L.ClientReport_getDataSetValues(report)
        values, texts, reasons = [], [], []
        if vals_ptr:
            n = L.MmsValue_getArraySize(vals_ptr)
            for i in range(n):
                el = L.MmsValue_getElement(vals_ptr, i)
                values.append(mms_value_to_python(el))
                texts.append(mms_value_to_text(el))
                r = L.ClientReport_getReasonForInclusion(report, i)
                reasons.append(ffi.REASON_NAMES.get(r, str(r)))
        info = {
            "rcb": _s(L.ClientReport_getRcbReference(report)) or self.rcb_ref,
            "rpt_id": _s(L.ClientReport_getRptId(report)) or self.rpt_id,
            "seq": L.ClientReport_getSeqNum(report),
            "ts": L.ClientReport_getTimestamp(report),
            "values": values, "texts": texts, "reasons": reasons,
        }
        try:
            self.callback(info)
        except Exception:  # noqa: BLE001
            pass

    # ---- RCB 操作 ----
    def enable(self, trg_ops=ffi.TRG_DATA_CHANGED | ffi.TRG_QUALITY_CHANGED | ffi.TRG_INTEGRITY,
               intg_pd=0, gi=False):
        """设置触发条件并使能报告"""
        L = self.client._lib
        L.ClientReportControlBlock_setTrgOps(self.rcb, int(trg_ops))
        if intg_pd:
            L.ClientReportControlBlock_setIntgPd(self.rcb, int(intg_pd))
        L.ClientReportControlBlock_setGI(self.rcb, 1 if gi else 0)
        L.ClientReportControlBlock_setRptEna(self.rcb, 1)
        mask = ffi.RCB_TRG_OPS | ffi.RCB_RPT_ENA
        if intg_pd:
            mask |= ffi.RCB_INTG_PD
        if gi:
            mask |= ffi.RCB_GI
        self.err.value = 0
        L.IedConnection_setRCBValues(self.client.con, ctypes.byref(self.err),
                                     self.rcb, mask, 1)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)

    def trigger_gi(self):
        """总召（触发一次完整性报告）"""
        L = self.client._lib
        L.ClientReportControlBlock_setGI(self.rcb, 1)
        self.err.value = 0
        L.IedConnection_setRCBValues(self.client.con, ctypes.byref(self.err),
                                     self.rcb, ffi.RCB_GI, 1)
        if self.err.value != ffi.IED_ERROR_OK:
            raise MmsError(self.err.value)

    def disable(self):
        L = self.client._lib
        L.ClientReportControlBlock_setRptEna(self.rcb, 0)
        self.err.value = 0
        L.IedConnection_setRCBValues(self.client.con, ctypes.byref(self.err),
                                     self.rcb, ffi.RCB_RPT_ENA, 1)

    def destroy(self):
        if self.rcb:
            self.client._lib.ClientReportControlBlock_destroy(self.rcb)
            self.rcb = None

    # ---- 元信息（界面显示用） ----
    @property
    def info(self):
        L = self.client._lib
        ds = _s(L.ClientReportControlBlock_getDataSetReference(self.rcb))
        return {
            "rcb": self.rcb_ref,
            "rpt_id": self.rpt_id,
            "dat_set": ds,
            "buffered": bool(L.ClientReportControlBlock_isBuffered(self.rcb)),
            "trg_ops": L.ClientReportControlBlock_getTrgOps(self.rcb),
            "intg_pd": L.ClientReportControlBlock_getIntgPd(self.rcb),
            "conf_rev": L.ClientReportControlBlock_getConfRev(self.rcb),
        }
