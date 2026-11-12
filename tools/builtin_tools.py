"""Agent 工具箱。

每个工具返回 {"observation": 给模型看的文本, "traffic": 对应的HTTP流量(可空)}。
"""

import json

from tools.recon import summarize_html

OBS_BODY_LIMIT = 3000  # 给模型的响应体截断长度，防止撑爆上下文

SOLVED_BANNER = "Congratulations, you solved the lab!"


class ToolBox:
    def __init__(self, http):
        self.http = http
        self.notes = []
        self._tools = {
            "http_request": self._tool_http_request,
            "extract_page": self._tool_extract_page,
            "check_solved": self._tool_check_solved,
            "note": self._tool_note,
        }

    # ---------- 给提示词的工具说明 ----------
    def specs(self) -> str:
        return "\n".join([
            "- http_request: 发送 HTTP 请求并返回状态码与响应体。"
            '参数: {"method": "GET 或 POST", "url": "完整URL或相对路径", '
            '"headers": {"Content-Type": "..."}, "body": "POST数据(可选)"}',
            "- extract_page: 请求页面并提取标题/表单/链接/URL参数/HTML注释（侦察首选）。"
            '参数: {"url": "完整URL或相对路径"}',
            "- check_solved: 检查靶场是否已通关。"
            "参数: {}",
            "- note: 记录一条测试发现。"
            '参数: {"text": "..."}',
            "- finish: 结束任务。"
            '参数: {"summary": "一句话总结"}',
        ])

    # ---------- 调度 ----------
    def execute(self, name: str, args: dict) -> dict:
        tool = self._tools.get(name)
        if tool is None:
            return {"observation": f"未知工具: {name}。可用工具: {', '.join(self._tools)}",
                    "traffic": None}
        try:
            return tool(args or {})
        except Exception as exc:  # 工具异常转成观察文本，让 Agent 自行调整
            return {"observation": f"工具执行出错: {type(exc).__name__}: {exc}",
                    "traffic": None}

    # ---------- 工具实现 ----------
    def _tool_http_request(self, args):
        method = str(args.get("method", "GET")).upper()
        url = self.http._resolve(str(args.get("url", "")))
        headers = args.get("headers") or {}
        body = args.get("body")
        result = self.http.request(method, url, headers=headers, data=body)
        obs = f"HTTP {result['status']}  {url}\n\n{result['body'][:OBS_BODY_LIMIT]}"
        return {"observation": obs, "traffic": self.http.traffic[-1]}

    def _tool_extract_page(self, args):
        url = self.http._resolve(str(args.get("url", "")))
        result = self.http.request("GET", url)
        summary = summarize_html(result["body"])
        summary["status"] = result["status"]
        summary["url"] = url
        obs = json.dumps(summary, ensure_ascii=False, indent=2)[:OBS_BODY_LIMIT]
        return {"observation": obs, "traffic": self.http.traffic[-1]}

    def _tool_check_solved(self, args):
        result = self.http.request("GET", self.http.base_url + "/")
        solved = SOLVED_BANNER in result["body"]
        obs = json.dumps({"solved": solved, "url": self.http.base_url + "/"},
                         ensure_ascii=False)
        return {"observation": obs, "traffic": self.http.traffic[-1]}

    def _tool_note(self, args):
        text = str(args.get("text", ""))[:500]
        self.notes.append(text)
        return {"observation": f"已记录: {text}", "traffic": None}
