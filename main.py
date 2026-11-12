#!/usr/bin/env python3
"""WebSec Lab Agent 命令行入口。

用法示例：
  python main.py labs                    # 查看题目清单与就绪状态
  python main.py smoke                   # 无需 LLM/靶场账号的本地冒烟测试
  python main.py run --lab sqli_login_bypass --url https://xxxx.web-security-academy.net
  python main.py run --lab xxx --url ... --blind     # 盲测模式（不告知漏洞类型）
  python main.py eval --mode hint        # 批量评测（需先在 registry 填 lab_url）
  python main.py eval --mode blind
  python main.py ui                      # 启动回放界面
"""

import argparse
import os
import subprocess
import sys

import yaml

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

from agent.core import ReActAgent            # noqa: E402
from agent.llm import LLMClient, ScriptedLLM  # noqa: E402
from agent.prompts import build_system_prompt, build_task  # noqa: E402
from store.transcript import Transcript       # noqa: E402
from tools.builtin_tools import ToolBox       # noqa: E402
from tools.http_client import SafeHTTP        # noqa: E402


def load_config(path=None) -> dict:
    for p in (path,
              os.path.join(HERE, "config.yaml"),
              os.path.join(HERE, "config.example.yaml")):
        if p and os.path.exists(p):
            with open(p, encoding="utf-8") as f:
                return yaml.safe_load(f) or {}
    raise SystemExit("未找到配置文件，请复制 config.example.yaml 为 config.yaml")


def load_registry() -> list:
    with open(os.path.join(HERE, "labs", "registry.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or []


# ---------- 子命令 ----------
def cmd_labs(args):
    labs = load_registry()
    print(f"共 {len(labs)} 道题：\n")
    for l in labs:
        ready = "✅ 已填 lab_url" if l.get("lab_url") else "⬜ 待填 lab_url"
        print(f"  [{ready}] {l['id']:<22} 难度{l['difficulty']} {l['title_zh']}")
    print("\n使用: python main.py run --lab <id> --url <靶场实例地址>")


def build_mock_script(base_url: str) -> list:
    """--mock-llm 的剧本：对本地 mock 靶场走一遍完整 ReAct 流程。"""
    return [
        f'Thought: 先侦察登录页结构\n'
        f'Action: extract_page\n'
        f'Action Input: {{"url": "{base_url}/login"}}',

        f"Thought: 登录框可能存在 SQL 注入，用注释符绕过密码校验\n"
        f"Action: http_request\n"
        f'Action Input: {{"method": "POST", "url": "{base_url}/login", '
        f'"headers": {{"Content-Type": "application/x-www-form-urlencoded"}}, '
        f'"body": "username=administrator\'--&password=x"}}',

        "Thought: 利用成功的话靶场应已通关\n"
        "Action: check_solved\n"
        "Action Input: {}",

        'Thought: 结束\n'
        'Action: finish\n'
        'Action Input: {"summary": "利用 SQL 注释（--）闭合用户名并注释密码条件，免密登录 administrator"}',
    ]


def cmd_run(args):
    cfg = load_config(args.config)
    labs = load_registry()
    lab = next((l for l in labs if l["id"] == args.lab), None)
    if lab is None:
        raise SystemExit(f"未找到题目 {args.lab}，用 `python main.py labs` 查看清单")
    lab_url = (args.url or lab.get("lab_url") or "").rstrip("/")
    if not lab_url:
        raise SystemExit("该题目还没有靶场地址：请在 PortSwigger Launch lab 后用 --url 传入")

    mode = "blind" if args.blind else "hint"
    if args.mock_llm:
        llm = ScriptedLLM(build_mock_script(lab_url))
        print("（使用 ScriptedLLM 剧本模式，不需要 API key）")
    else:
        llm = LLMClient(cfg["llm"])
        print(f"LLM: {cfg['llm'].get('model')} @ {cfg['llm'].get('base_url')}")

    # mock 模式打的是本地靶场，自动放行本机回环地址
    allow_hosts = args.allow_host
    if args.mock_llm:
        allow_hosts = list(set(allow_hosts) | {"127.0.0.1", "localhost"})

    http = SafeHTTP(
        lab_url,
        cfg["safety"]["allowed_host_suffixes"],
        interval=cfg["agent"]["request_interval_sec"],
        max_requests=cfg["agent"]["max_http_requests"],
        allow_hosts=allow_hosts,
    )
    toolbox = ToolBox(http)
    transcript = Transcript.start(lab["id"], lab["title"],
                                  lab.get("category", ""), mode, lab_url)
    agent = ReActAgent(llm, toolbox, transcript, build_system_prompt(toolbox),
                       build_task(lab, lab_url, mode),
                       max_steps=cfg["agent"]["max_steps"])

    print(f"开始: {lab['id']} | 模式={mode} | 上限 {cfg['agent']['max_steps']} 步\n")
    result = agent.run()

    print("\n========== 结果 ==========")
    print("结果:", "✅ 通关" if result["solved"] else "❌ 未通关")
    print("总结:", result["summary"])
    print("指标:", result["metrics"])
    print("回放:", result["transcript_path"])
    print("查看: python main.py ui")


def cmd_eval(args):
    cfg = load_config(args.config)
    run_eval(cfg, mode=args.mode, only=args.lab)


def cmd_ui(args):
    app = os.path.join(HERE, "ui", "app.py")
    subprocess.call([sys.executable, "-m", "streamlit", "run", app])


def cmd_smoke(args):
    """本地端到端冒烟测试：mock 靶场 + ScriptedLLM，无需任何 API/账号。"""
    import tests.smoke_test as smoke
    sys.exit(smoke.main())


# ---------- 参数解析 ----------
def main():
    parser = argparse.ArgumentParser(description="WebSec Lab Agent —— 针对 PortSwigger 靶场的渗透测试 Agent")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("labs", help="查看题目清单")
    p.set_defaults(func=cmd_labs)

    p = sub.add_parser("run", help="对单个靶场运行 Agent")
    p.add_argument("--lab", required=True, help="题目 id（见 labs/registry.yaml）")
    p.add_argument("--url", help="靶场实例地址（Launch lab 后获得）")
    p.add_argument("--blind", action="store_true", help="盲测：不告知漏洞类型")
    p.add_argument("--mock-llm", action="store_true", help="使用内置剧本（冒烟演示，无需 API key）")
    p.add_argument("--allow-host", action="append", default=[],
                   help="额外允许的域名后缀（如本地测试 127.0.0.1）")
    p.add_argument("--config", help="配置文件路径（默认 config.yaml）")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("eval", help="批量评测")
    p.add_argument("--mode", choices=["hint", "blind"], default="hint")
    p.add_argument("--lab", action="append", help="只跑指定题目（可多次）")
    p.add_argument("--config")
    p.set_defaults(func=cmd_eval)

    p = sub.add_parser("ui", help="启动回放界面")
    p.set_defaults(func=cmd_ui)

    p = sub.add_parser("smoke", help="本地冒烟测试（无需 API key）")
    p.set_defaults(func=cmd_smoke)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
