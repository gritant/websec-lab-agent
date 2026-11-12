"""运行记录（Transcript）：一次完整运行的每一步落盘为 JSON。

一份运行数据，三种用途：
1. 评测：metrics 里的步数/请求数/耗时/是否通关；
2. 回放：ui/app.py 逐步复盘每一步的思考、请求与响应；
3. 教学：结合 docs/knowledge.yaml 的知识卡片讲解漏洞原理。
"""

import json
import os
import time


class Transcript:
    def __init__(self, data: dict, runs_dir: str):
        self.data = data
        self.runs_dir = runs_dir

    @classmethod
    def start(cls, lab_id, lab_title, category, mode, base_url, runs_dir=None):
        runs_dir = runs_dir or os.path.join(os.getcwd(), "runs")
        os.makedirs(runs_dir, exist_ok=True)
        data = {
            "lab_id": lab_id,
            "lab_title": lab_title,
            "category": category,
            "mode": mode,
            "base_url": base_url,
            "started_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "status": "running",
            "solved": False,
            "steps": [],
            "metrics": {},
        }
        return cls(data, runs_dir)

    def add_step(self, step_no, thought, action, action_input, observation,
                 traffic=None, status="ok"):
        self.data["steps"].append({
            "step": step_no,
            "thought": thought,
            "action": action,
            "action_input": action_input,
            "observation": observation,
            "traffic": traffic,
            "status": status,
            "ts": time.time(),
        })

    def finish(self, status, solved, summary, metrics) -> str:
        self.data["status"] = status
        self.data["solved"] = solved
        self.data["summary"] = summary
        self.data["metrics"] = metrics
        return self.save()

    def save(self, path=None) -> str:
        if not path:
            path = os.path.join(
                self.runs_dir,
                f"{time.strftime('%Y%m%d-%H%M%S')}-{self.data['lab_id']}-{self.data['mode']}.json",
            )
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
        return path

    @staticmethod
    def load(path) -> dict:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
