"""Evaluation report regressions; no LLM API or lab is contacted."""

import csv
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from eval.runner import _write_report, run_eval


REPORT_FIELDS = [
    "lab", "category", "solved", "steps", "http_requests", "llm_calls",
    "duration_sec", "summary", "transcript",
]


class EvalReportTests(unittest.TestCase):
    def setUp(self):
        self.failed = {
            "lab": "failed_lab", "category": "test", "solved": False,
            "summary": '运行异常: 模型返回 "错误", 请重试\n保留下一行',
            "transcript": "",
        }
        self.succeeded = {
            "lab": "solved_lab", "category": "test", "solved": True,
            "steps": 3, "http_requests": 2, "llm_calls": 3,
            "duration_sec": 1.5, "summary": "已通关",
            "transcript": "runs/solved_lab.json",
        }

    def assert_report(self, folder, results, totals, mode="hint"):
        csv_paths = list(Path(folder).glob(f"eval-{mode}-*.csv"))
        md_paths = list(Path(folder).glob(f"eval-{mode}-*.md"))
        self.assertEqual(len(csv_paths), 1)
        self.assertEqual(len(md_paths), 1)
        with csv_paths[0].open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream)
            self.assertEqual(reader.fieldnames, REPORT_FIELDS)
            rows = list(reader)
        self.assertEqual(rows, [
            {field: str(result.get(field, "")) for field in REPORT_FIELDS}
            for result in results
        ])
        self.assertIn(totals, md_paths[0].read_text(encoding="utf-8"))

    def test_mixed_results_preserve_metrics_and_text_in_either_order(self):
        for results in ([self.failed, self.succeeded],
                        [self.succeeded, self.failed]):
            with self.subTest(first_lab=results[0]["lab"]), \
                    TemporaryDirectory() as folder, patch("builtins.print"):
                _write_report(results, "hint", folder)
                self.assert_report(folder, results, "题数：2，通关：1（50%）")

    def test_all_failures_keep_metric_columns(self):
        results = [self.failed, {**self.failed, "lab": "another_failed_lab"}]
        with TemporaryDirectory() as folder, patch("builtins.print"):
            _write_report(results, "blind", folder)
            self.assert_report(folder, results, "题数：2，通关：0（0%）", "blind")

    def test_empty_results_write_header_and_zero_totals(self):
        with TemporaryDirectory() as folder, patch("builtins.print"):
            _write_report([], "hint", folder)
            self.assert_report(folder, [], "题数：0，通关：0（0%）")

    def test_run_eval_exports_later_success_after_first_lab_raises(self):
        cfg = {
            "llm": {},
            "safety": {"allowed_host_suffixes": ["example.test"]},
            "agent": {"request_interval_sec": 0, "max_http_requests": 10,
                      "max_steps": 5},
        }
        labs = [
            {"id": result["lab"], "title": result["lab"],
             "category": result["category"],
             "lab_url": f"https://{result['lab']}.example.test"}
            for result in (self.failed, self.succeeded)
        ]
        success = {
            "solved": True, "summary": self.succeeded["summary"],
            "metrics": {name: self.succeeded[name] for name in
                        ("steps", "http_requests", "llm_calls", "duration_sec")},
            "transcript_path": self.succeeded["transcript"],
        }
        with TemporaryDirectory() as folder, \
                patch("eval.runner.load_registry", return_value=labs), \
                patch("eval.runner.LLMClient") as llm, \
                patch("eval.runner.SafeHTTP") as http, \
                patch("eval.runner.ReActAgent") as agent, \
                patch("eval.runner.time.sleep"), patch("builtins.print"):
            agent.return_value.run.side_effect = [
                RuntimeError("模拟模型异常"), success,
            ]
            run_eval(cfg, runs_dir=folder)

            self.assertEqual(agent.return_value.run.call_count, 2)
            self.assertEqual(llm.call_count, 2)
            self.assertEqual(http.call_count, 2)
            expected = [
                {**self.failed, "summary": "运行异常: 模拟模型异常"},
                self.succeeded,
            ]
            self.assert_report(folder, expected, "题数：2，通关：1（50%）")


if __name__ == "__main__":
    unittest.main()
