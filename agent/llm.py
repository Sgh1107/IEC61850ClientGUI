# -*- coding: utf-8 -*-
"""LLM 客户端：OpenAI 兼容 Chat Completions（urllib 实现，无第三方依赖）
支持任意 OpenAI 兼容端点：OpenAI / DeepSeek / 通义 / Ollama / vLLM 等
"""
import json
import urllib.request
import urllib.error


class LLMError(Exception):
    """LLM 调用失败（网络 / HTTP / 响应格式错误）"""


class LLMClient(object):
    """一个 OpenAI 兼容端点的会话客户端（无状态，可多线程复用）"""

    def __init__(self, base_url, api_key="", model="", timeout=60):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def chat(self, messages, tools=None, tool_choice=None):
        """发送 Chat Completions 请求，返回解析后的 JSON 响应 dict。

        :param messages:    OpenAI 格式消息列表（含 tool/assistant 消息）
        :param tools:       工具 schema 列表（可选）
        :param tool_choice: 默认 'auto'，可传 'none'
        """
        payload = {
            "model": self.model,
            "messages": messages,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = tool_choice or "auto"

        url = self.base_url + "/chat/completions"
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + (self.api_key or ""),
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            return json.loads(body)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = e.read().decode("utf-8", "replace")[:300]
            except Exception:  # noqa: BLE001
                pass
            raise LLMError("LLM HTTP %d：%s" % (e.code, detail or e.reason))
        except urllib.error.URLError as e:
            raise LLMError("无法连接 LLM 服务：%s" % e.reason)
        except (json.JSONDecodeError, KeyError, IndexError):
            raise LLMError("LLM 响应格式无法解析")

    def list_models(self):
        """GET /models 获取可用模型 id 列表"""
        url = self.base_url + "/models"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": "Bearer " + (self.api_key or ""),
            },
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", "replace")
            data = json.loads(body)
        except urllib.error.HTTPError as e:
            raise LLMError("获取模型列表 HTTP %d：%s" % (e.code, e.reason))
        except urllib.error.URLError as e:
            raise LLMError("无法连接 LLM 服务：%s" % e.reason)
        except json.JSONDecodeError:
            raise LLMError("模型列表响应不是有效 JSON")

        items = data.get("data") or []
        ids = sorted(m.get("id", "") for m in items if isinstance(m, dict))
        if not ids:
            raise LLMError("服务端未返回任何模型（可能不支持 /models 接口）")
        return ids
