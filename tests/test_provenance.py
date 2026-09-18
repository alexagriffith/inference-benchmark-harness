import json
from pathlib import Path
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import subprocess
import unittest
from unittest.mock import patch

from bench.config import load
from bench.evidence import manifest, write_json
from bench.runner import campaign
from bench.provenance import timestamp


class ProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "run"
        self.config = load(Path(__file__).resolve().parents[1] / "examples/benchmark.json")
        self.config["load"].pop("max_attempts_per_repeat", None)
        self.config["load"].update(repeats=1, concurrency=[1], requests=1)
        self.config["metrics"] = []
        self.config["goals"] = {}

    def ledger(self):
        return [json.loads(line) for line in (self.root / "provenance.jsonl").read_text().splitlines()]

    def client(self, args, directory, deadline, lock_fd):
        native = directory / "native"
        native.mkdir()
        write_json(native / "profile_export_aiperf.json", {
            "aiperf_version": "0.12.0", "schema_version": "1.4", "request_count": {"avg": 1}})
        row = {"metadata": {"request_start_ns": timestamp()["timestamp_ns"],
                            "request_end_ns": timestamp()["timestamp_ns"]},
               "metrics": {"request_latency": {"unit": "ms", "value": 1}}}
        (native / "profile_export.jsonl").write_text(json.dumps(row) + "\n")
        return {"exit_code": 0}

    def test_failed_http_acquisition_is_preserved_across_resume(self):
        class Denied(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(401)
                self.end_headers()
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Denied)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.config["endpoint"]["url"] = f"http://127.0.0.1:{server.server_port}"
        self.config["endpoint"]["models_path"] = "/v1/models"
        with patch("bench.preflight.subprocess.run", return_value=subprocess.CompletedProcess([], 0, "0.12.0\n")), \
             patch("bench.runner.run_child", side_effect=AssertionError("must not send inference")):
            self.assertEqual(campaign(self.config, self.root, "aiperf")["status"], "preflight_failed")
        before = (self.root / "provenance.jsonl").read_bytes()
        acquisition = next(row for row in self.ledger() if row["operation"] == "http_acquisition")
        self.assertEqual(acquisition["status"], "failed")
        self.assertEqual(acquisition["error_type"], "ValueError")
        self.assertLessEqual(acquisition["started"]["timestamp_ns"], acquisition["finished"]["timestamp_ns"])
        self.assertLessEqual(acquisition["finished"]["timestamp_ns"], acquisition["recorded"]["timestamp_ns"])
        self.assertNotIn("Authorization", json.dumps(acquisition))
        with patch("bench.runner.verify", return_value=[]), patch("bench.runner.run_child", side_effect=self.client):
            self.assertEqual(campaign(self.config, self.root, "aiperf", resume=True)["status"], "complete")
        self.assertTrue((self.root / "provenance.jsonl").read_bytes().startswith(before))
        state_saves = [row for row in self.ledger() if row["operation"] == "artifact_saved" and row.get("artifact") == "state.json"]
        self.assertGreater(len({row["sha256"] for row in state_saves}), 1)
        accepted = self.root / "point-01-attempt-002"
        self.assertEqual(json.loads((accepted / "manifest.json").read_text()), manifest(accepted))
        # Appending history must not invalidate accepted evidence on a second resume.
        with patch("bench.runner.run_child", side_effect=AssertionError("completed run must be skipped")):
            self.assertEqual(campaign(self.config, self.root, "aiperf", resume=True)["status"], "complete")

    def test_pre_and_post_reads_are_distinct_from_save_times(self):
        self.config["kubernetes"] = {"context": "fixture", "deployments": []}
        with patch("bench.runner.verify", return_value=[]), patch("bench.kubernetes.inspect", return_value=[]), \
             patch("bench.runner.run_child", side_effect=self.client):
            campaign(self.config, self.root, "aiperf")
        rows = self.ledger()
        pre = next(row for row in rows if row["operation"] == "verify_attempt")
        child = next(row for row in rows if row["operation"] == "client_execution")
        post = next(row for row in rows if row["operation"] == "postflight")
        saved = next(row for row in rows if row["operation"] == "artifact_saved" and row.get("artifact", "").endswith("postflight.json"))
        self.assertLessEqual(pre["finished"]["timestamp_ns"], child["started"]["timestamp_ns"])
        self.assertLessEqual(child["finished"]["timestamp_ns"], post["started"]["timestamp_ns"])
        self.assertLessEqual(post["finished"]["timestamp_ns"], saved["save_window"]["started"]["timestamp_ns"])
        self.assertLessEqual(saved["save_window"]["finished"]["timestamp_ns"], saved["recorded"]["timestamp_ns"])
        native = [row for row in rows if row["operation"] == "native_artifact_observed"]
        self.assertEqual(len(native), 2)
        self.assertTrue(all("created" not in row for row in native))

    def test_failed_config_snapshot_stops_before_traffic_and_is_timed(self):
        with patch("bench.evidence.json.dump", side_effect=OSError("fixture disk failure")), \
             patch("bench.runner.run_child", side_effect=AssertionError("must not send inference")):
            with self.assertRaises(OSError):
                campaign(self.config, self.root, "aiperf")
        rows = self.ledger()
        failure = next(row for row in rows if row["operation"] == "save_json")
        self.assertEqual(failure["status"], "failed")
        self.assertEqual(failure["artifact"], "config.json")
        self.assertGreaterEqual(failure["duration_ns"], 0)
        self.assertEqual(rows[-1]["operation"], "campaign")
        self.assertEqual(rows[-1]["status"], "failed")
        self.assertFalse(any(row["operation"] == "artifact_saved" for row in rows))
