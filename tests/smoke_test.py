"""端到端冒烟测试（无需 LLM API、无需 PortSwigger 账号）。

流程：
1. 在线程里启动本地 mock 靶场（tests/mock_lab.py）
2. 用 ScriptedLLM 按剧本走一遍完整 ReAct 流程
3. 校验通关判定与运行记录落盘

运行：python main.py smoke
"""

import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)

from agent.core import ReActAgent                      # noqa: E402
from agent.llm import ScriptedLLM                      # noqa: E402
from agent.prompts import build_system_prompt, build_task   # noqa: E402
from store.transcript import Transcript                # noqa: E402
from tests.mock_lab import app, STATE                  # noqa: E402
from tools.builtin_tools import ToolBox                # noqa: E402
from tools.http_client import SafeHTTP                 # noqa: E402

BASE_URL = "http://127.0.0.1:5050"


def start_mock_server():
    thread = threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=5050, debug=False,
                               use_reloader=False),
        daemon=True,
    )
    thread.start()
    time.sleep(1.0)  # 等服务起来


def main() -> int:
    STATE["solved"] = False
    start_mock_server()

    scripted = [
        f"Thought: 先侦察登录页\n"
        f"Action: extract_page\n"
        f'Action Input: {{"url": "{BASE_URL}/login"}}',

        f"Thought: 登录框可能存在 SQL 注入，尝试注释密码条件\n"
        f"Action: http_request\n"
        f'Action Input: {{"method": "POST", "url": "{BASE_URL}/login", '
        f'"headers": {{"Content-Type": "application/x-www-form-urlencoded"}}, '
        f'"body": "username=administrator\'--&password=x"}}',

        "Thought: 利用应该已生效\n"
        "Action: check_solved\n"
        "Action Input: {}",

        'Thought: 已通关\n'
        'Action: finish\n'
        'Action Input: {"summary": "SQL 注释绕过登录"}',
    ]

    llm = ScriptedLLM(scripted)
    http = SafeHTTP(
        BASE_URL,
        allowed_suffixes=["web-security-academy.net", "portswigger-lab.net"],
        interval=0.05,
        allow_hosts=["127.0.0.1"],
    )
    toolbox = ToolBox(http)
    lab = {"id": "mock_sqli_login", "title": "Mock SQLi login bypass",
           "title_zh": "模拟：SQL 注入登录绕过", "category": "sqli"}
    transcript = Transcript.start(lab["id"], lab["title"], lab["category"],
                                  mode="mock", base_url=BASE_URL)
    agent = ReActAgent(llm, toolbox, transcript, build_system_prompt(toolbox),
                       build_task(lab, BASE_URL, "hint"), max_steps=10)
    result = agent.run()

    print("\n========== 冒烟测试 ==========")
    print("通关:", result["solved"])
    print("总结:", result["summary"])
    print("指标:", result["metrics"])
    print("记录:", result["transcript_path"])

    assert result["solved"], "❌ 未通关 —— Agent 链路有问题"
    assert result["metrics"]["http_requests"] >= 3, "HTTP 流量记录不完整"
    assert os.path.exists(result["transcript_path"]), "运行记录未落盘"
    print("\n✅ 冒烟测试通过：ReAct 循环 / 工具箱 / 白名单 / 通关检测 / 记录落盘 全部正常")
    return 0


if __name__ == "__main__":
    sys.exit(main())
