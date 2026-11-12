"""ReAct Agent 核心：思考 -> 行动 -> 观察 的循环。

每一步的完整过程（思考、工具调用、HTTP 流量、观察结果）都会写入 Transcript，
供回放界面逐步复盘。
"""

import json
import re
import time

THOUGHT_RE = re.compile(r"Thought:\s*(.*?)(?=\n\s*Action:|\Z)", re.S)
ACTION_RE = re.compile(r"Action:\s*([A-Za-z_]\w*)")
INPUT_RE = re.compile(r"Action Input:\s*(\{.*\})", re.S)
SOLVED_RE = re.compile(r'"solved"\s*:\s*true', re.I)


def parse_react(text: str):
    """从模型回复中解析 Thought / Action / Action Input。"""
    m = THOUGHT_RE.search(text)
    thought = m.group(1).strip() if m else ""
    m = ACTION_RE.search(text)
    action = m.group(1) if m else ""
    args = {}
    m = INPUT_RE.search(text)
    if m:
        raw = m.group(1).strip()
        try:
            args = json.loads(raw)
        except json.JSONDecodeError:
            args = {"_raw": raw}
    if not isinstance(args, dict):
        args = {"_value": args}
    return thought, action, args


class ReActAgent:
    def __init__(self, llm, toolbox, transcript, system_prompt, task, max_steps=25):
        self.llm = llm
        self.toolbox = toolbox
        self.transcript = transcript
        self.system_prompt = system_prompt
        self.task = task
        self.max_steps = max_steps

    def run(self) -> dict:
        start_ts = time.time()
        messages = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": self.task},
        ]
        solved = False
        summary = ""
        recent_calls = []

        for step_no in range(1, self.max_steps + 1):
            reply = self.llm.chat(messages)
            thought, action, args = parse_react(reply)

            # 格式错误：提示模型重新输出
            if not action:
                messages.append({"role": "assistant", "content": reply})
                messages.append({"role": "user", "content": FORMAT_HINT})
                self.transcript.add_step(step_no, thought, "", {}, reply, status="format_error")
                continue

            if action == "finish":
                summary = str(args.get("summary", ""))[:500]
                self.transcript.add_step(step_no, thought, action, args, summary)
                break

            # 重复调用检测：连续同样操作时提醒模型换思路
            call_key = (action, json.dumps(args, sort_keys=True, ensure_ascii=False))
            repeated = recent_calls.count(call_key)
            result = self.toolbox.execute(action, args)
            observation, traffic = result["observation"], result.get("traffic")
            if repeated >= 2:
                observation += "\n\n⚠️ 你已重复同一操作多次，请更换思路或换注入点。"
            recent_calls.append(call_key)

            self.transcript.add_step(step_no, thought, action, args, observation, traffic)

            # 通关检测：check_solved 返回 true 即自动结束
            if action == "check_solved" and SOLVED_RE.search(observation):
                solved = True
                summary = "已通关：靶场返回 Congratulations 横幅。"
                self.transcript.add_step(step_no + 1, "系统", "auto_finish", {}, summary)
                break

            messages.append({"role": "assistant", "content": reply})
            messages.append({"role": "user", "content": f"Observation: {observation[:6000]}"})
        else:
            summary = summary or f"达到最大步数 {self.max_steps}，停止。"

        metrics = {
            "steps": len(self.transcript.data["steps"]),
            "http_requests": len(getattr(self.toolbox.http, "traffic", [])),
            "llm_calls": getattr(self.llm, "calls", 0),
            "duration_sec": round(time.time() - start_ts, 1),
        }
        path = self.transcript.finish(
            "solved" if solved else "failed", solved, summary, metrics
        )
        return {"solved": solved, "summary": summary, "metrics": metrics,
                "transcript_path": path}
