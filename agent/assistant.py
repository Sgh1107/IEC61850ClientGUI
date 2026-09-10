# -*- coding: utf-8 -*-
"""Agent 会话：LLM 对话 + 工具调用循环
用法（在后台线程中调用）：
    session = AgentSession(llm, dispatcher)
    session.on_tool = lambda name, args, result: ...   # 工具调用通知
    answer = session.chat("读一下 AnIn1 的值")           # 返回最终回答
"""
import json

from .llm import LLMClient, LLMError          # noqa: F401  (保持原导入结构)
from .tools import TOOL_SCHEMAS, ToolDispatcher  # noqa: F401

SYSTEM_PROMPT = (
    "你是一个 IEC 61850 电力系统客户端助手，可以通过工具操作一个正在运行的 "
    "IEC 61850 客户端连接（浏览模型、读值、写值、订阅报告、控制操作、文件服务）。\n"
    "规则：\n"
    "1. 涉及具体引用时，先用 list_model/list_datasets/list_rcbs 查询服务器真实模型，"
    "不要凭空猜测引用名。\n"
    "2. 读遥测用 read_value(fc='MX')，遥信用 fc='ST'。\n"
    "3. operate_control 是遥控操作，涉及一次设备动作，调用前必须向用户说明并确认。\n"
    "4. 用简洁的中文回答，并给出你读取到的具体数值。\n"
    "5. 工具返回错误时如实告知用户，不要编造结果。"
)


class AgentSession(object):
    """一次多轮对话会话（含工具调用循环）"""

    def __init__(self, llm, dispatcher):
        self.llm = llm
        self.dispatcher = dispatcher
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.on_tool = None      # callback(name, args_dict, result_text)
        self.on_status = None    # callback(status_text)

    def reset(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def chat(self, user_text):
        """发送用户消息并循环处理工具调用，返回最终回答文本（阻塞）"""
        self.history.append({"role": "user", "content": user_text})

        for _ in range(20):   # 工具调用轮数上限，防止死循环
            if self.on_status:
                self.on_status("AI 思考中…")
            resp = self.llm.chat(self.history, tools=TOOL_SCHEMAS)
            msg = resp["choices"][0]["message"]

            calls = msg.get("tool_calls") or []
            if not calls:
                content = msg.get("content") or "(无内容)"
                self.history.append({"role": "assistant", "content": content})
                if self.on_status:
                    self.on_status("就绪")
                return content

            # assistant 消息（含 tool_calls）必须原样回传
            self.history.append(msg)
            for call in calls:
                fn = call.get("function", {})
                name = fn.get("name", "")
                raw_args = fn.get("arguments") or "{}"
                try:
                    args = json.loads(raw_args)
                except json.JSONDecodeError:
                    args = {}
                if self.on_status:
                    self.on_status("执行工具：%s …" % name)
                result, ok = self.dispatcher.dispatch(name, args)
                if self.on_tool:
                    self.on_tool(name, args, (result, ok))
                self.history.append({
                    "role": "tool",
                    "tool_call_id": call.get("id", ""),
                    "content": result,
                })

        return "工具调用轮数已达上限，请换个问法或重试。"
