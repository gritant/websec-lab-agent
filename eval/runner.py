"""批量评测：对注册表中已填 lab_url 的题目逐题运行 Agent，输出解出率报告。

典型用法（对比实验）：
    python main.py eval --mode hint    # Agent 知道题目考察的漏洞类型
    python main.py eval --mode blind   # 盲测：只给 URL，自行侦察判断
然后对比两份报告中的解出率/步数/请求数，即为项目的核心实验结论。
"""

import csv
import os
import time

import yaml

from agent.core import ReActAgent
from agent.llm import LLMClient
from agent.prompts import build_system_prompt, build_task
from store.transcript import Transcript
from tools.builtin_tools import ToolBox
from tools.http_client import SafeHTTP

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_registry() -> list:
    with open(os.path.join(HERE, "labs", "registry.yaml"), encoding="utf-8") as f:
        return yaml.safe_load(f) or []


def run_eval(cfg: dict, mode="hint", only=None, runs_dir=None):
    runs_dir = runs_dir or os.path.join(HERE, "runs")
    os.makedirs(runs_dir, exist_ok=True)

    labs = [l for l in load_registry() if l.get("lab_url")]
    if only:
        labs = [l for l in labs if l["id"] in only]
    if not labs:
        print("注册表中没有可运行的题目 —— 请先在 labs/registry.yaml 填入 lab_url，"
              "或运行时用 --url 传入（单题模式: python main.py run）")
        return

    print(f"开始评测: 模式={mode}, 题数={len(labs)}")
    results = []
    for i, lab in enumerate(labs, 1):
        print(f"\n[{i}/{len(labs)}] {lab['id']}  {lab['title']}")
        llm = LLMClient(cfg["llm"])
        http = SafeHTTP(
            lab["lab_url"],
            cfg["safety"]["allowed_host_suffixes"],
            interval=cfg["agent"]["request_interval_sec"],
            max_requests=cfg["agent"]["max_http_requests"],
        )
        toolbox = ToolBox(http)
        transcript = Transcript.start(lab["id"], lab["title"],
                                      lab.get("category", ""), mode,
                                      lab["lab_url"], runs_dir)
        agent = ReActAgent(llm, toolbox, transcript,
                           build_system_prompt(toolbox),
                           build_task(lab, lab["lab_url"], mode),
                           max_steps=cfg["agent"]["max_steps"])
        try:
            r = agent.run()
        except Exception as exc:
            r = {"solved": False, "summary": f"运行异常: {exc}",
                 "metrics": {}, "transcript_path": ""}
        flag = "✅ 通关" if r["solved"] else "❌ 未通关"
        print(f"    {flag} | {r['metrics']}")
        results.append({
            "lab": lab["id"],
            "category": lab.get("category", ""),
            "solved": r["solved"],
            **r.get("metrics", {}),
            "summary": r["summary"],
            "transcript": r["transcript_path"],
        })
        time.sleep(5)  # 题与题之间礼貌限速

    _write_report(results, mode, runs_dir)


def _write_report(results, mode, runs_dir):
    ts = time.strftime("%Y%m%d-%H%M%S")
    solved = sum(1 for r in results if r["solved"])
    pct = solved / len(results) * 100 if results else 0

    lines = [
        f"# 评测报告 · {time.strftime('%Y-%m-%d %H:%M')}",
        "",
        f"- 模式：**{mode}**（hint=告知漏洞类型 / blind=盲测）",
        f"- 题数：{len(results)}，通关：{solved}（{pct:.0f}%）",
        "",
        "| 题目 | 类别 | 结果 | 步数 | HTTP请求 | LLM调用 | 耗时(s) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        lines.append(
            f"| {r['lab']} | {r['category']} | {'✅' if r['solved'] else '❌'} "
            f"| {r.get('steps', '')} | {r.get('http_requests', '')} "
            f"| {r.get('llm_calls', '')} | {r.get('duration_sec', '')} |"
        )
    md_path = os.path.join(runs_dir, f"eval-{mode}-{ts}.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    csv_path = os.path.join(runs_dir, f"eval-{mode}-{ts}.csv")
    with open(csv_path, "w", newline="", encoding="utf-8") as f:
        # 异常结果没有 metrics，表头不能依赖第一道题是否正常完成。
        writer = csv.DictWriter(f, fieldnames=[
            "lab", "category", "solved", "steps", "http_requests", "llm_calls",
            "duration_sec", "summary", "transcript",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\n评测完成: 通关 {solved}/{len(results)} ({pct:.0f}%)")
    print(f"报告: {md_path}")
