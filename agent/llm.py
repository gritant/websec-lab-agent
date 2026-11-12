"""LLM 客户端。

统一走 OpenAI 兼容的 /chat/completions 接口，因此同一份代码可接入：
OpenAI / 智谱 GLM / DeepSeek / Qwen / 本地 Ollama（http://localhost:11434/v1）。
"""

import os

import requests


class LLMError(RuntimeError):
    pass


class LLMClient:
    def __init__(self, cfg: dict):
        self.base_url = (cfg.get("base_url") or "").rstrip("/")
        self.api_key = cfg.get("api_key") or os.environ.get("LLM_API_KEY", "")
        self.model = cfg.get("model", "gpt-4o-mini")
        self.temperature = cfg.get("temperature", 0.2)
        self.max_tokens = cfg.get("max_tokens", 1024)
        self.timeout = cfg.get("timeout_sec", 120)
        self.calls = 0
        if not self.base_url:
            raise LLMError("配置缺少 llm.base_url（参考 config.example.yaml）")

    def chat(self, messages: list) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            resp = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
        except requests.RequestException as exc:
            raise LLMError(f"LLM 请求失败: {exc}") from exc
        if resp.status_code != 200:
            raise LLMError(f"LLM 返回 {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        try:
            content = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError) as exc:
            raise LLMError(f"LLM 响应格式异常: {str(data)[:300]}") from exc
        self.calls += 1
        return content


class ScriptedLLM:
    """冒烟测试用：按剧本依次返回预设回复，不依赖任何 API。"""

    def __init__(self, scripted: list):
        self.scripted = list(scripted)
        self.calls = 0

    def chat(self, messages: list) -> str:
        if not self.scripted:
            raise AssertionError("ScriptedLLM 剧本已耗尽，而 Agent 仍未结束 —— 请检查流程")
        self.calls += 1
        return self.scripted.pop(0)
