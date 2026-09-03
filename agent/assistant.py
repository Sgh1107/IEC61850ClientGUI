# -*- coding: utf-8 -*-
"""Agent 会话：LLM 对话 + 工具调用循环。

用法（在后台线程中调用）：
    session = AgentSession(llm, dispatcher)
    session.on_tool = lambda name, args, result: ...   # 工具调用通知
    answer = session.chat("读一下 AnIn1 的值")           # 返回最终回答
"""
import json

from .llm import LLMClient, LLMError
from .tools import TOOL_SCHEMAS, ToolDispatcher

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
    def __init__(self, llm, dispatcher):
        self.llm = llm
        self.dispatcher = dispatcher
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]
        self.on_tool = None          # on_tool(name, args, result_text, ok)
        self.on_status = None        # on_status(text)

    def reset(self):
        self.history = [{"role": "system", "content": SYSTEM_PROMPT}]

    def chat(self, user_text, max_rounds=8):
        """处理一轮用户输入，返回最终回答文本。工具循环最多 max_rounds 轮。"""
        self.history.append({"role": "user", "content": user_text})

        for _ in range(max_rounds):
            if self.on_status:
                self.on_status("AI 思考中…")
            msg = self.llm.chat(self.history, tools=TOOL_SCHEMAS)
            self.history.append(msg)

            tool_calls = msg.get("tool_calls")
            if not tool_calls:
                content = msg.get("content") or "(无内容)"
                if self.on_status:
                    self.on_status("就绪")
                return content

            # 执行全部工具调用
            for tc in tool_calls:
                fn = tc.get("function", {})
                name = fn.get("name", "")
                try:
                    args = json.loads(fn.get("arguments") or "{}")
                except json.JSONDecodeError:
                    args = {}
                if self.on_status:
                    self.on_status("执行工具：%s …" % name)
                result, ok = self.dispatcher.dispatch(name, args)
                if self.on_tool:
                    self.on_tool(name, args, result, ok)
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.get("id", ""),
                    "content": result,
                })

        return "（达到最大工具调用轮数，已停止。请缩小问题范围后重试。）"
