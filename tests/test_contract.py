import copy
import json
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys
from urllib.error import HTTPError
from unittest.mock import patch

from bench.config import load
from bench.evidence import analyze, write_json
from bench.runner import campaign, command, run_child
from bench.preflight import fetch
from bench.kubernetes import inspect

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.config = load(ROOT / "examples/benchmark.json")
        self.config["load"].update(concurrency=[1, 2], requests=2)

    def fixture(self, args, directory, deadline, lock_fd):
        native = directory / "native"
        native.mkdir()
        write_json(native / "profile_export_aiperf.json", {
            "aiperf_version": "0.12.0", "schema_version": "1.4",
            "request_count": {"avg": 2}, "time_to_first_token": {"unit": "ms", "p95": 20}})
        row = {"metadata": {"request_start_ns": 100, "request_end_ns": 200},
               "metrics": {"request_latency": 100}}
        (native / "profile_export.jsonl").write_text((json.dumps(row) + "\n") * 2)
        return {"exit_code": 0, "reason": None}

    def test_plan_does_not_execute_or_write(self):
        with patch("subprocess.Popen", side_effect=AssertionError("execution")):
            args = command(self.config, 1, self.root / "unused", "aiperf")
        self.assertIn("--custom-endpoint", args)
        self.assertFalse((self.root / "unused").exists())

    def test_empty_dataset_fails_before_traffic(self):
        config = copy.deepcopy(self.config)
        (self.root / "empty.jsonl").write_text("")
        config["workload"] = {"type": "single_turn", "path": "empty.jsonl", "output_tokens": 10}
        write_json(self.root / "config.json", config)
        with self.assertRaisesRegex(ValueError, "empty"):
            load(self.root / "config.json")

    def test_no_secret_in_command(self):
        self.config["endpoint"]["api_key_env"] = "BENCH_API_KEY"
        args = command(self.config, 1, self.root, "aiperf")
        self.assertNotIn("--api-key", args)
        self.assertIn("--config", args)

    @patch("bench.runner.verify", return_value=[])
    def test_points_finish_before_next_starts_and_resume_skips(self, verify):
        calls = []
        def execute(*args):
            calls.append(args[1].name)
            if len(calls) == 2:
                self.assertTrue((args[1].parent / calls[0] / "summary.json").exists())
            return self.fixture(*args)
        root = self.root / "run"
        with patch("bench.runner.run_child", side_effect=execute):
            result = campaign(self.config, root, "aiperf")
        self.assertEqual(result["status"], "complete")
        with patch("bench.runner.run_child", side_effect=AssertionError("replayed")):
            self.assertEqual(campaign(self.config, root, "aiperf", True)["status"], "complete")
        self.assertEqual(len(calls), 2)

    @patch("bench.runner.verify", return_value=[])
    def test_goal_miss_is_kept_and_resume_advances(self, verify):
        self.config["goals"] = {"ttft_p95_ms": 10}
        root = self.root / "run"
        with patch("bench.runner.run_child", side_effect=self.fixture):
            state = campaign(self.config, root, "aiperf")
            self.assertEqual(state["status"], "goal_not_met")
            self.assertEqual(state["next_point"], 1)
            state = campaign(self.config, root, "aiperf", True)
        self.assertEqual(state["next_point"], 2)
        self.assertEqual(state["attempts"], 2)

    @patch("bench.runner.verify", return_value=[])
    def test_missing_evidence_stops_without_retry(self, verify):
        root = self.root / "run"
        with patch("bench.runner.run_child", return_value={"exit_code": 0}) as child:
            state = campaign(self.config, root, "aiperf")
        self.assertEqual(state["status"], "evidence_invalid")
        self.assertEqual(child.call_count, 1)
        self.assertEqual(state["next_point"], 0)

    @patch("bench.runner.verify", return_value=[{"status": "fail", "name": "model"}])
    def test_preflight_failure_sends_no_traffic(self, verify):
        with patch("bench.runner.run_child", side_effect=AssertionError("traffic")):
            state = campaign(self.config, self.root / "run", "aiperf")
        self.assertEqual(state["status"], "preflight_failed")

    @patch("bench.runner.verify", return_value=[])
    def test_modified_evidence_prevents_skip(self, verify):
        root = self.root / "run"
        with patch("bench.runner.run_child", side_effect=self.fixture):
            state = campaign(self.config, root, "aiperf")
        (root / state["completed"][0] / "summary.json").write_text("{}")
        with self.assertRaisesRegex(ValueError, "evidence changed"):
            campaign(self.config, root, "aiperf", True)

    def test_unchanged_metrics_use_fetch_timeline(self):
        self.fixture([], self.root, 10, 0)
        native = self.root / "native"
        self.config["metrics"] = [{"name": "engine", "url": "http://localhost/metrics", "required": [{"metric": "requests", "why": "Coverage"}]}]
        (native / "server_metrics_export.jsonl").write_text(json.dumps({"endpoint_url": "http://localhost/metrics", "timestamp_ns": 50}) + "\n")
        write_json(native / "server_metrics_export.json", {"summary": {"endpoint_info": {
            "http://localhost/metrics": {"total_fetches": 5, "first_fetch_ns": 50, "last_fetch_ns": 250}}}})
        self.assertEqual(analyze(self.root, self.config, {"exit_code": 0})["evidence"], "complete")
        write_json(native / "server_metrics_export.json", {"summary": {"endpoint_info": {
            "http://localhost/metrics": {"total_fetches": 1, "first_fetch_ns": 50, "last_fetch_ns": 50}}}})
        self.assertEqual(analyze(self.root, self.config, {"exit_code": 0})["evidence"], "invalid")

    def test_interruption_cannot_be_accepted(self):
        self.fixture([], self.root, 10, 0)
        result = analyze(self.root, self.config, {"exit_code": 130, "reason": "interrupted"})
        self.assertEqual(result["evidence"], "invalid")
        self.assertIn("interrupted", result["reasons"])

    @patch("bench.runner.verify", return_value=[])
    def test_attempt_budget_prevents_another_launch(self, verify):
        root = self.root / "run"
        self.config["load"]["max_attempts_per_point"] = 1
        with patch("bench.runner.run_child", return_value={"exit_code": 1}) as child:
            campaign(self.config, root, "aiperf")
            state = campaign(self.config, root, "aiperf", True)
        self.assertEqual(state["status"], "attempt_budget_exhausted")
        self.assertEqual(child.call_count, 1)

    def test_real_child_is_bounded_by_deadline(self):
        with (self.root / ".lock").open("w") as lock:
            result = run_child([sys.executable, "-c", "import time; time.sleep(30)"], self.root, 0.1, lock.fileno())
        self.assertEqual(result["reason"], "deadline_exceeded")
        self.assertLess(result["end_unix"] - result["start_unix"], 6)

    def test_reconciled_but_premature_export_is_invalid(self):
        self.fixture([], self.root, 10, 0)
        self.config["load"]["requests"] = 20
        path = self.root / "native/profile_export_aiperf.json"
        summary = json.loads(path.read_text())
        summary.update(start_time="2026-01-01T00:00:00", end_time="2026-01-01T00:00:01")
        write_json(path, summary)
        result = analyze(self.root, self.config, {"exit_code": 0})
        self.assertIn("stopped_before_request_or_time_limit", result["reasons"])

    def test_authentication_errors_are_not_retried(self):
        with patch("bench.preflight.urlopen", side_effect=HTTPError("http://localhost", 401, "Unauthorized", {}, None)) as request:
            with self.assertRaisesRegex(ValueError, "HTTP 401"):
                fetch("http://localhost")
        self.assertEqual(request.call_count, 1)

    def test_transient_read_retries_are_bounded(self):
        with patch("bench.preflight.urlopen", side_effect=HTTPError("http://localhost", 503, "Unavailable", {}, None)) as request:
            with patch("bench.preflight.time.sleep") as sleep:
                with self.assertRaisesRegex(ValueError, "HTTP 503"):
                    fetch("http://localhost")
        self.assertEqual(request.call_count, 3)
        self.assertEqual(sleep.call_count, 2)

    def test_old_and_new_rollout_pods_do_not_pass(self):
        scope = {"kubernetes": {"context": "test-context", "deployments": [{"namespace": "test", "name": "model", "replicas": 1}]}}
        deployment = {"metadata": {"generation": 2}, "spec": {"replicas": 1, "selector": {"matchLabels": {"app": "model"}}},
                      "status": {"observedGeneration": 2, "replicas": 2, "updatedReplicas": 1, "readyReplicas": 1, "availableReplicas": 1}}
        pod = {"metadata": {"name": "model-1", "uid": "a"}, "status": {"conditions": [{"type": "Ready", "status": "True"}]}}
        calls = []
        def read(args, **kwargs):
            calls.append(args)
            payload = deployment if "deployment" in args else {"items": [pod, pod]}
            return subprocess.CompletedProcess(args, 0, json.dumps(payload))
        with patch("bench.kubernetes.subprocess.run", side_effect=read):
            result = inspect(scope)
        self.assertEqual(result[0]["status"], "fail")
        self.assertTrue(all("get" in args and "--context" in args for args in calls))


if __name__ == "__main__":
    unittest.main()
