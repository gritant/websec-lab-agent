"""CLI evaluation regressions; no LLM API or remote lab is contacted."""

from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import main


class EvalCLITests(unittest.TestCase):
    def test_eval_defaults_to_hint_mode(self):
        cfg = {"test_config": True}
        with patch("sys.argv", ["main.py", "eval"]), \
                patch("main.load_config", return_value=cfg) as load_config, \
                patch("eval.runner.run_eval") as run_eval:
            main.main()

        load_config.assert_called_once_with(None)
        run_eval.assert_called_once_with(cfg, mode="hint", only=None)

    def test_eval_forwards_blind_mode_lab_filters_and_config_path(self):
        cfg = {"test_config": True}
        argv = ["main.py", "eval", "--mode", "blind", "--lab", "lab_one",
                "--lab", "lab_two", "--config", "custom.yaml"]
        with patch("sys.argv", argv), \
                patch("main.load_config", return_value=cfg) as load_config, \
                patch("eval.runner.run_eval") as run_eval:
            main.main()

        load_config.assert_called_once_with("custom.yaml")
        run_eval.assert_called_once_with(cfg, mode="blind", only=["lab_one", "lab_two"])

    def test_eval_without_ready_labs_prints_setup_hint(self):
        with TemporaryDirectory() as folder, \
                patch("sys.argv", ["main.py", "eval"]), \
                patch("main.load_config", return_value={}), \
                patch("eval.runner.HERE", folder), \
                patch("eval.runner.load_registry", return_value=[]), \
                patch("eval.runner.LLMClient") as llm, \
                patch("eval.runner.SafeHTTP") as http, \
                patch("builtins.print") as output:
            main.main()

        self.assertIn("注册表中没有可运行的题目", output.call_args.args[0])
        llm.assert_not_called()
        http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
