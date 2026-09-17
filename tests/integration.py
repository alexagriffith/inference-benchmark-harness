"""Exercise the installed AIPerf CLI against harmless local HTTP fixtures."""

import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]


class Handler(BaseHTTPRequestHandler):
    requests = []
    failures = False

    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.path == "/v1/models":
            body = json.dumps({"data": [{"id": "fixture-model"}]}).encode()
        elif self.path == "/metrics":
            body = ("# TYPE fixture_requests_total counter\nfixture_requests_total " + str(len(self.requests)) + "\n").encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        self.requests.append({"path": self.path, "model": payload.get("model"),
                              "authorized": self.headers.get("Authorization") == "Bearer fixture-key", "at": time.time()})
        if self.failures:
            self.send_error(503)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        try:
            for word in ("Hello", " world", "."):
                chunk = {"id": "fixture", "object": "chat.completion.chunk", "created": int(time.time()),
                         "model": "fixture-model", "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}]}
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
                self.wfile.flush()
                time.sleep(0.06)
            chunk = {"id": "fixture", "object": "chat.completion.chunk", "model": "fixture-model",
                     "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                     "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11}}
            self.wfile.write(("data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--aiperf", required=True)
    args = parser.parse_args()
    output = Path(tempfile.mkdtemp(prefix="inference-bench-integration-"))
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    commands = []
    env = {**os.environ, "FIXTURE_API_KEY": "fixture-key", "PYTHONDONTWRITEBYTECODE": "1"}
    try:
        config = json.loads((ROOT / "examples/benchmark.json").read_text())
        config["endpoint"].update(url=f"http://127.0.0.1:{server.server_port}", model="fixture-model", api_key_env="FIXTURE_API_KEY")
        config["load"].update(concurrency=[1, 2], requests=3, duration_seconds=10,
                              request_timeout_seconds=3, grace_seconds=5, deadline_seconds=90)
        config["metrics"] = [{"name": "fixture", "url": config["endpoint"]["url"] + "/metrics", "required": [{"metric": "fixture_requests_total", "why": "Check collection during the request window"}]}]
        duration_requests = 0
        for case in ("generated", "file", "duration", "server-error"):
            if case == "file":
                config["workload"] = {"type": "single_turn", "path": str(ROOT / "examples/prompts.jsonl"), "output_tokens": 32, "tokenizer": "builtin"}
                config["load"]["concurrency"] = [1]
            if case == "duration":
                config["load"].update(requests=100, duration_seconds=1)
            if case == "server-error":
                config["load"].update(requests=3, duration_seconds=10)
                Handler.failures = True
            config_path = output / f"{case}.json"
            config_path.write_text(json.dumps(config))
            run = output / case
            command = [sys.executable, "-m", "bench", "run", "--config", str(config_path), "--run", str(run), "--aiperf", args.aiperf, "--execute"]
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)
            commands.append({"case": case, "command": command, "exit_code": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
            (output / "commands.json").write_text(json.dumps(commands, indent=2))
            print(json.dumps({"case": case, "exit_code": result.returncode, "output": str(run)}), flush=True)
            if case != "server-error":
                if result.returncode != 0:
                    raise AssertionError(result.stdout + result.stderr)
                state = json.loads((run / "state.json").read_text())
                assert state["status"] == "complete"
                for attempt in state["completed"]:
                    summary = json.loads((run / attempt / "summary.json").read_text())
                    assert summary["evidence"] == "complete"
                    if case == "duration":
                        duration_requests = summary["requests"]
                        assert 0 < duration_requests < 100
                    else:
                        assert summary["requests"] == 3
            else:
                assert result.returncode != 0
                assert len(list(run.glob("point-*"))) == 1
        assert len(Handler.requests) == 12 + duration_requests, len(Handler.requests)
        assert all(row["authorized"] for row in Handler.requests)
        assert all(row["path"] == "/v1/chat/completions" for row in Handler.requests)
        Handler.failures = False
        sys.path.insert(0, str(ROOT))
        from bench.runner import command as build_command
        sweep_dir = output / "native-sweep"
        sweep_dir.mkdir()
        config["endpoint"].pop("api_key_env")
        cmd = build_command(config, 1, sweep_dir, args.aiperf)
        cmd[cmd.index("--concurrency") + 1] = "1,2"
        result = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True, timeout=200)
        commands.append({"case": "native-sweep", "command": cmd, "exit_code": result.returncode,
                         "stdout": result.stdout, "stderr": result.stderr})
        (output / "commands.json").write_text(json.dumps(commands, indent=2))
        assert result.returncode == 0, result.stdout + result.stderr
        exports = list(sweep_dir.rglob("profile_export_aiperf.json"))
        assert len(exports) == 2, [str(p) for p in exports]
        assert len(Handler.requests) == 18 + duration_requests, len(Handler.requests)
        (output / "observed-requests.json").write_text(json.dumps(Handler.requests, indent=2))
        print(json.dumps({"status": "pass", "requests": len(Handler.requests), "artifacts": str(output)}))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
