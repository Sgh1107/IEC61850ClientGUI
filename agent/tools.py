# -*- coding: utf-8 -*-
"""Agent 工具层：把 core/ 的 IEC 61850 客户端能力包装为 LLM 可调用的工具
安全设计：
- operate_control 是唯一危险操作，dispatch 前必须经 confirm 回调人工确认
- read/write 前用模型缓存校验引用是否存在，防止 LLM 幻觉编造引用
"""
import threading

from core.connection import MmsError
from core import files as filesvc
from core.reports import ReportSubscription


def _schema(name, description, properties=None, required=None):
    props = {}
    for p_name, p_desc in (properties or []):
        props[p_name] = {"type": "string", "description": p_desc}
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": props,
                "required": required or [],
            },
        },
    }


TOOL_SCHEMAS = [
    _schema("list_model", "列出服务器上全部逻辑设备(LD)、逻辑节点(LN)和数据对象(DO)引用"),
    _schema("list_datasets", "列出服务器上全部数据集引用"),
    _schema("list_rcbs", "列出服务器上全部报告控制块(RCB)引用（RP=非缓存, BR=缓存）"),
    _schema("read_value", "读取一个数据属性的当前值",
            [("ref", "数据属性引用，如 GenericIO/GGIO1.AnIn1.mag.f"),
             ("fc", "功能约束，遥测用 MX，遥信用 ST，其他如 CF/SP/DC")],
            ["ref", "fc"]),
    _schema("write_value", "写一个数据属性的值",
            [("ref", "数据属性引用"), ("fc", "功能约束"),
             ("value", "要写入的值（文本形式）")],
            ["ref", "fc", "value"]),
    _schema("operate_control", "遥控操作（危险操作，需要用户确认）",
            [("ref", "控制对象引用，如 GenericIO/GGIO1.SPCSO1"),
             ("value", "控制值，如 true/false/1/0"),
             ("sbo", "是否使用 SBO（选择后操作）模型，默认 false")],
            ["ref", "value"]),
    _schema("watch_reports", "订阅一个报告控制块并收集一段时间内的报告",
            [("rcb_ref", "RCB 引用，如 GenericIO/LLN0.BRCB1"),
             ("seconds", "收集时长（秒），默认 10")],
            ["rcb_ref", "seconds"]),
    _schema("list_files", "列出服务器文件目录",
            [("dirname", "目录名，根目录留空")]),
]


class ToolDispatcher(object):
    """绑定到一个 Client 连接的工具执行器（所有 MMS 调用串行化）"""

    def __init__(self, client, confirm_cb=None, log_cb=None):
        self.client = client
        self.confirm_cb = confirm_cb      # 危险操作人工确认回调 confirm(text) -> bool
        self.log_cb = log_cb              # 可选日志回调 log(text)
        self._lock = threading.Lock()
        self._model_cache = None          # 服务器模型引用集合缓存

    # ------------------------------------------------------------------
    def _known_refs(self):
        if self._model_cache is None:
            self._model_cache = set(self.client.get_all_data_objects())
        return self._model_cache

    def _validate_ref(self, ref):
        refs = self._known_refs()
        base = ref
        if "." in base:
            base = base.split(".", 1)[0]
        base = base.split("/")[0] if "/" in base else base
        if base not in refs:
            raise MmsError(0, "引用 %s 未在服务器模型中找到（可能不存在）" % ref)

    def _run(self, fn):
        """串行化所有 MMS 调用（同一连接不能并发请求）"""
        with self._lock:
            return fn()

    def dispatch(self, name, args):
        """执行工具，返回 (结果文本, 是否成功)"""
        if not self.client.connected():
            return ("当前未连接 IED 服务器。请提示用户：先在主界面左上角输入服务器 IP 并点击"
                    "“连接”，然后重试该操作。", False)

        args = args or {}
        try:
            if name == "list_model":
                def work():
                    self._model_cache = None
                    return self.client.get_all_data_objects()
                refs = self._run(work)
                return ("共 %d 个数据对象引用：\n%s"
                        % (len(refs), "\n".join(refs)), True)

            if name == "list_datasets":
                dss = self._run(lambda: self.client.get_all_datasets())
                return ("共 %d 个数据集：\n%s"
                        % (len(dss), "\n".join(dss) or "(无)"), True)

            if name == "list_rcbs":
                rcbs = self._run(lambda: self.client.get_all_rcbs())
                return ("共 %d 个 RCB：\n%s"
                        % (len(rcbs), "\n".join(rcbs) or "(无)"), True)

            if name == "read_value":
                ref = args.get("ref", "")
                fc = args.get("fc", "MX")
                self._run(lambda: self._validate_ref(ref))
                val = self._run(lambda: self.client.read(ref, fc))
                return ("%s(%s) = %s" % (ref, fc, val), True)

            if name == "write_value":
                ref = args.get("ref", "")
                fc = args.get("fc", "")
                raw = args.get("value", "")
                self._run(lambda: self._validate_ref(ref))
                if isinstance(raw, str):
                    from core.mms_value import parse_text_value
                    try:
                        value = parse_text_value(raw)
                    except Exception:  # noqa: BLE001
                        value = raw
                else:
                    value = raw
                self._run(lambda: self.client.write(ref, fc, value))
                return ("写入成功：%s(%s) = %s" % (ref, fc, raw), True)

            if name == "operate_control":
                return self._operate(args)

            if name == "watch_reports":
                return self._watch_reports(args)

            if name == "list_files":
                dirname = args.get("dirname", "") or ""
                entries = self._run(lambda: filesvc.list_dir(self.client, dirname))
                lines = ["%s (%d B)" % (e.get("name", "?"), e.get("size", 0))
                         for e in entries]
                return ("共 %d 个文件：\n%s"
                        % (len(lines), "\n".join(lines) or "(空)"), True)

            return ("未知工具：%s" % name, False)
        except Exception as e:  # noqa: BLE001
            return ("工具执行失败：%s" % e, False)

    # ------------------------------------------------------------------
    def _operate(self, args):
        ref = args.get("ref", "")
        raw = args.get("value", "")
        sbo = str(args.get("sbo", "")).lower() in ("true", "1", "yes")
        self._run(lambda: self._validate_ref(ref))
        if self.confirm_cb:
            ok = self.confirm_cb("agent 请求遥控操作：%s = %s%s\n\n确认执行？"
                                 % (ref, raw, "（SBO）" if sbo else ""))
            if not ok:
                return ("用户拒绝执行该遥控操作", False)

        from core import control

        def work():
            control.operate(self.client, ref, raw, sbo=sbo)
            return "操作成功：%s = %s" % (ref, raw)

        self._model_cache = None
        return (self._run(work), True)

    # ------------------------------------------------------------------
    def _watch_reports(self, args):
        rcb_ref = args.get("rcb_ref", "")
        seconds = max(1, min(int(float(args.get("seconds", 10) or 10)), 120))

        self._run(lambda: self._validate_ref(rcb_ref))

        reports = []
        done = threading.Event()

        sub = self._run(lambda: ReportSubscription(
            self.client, rcb_ref, lambda info: reports.append(info)))
        self._run(lambda: sub.enable())

        def stop():
            try:
                self._run(lambda: sub.disable())
            except Exception:  # noqa: BLE001
                pass
            try:
                sub.destroy()
            except Exception:  # noqa: BLE001
                pass
            done.set()

        def worker():
            timer = threading.Timer(seconds, stop)
            timer.start()
            done.wait(seconds + 5)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(seconds + 10)

        lines = ["seq=%s 原因=%s 值=%s"
                 % (r.get("seq"), ",".join(r.get("reasons", [])),
                    " | ".join(r.get("texts", [])))
                 for r in reports]
        return ("共收到 %d 条报告：\n%s" % (len(reports), "\n".join(lines) or "(无)"), True)
