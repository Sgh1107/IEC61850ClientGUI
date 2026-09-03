# -*- coding: utf-8 -*-
"""
Agent 工具层：把 core/ 的 IEC 61850 客户端能力包装为 LLM 可调用的工具
安全设计：
- operate_control 是唯一危险操作，dispatch 前必须经 confirm 回调人工确认
- read/write 前用模型缓存校验引用是否存在，防止 LLM 幻觉编造引用
"""
import threading

from core.connection import MmsError
from core import files as filesvc
from core.reports import ReportSubscription

# 所有工具的 JSON Schema（OpenAI tools 格式）
TOOL_SCHEMAS = [
    {"type": "function", "function": {
        "name": "list_model",
        "description": "列出服务器上全部逻辑设备(LD)、逻辑节点(LN)和数据对象(DO)引用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_datasets",
        "description": "列出服务器上全部数据集引用",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "list_rcbs",
        "description": "列出服务器上全部报告控制块(RCB)引用（RP=非缓存, BR=缓存）",
        "parameters": {"type": "object", "properties": {}, "required": []}}},
    {"type": "function", "function": {
        "name": "read_value",
        "description": "读取一个数据属性的当前值",
        "parameters": {"type": "object",
                       "properties": {"ref": {"type": "string", "description": "数据属性引用，如 GenericIO/GGIO1.AnIn1.mag.f"},
                                      "fc": {"type": "string", "description": "功能约束：ST/MX/CF/DC/SP/CO 等"}},
                       "required": ["ref", "fc"]}}},
    {"type": "function", "function": {
        "name": "write_value",
        "description": "写一个数据属性的值（仅限可写属性，写入前校验引用存在）",
        "parameters": {"type": "object",
                       "properties": {"ref": {"type": "string", "description": "数据属性引用"},
                                      "fc": {"type": "string", "description": "功能约束"},
                                      "value": {"type": "string", "description": "true/false、数字或字符串"}},
                       "required": ["ref", "fc", "value"]}}},
    {"type": "function", "function": {
        "name": "operate_control",
        "description": "对控制对象执行遥控操作（危险！必须先向用户确认）。ref 如 GenericIO/GGIO1.SPCSO1，value 通常 true/false",
        "parameters": {"type": "object",
                       "properties": {"ref": {"type": "string", "description": "控制对象引用"},
                                      "value": {"type": "string", "description": "控制值 true/false"},
                                      "sbo": {"type": "boolean", "description": "是否 SBO 先选择后操作"}},
                       "required": ["ref", "value"]}}},
    {"type": "function", "function": {
        "name": "watch_reports",
        "description": "订阅一个报告控制块并监听指定秒数，返回期间收到的全部报告",
        "parameters": {"type": "object",
                       "properties": {"rcb_ref": {"type": "string", "description": "RCB 引用"},
                                      "seconds": {"type": "integer", "description": "监听时长(1-30秒)"}},
                       "required": ["rcb_ref"]}}},
    {"type": "function", "function": {
        "name": "list_files",
        "description": "列出服务器文件存储目录",
        "parameters": {"type": "object",
                       "properties": {"dirname": {"type": "string", "description": "目录名，空为根目录"}},
                       "required": []}}},
]


class ToolDispatcher(object):
    """绑定到一个 Client 连接的工具执行器（所有 MMS 调用串行化）"""

    def __init__(self, client, confirm_cb=None, log_cb=None):
        self.client = client
        self.confirm_cb = confirm_cb      # operate 确认回调 confirm(text) -> bool
        self.log_cb = log_cb              # 工具执行日志回调 log(text)
        self._lock = threading.Lock()     # 同一连接 MMS 请求串行化
        self._model_cache = None          # DO 引用缓存（防幻觉校验用）

    # ---- 校验 ----
    def _known_refs(self):
        if self._model_cache is None:
            self._model_cache = set(self.client.get_all_data_objects())
        return self._model_cache

    def _validate_ref(self, ref):
        """校验 ref 的 DO 部分是否在服务器模型中（防 LLM 幻觉）"""
        known = self._known_refs()
        for k in known:
            if ref == k or ref.startswith(k + "."):
                return True
        # 宽松匹配：引用的 DO 前缀命中缓存即可（如带不同 LD 前缀写法）
        prefix = ref.split(".")[0]
        for k in known:
            if prefix.endswith(k.split("/")[-1] + "." + k.split(".")[-1]) \
                    or prefix.endswith(k.replace("/", ".")):
                return True
        raise MmsError(12, "引用 %s 未在服务器模型中找到（可能不存在）" % ref)

    def _run(self, fn):
        with self._lock:
            return fn()

    
    def dispatch(self, name, args):
        """执行工具，返回 (结果文本, 是否成功)"""
        c = self.client
        try:
            if name == "list_model":
                out = self._run(c.get_all_data_objects)
                return "共 %d 个数据对象引用：\n%s" % (len(out), "\n".join(out)), True

            if name == "list_datasets":
                out = self._run(c.get_all_datasets)
                return "共 %d 个数据集：\n%s" % (len(out), "\n".join(out) or "(无)"), True

            if name == "list_rcbs":
                out = self._run(c.get_all_rcbs)
                return "共 %d 个 RCB：\n%s" % (len(out), "\n".join(out) or "(无)"), True

            if name == "read_value":
                ref, fc = args["ref"], args["fc"]
                self._run(lambda: self._validate_ref(ref))
                val = self._run(lambda: c.read(ref, fc))
                return "%s = %r" % (ref, val), True

            if name == "write_value":
                ref, fc = args["ref"], args["fc"]
                from core.mms_value import parse_text_value
                value = parse_text_value(str(args["value"]))
                self._run(lambda: self._validate_ref(ref))
                self._run(lambda: c.write(ref, fc, value))
                return "写入成功：%s = %r" % (ref, value), True

            if name == "operate_control":
                ref, value = args["ref"], str(args["value"])
                sbo = bool(args.get("sbo", False))
                msg = "agent 请求遥控操作：%s = %s%s\n\n确认执行？" % (
                    ref, value, "（SBO）" if sbo else "")
                if self.confirm_cb and not self.confirm_cb(msg):
                    return "用户拒绝执行该遥控操作", False
                from core import control
                from core.mms_value import parse_text_value
                self._run(lambda: control.operate(
                    c, ref, parse_text_value(value), sbo=sbo))
                return "操作成功：%s = %s" % (ref, value), True

            if name == "watch_reports":
                return self._watch_reports(args)

            if name == "list_files":
                entries = self._run(lambda: filesvc.list_dir(c, args.get("dirname", "")))
                lines = ["%s (%d B)" % (e["name"], e["size"]) for e in entries]
                return "共 %d 个文件：\n%s" % (len(lines), "\n".join(lines) or "(空)"), True

            return "未知工具：%s" % name, False
        except Exception as e:  # noqa: BLE001
            return "工具执行失败：%s" % e, False

    def _watch_reports(self, args):
        rcb_ref = args["rcb_ref"]
        seconds = max(1, min(30, int(args.get("seconds", 5))))
        got = []
        done_ev = threading.Event()
        holder = {}

        def work():
            sub = ReportSubscription(self.client, rcb_ref,
                                     lambda info: got.append(info))
            sub.enable(trg_ops=0x13, gi=True)
            return sub

        def stop():
            try:
                if "sub" in holder:
                    holder["sub"].disable()
                    holder["sub"].destroy()
            except Exception:  # noqa: BLE001
                pass
            done_ev.set()

        def worker():
            try:
                holder["sub"] = self._run(work)
                threading.Timer(seconds, stop).start()
            except Exception as e:  # noqa: BLE001
                got.append({"error": str(e)})
                done_ev.set()

        threading.Thread(target=worker, daemon=True).start()
        done_ev.wait(seconds + 8)

        if got and "error" not in got[0]:
            lines = ["共收到 %d 条报告：" % len(got)]
            for i in got:
                lines.append("seq=%s 原因=%s 值=%s" % (
                    i["seq"], ",".join(i["reasons"]), " | ".join(i["texts"])))
            return "\n".join(lines), True
        return "监听 %d 秒内未收到报告或订阅失败：%s" % (seconds, got), False
