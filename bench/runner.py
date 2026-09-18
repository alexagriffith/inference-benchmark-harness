"""Run isolated points and keep every attempt, including failures."""

import fcntl
import copy
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time

from .config import file_digest, fingerprint, load_points, phase
from .evidence import analyze, manifest, write_json
from .preflight import verify


def command(config, point, directory, aiperf):
    endpoint, workload, bounds = config["endpoint"], config["workload"], config["load"]
    traffic = phase(config, point)
    args = [aiperf, "profile", "--url", endpoint["url"], "--custom-endpoint", endpoint["path"],
            "--model", endpoint["model"], "--endpoint-type", "chat", "--streaming",
            "--tokenizer", workload.get("tokenizer", "builtin"), "--use-server-token-count",
            "--concurrency", str(traffic["concurrency"]), "--request-count", str(bounds["requests"]),
            "--benchmark-duration", str(bounds["duration_seconds"]),
            "--benchmark-grace-period", str(bounds["grace_seconds"]),
            "--request-timeout-seconds", str(bounds["request_timeout_seconds"]),
            "--osl", str(workload["output_tokens"]), "--random-seed", "42",
            "--record-processors", str(config.get("record_processors", 1)),
            "--no-gpu-telemetry", "--ui-type", "none", "--export-level", "records", "--no-auto-plot",
            "--output-artifact-dir", str(directory / "native")]
    if "rate" in traffic:
        args += ["--request-rate", str(traffic["rate"]), "--request-rate-mode", traffic["type"]]
    if workload["type"] == "single_turn":
        args += ["--input-file", workload["path"], "--custom-dataset-type", "single_turn"]
    else:
        args += ["--isl", str(workload["input_tokens"]), "--isl-stddev", "0", "--osl-stddev", "0"]
    if endpoint.get("api_key_env"):
        args += ["--config", str(directory / "auth.yaml")]
    for key, value in sorted(endpoint.get("headers", {}).items()):
        args += ["--header", key + ":" + value]
    if config.get("metrics"):
        args += ["--server-metrics", *[producer["url"] for producer in config["metrics"]],
                 "--server-metrics-formats", "json", "csv", "jsonl"]
    else:
        args += ["--no-server-metrics"]
    return args


def event(root, code, **fields):
    value = {"schema_version": 1, "timestamp": time.time(), "event": code, **fields}
    with (root / "events.jsonl").open("a") as stream:
        stream.write(json.dumps(value) + "\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_child(args, directory, deadline, lock_fd):
    process = None
    code, reason = 1, None
    started = time.time()
    try:
        with (directory / "aiperf.log").open("w") as log:
            process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT,
                                       start_new_session=True, pass_fds=(lock_fd,))
            code = process.wait(timeout=deadline)
    except subprocess.TimeoutExpired:
        code, reason = 124, "deadline_exceeded"
    except KeyboardInterrupt:
        code, reason = 130, "interrupted"
    except OSError:
        code, reason = 127, "launch_failed"
    finally:
        if process is not None:
            try:
                os.killpg(process.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                pass
            # A finished parent may still have descendants in its process group.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait()
    return {"start_unix": started, "end_unix": time.time(), "exit_code": code, "reason": reason}


def campaign(config, root, aiperf, resume=False):
    os.umask(0o077)
    root = Path(root).resolve()
    root.mkdir(parents=True, exist_ok=resume)
    with (root / ".lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("A process still owns this campaign") from None
        return run_locked(config, root, aiperf, resume, lock.fileno())


def run_locked(config, root, aiperf, resume, lock_fd):
    identity = fingerprint(config)
    if resume:
        state = json.loads((root / "state.json").read_text())
        if state["config_hash"] != identity:
            raise ValueError("Configuration or dataset changed; choose a new run directory")
        if state["status"] == "running":
            raise ValueError("Previous execution ended without a checkpoint; inspect ownership and start a new campaign")
        for accepted in state["completed"]:
            directory = root / accepted
            if json.loads((directory / "manifest.json").read_text()) != manifest(directory):
                raise ValueError("Saved evidence changed; cannot skip this point on resume")
    else:
        state = {"schema_version": 1, "config_hash": identity, "status": "created", "completed": [], "next_point": 0, "attempts": 0}
        write_json(root / "config.json", config)
    if state["status"] == "complete":
        return state
    points = load_points(config)
    for index in range(state["next_point"], len(points)):
        point = points[index]
        if len(list(root.glob(f"point-{index + 1:02d}-attempt-*"))) >= config["load"].get("max_attempts_per_point", 3):
            state["status"] = "attempt_budget_exhausted"
            write_json(root / "state.json", state)
            event(root, "attempt_budget_exhausted", point=index + 1, retryable=False,
                  action="Review the accumulated failures before planning another experiment")
            return state
        state["attempts"] += 1
        directory = root / f"point-{index + 1:02d}-attempt-{state['attempts']:03d}"
        directory.mkdir()
        checks = verify(config, aiperf)
        if shutil.disk_usage(root).free < 64 * 1024 * 1024:
            checks.append({"name": "storage", "status": "fail", "detail": "Less than 64 MiB free; choose durable storage with enough space for the planned run"})
        write_json(directory / "preflight.json", checks)
        if any(check["status"] == "fail" for check in checks):
            state["status"] = "preflight_failed"
            event(root, "preflight_failed", point=index + 1, attempt=directory.name, retryable=True, action="Correct the failed check, then resume; no inference was sent")
            write_json(root / "state.json", state)
            return state
        point_config = copy.deepcopy(config)
        if config["workload"]["type"] == "single_turn":
            dataset = directory / "input.jsonl"
            shutil.copyfile(config["workload"]["path"], dataset)
            if file_digest(dataset) != config["workload"]["sha256"]:
                state["status"] = "dataset_changed"
                write_json(root / "state.json", state)
                event(root, "dataset_changed", point=index + 1, attempt=directory.name, retryable=False,
                      action="Restore the planned input or create a new experiment")
                return state
            point_config["workload"]["path"] = str(dataset)
        if config["endpoint"].get("api_key_env"):
            env_name = config["endpoint"]["api_key_env"]
            workload = point_config["workload"]
            dataset = ({"type": "file", "format": "single_turn", "path": workload["path"]}
                       if workload["type"] == "single_turn" else
                       {"type": "synthetic", "isl": {"mean": workload["input_tokens"], "stddev": 0},
                        "osl": {"mean": workload["output_tokens"], "stddev": 0}})
            write_json(directory / "auth.yaml", {"schemaVersion": "2.0", "benchmark": {
                "endpoint": {"api_key": "${" + env_name + "}"}, "dataset": dataset,
                "phases": phase(config, point)}})
        args = command(point_config, point, directory, aiperf)
        write_json(directory / "command.json", args)
        state["status"] = "running"
        write_json(root / "state.json", state)
        event(root, "point_started", point=index + 1, attempt=directory.name, load=phase(config, point))
        execution = run_child(args, directory, config["load"]["deadline_seconds"], lock_fd)
        write_json(directory / "execution.json", execution)
        result = analyze(directory, config, execution)
        write_json(directory / "summary.json", result)
        write_json(directory / "manifest.json", manifest(directory))
        if result["evidence"] != "complete":
            state["status"] = "evidence_invalid"
            event(root, "point_invalid", point=index + 1, attempt=directory.name, retryable=False,
                  reasons=result["reasons"], action="Inspect artifacts; deliberate resume creates a new attempt")
            write_json(root / "state.json", state)
            return state
        state["completed"].append(directory.name)
        state["next_point"] = index + 1
        missed = any(goal["status"] != "met" for goal in result["goals"])
        state["status"] = "goal_not_met" if missed else "request_errors" if result["failed_requests"] else "ready"
        event(root, "point_completed", point=index + 1, attempt=directory.name, retryable=False,
              result=state["status"], action="Keep this result; resume advances to the next point" if state["status"] != "ready" else "Continue")
        write_json(root / "state.json", state)
        if state["status"] != "ready":
            return state
    state["status"] = "complete"
    write_json(root / "state.json", state)
    event(root, "campaign_complete", points=len(state["completed"]))
    return state
