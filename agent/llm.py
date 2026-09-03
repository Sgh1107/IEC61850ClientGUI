# -*- coding: utf-8 -*-
"""LLM 客户端：OpenAI 兼容 Chat Completions（urllib 实现，无第三方依赖）。

支持任意 OpenAI 兼容端点：OpenAI / DeepSeek / 通义 / Ollama / vLLM 等。
"""
import json
import urllib.request
import urllib.error


class LLMError(Exception):
    pass


class LLMClient(object):
    def __init__(self, base_url, api_key, model, timeout=120):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages, tools=None):
        """调用 chat/completions，返回 assistant 消息 dict。

        支持工具调用：返回的消息可能包含 tool_calls。
        """
        url = self.base_url + "/chat/completions"
        body = {"model": self.model, "messages": messages}
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        req = urllib.request.Request(
            url, data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + (self.api_key or "none")})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:500]
            raise LLMError("LLM HTTP %s：%s" % (e.code, detail))
        except urllib.error.URLError as e:
            raise LLMError("无法连接 LLM 服务：%s" % e.reason)
        except json.JSONDecodeError:
            raise LLMError("LLM 返回内容不是有效 JSON")
        try:
            return data["choices"][0]["message"]
        except (KeyError, IndexError):
            raise LLMError("LLM 响应格式异常：%s" % json.dumps(data)[:300])
