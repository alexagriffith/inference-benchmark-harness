"""Validate the supported experiment contract before any traffic."""

import hashlib
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def file_digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def positive(value, name, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a positive number")
    if not math.isfinite(value) or value <= 0 or (integer and type(value) is not int):
        raise ValueError(f"Invalid {name}")


def check_url(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in ("http", "https") or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("Use an HTTP(S) URL without credentials, query or fragment")


def load(path, smoke=False):
    config = json.loads(Path(path).read_text())
    if config.get("schema_version") != 1:
        raise ValueError("Expected schema_version 1")
    positive(config.get("record_processors", 1), "record_processors", integer=True)
    if config.get("kubernetes"):
        scope = config["kubernetes"]
        if not isinstance(scope.get("context"), str) or not scope["context"] or not scope.get("deployments"):
            raise ValueError("kubernetes needs an explicit context and deployments")
        for target in scope["deployments"]:
            if not target.get("name") or not target.get("namespace"):
                raise ValueError("Each Deployment needs name and namespace")
            positive(target["replicas"], "replicas", integer=True)
    endpoint = config["endpoint"]
    check_url(endpoint["url"])
    if urlsplit(endpoint["url"]).path not in ("", "/"):
        raise ValueError("Use endpoint.path for the API path")
    if not isinstance(endpoint["model"], str) or not endpoint["model"].strip():
        raise ValueError("Set endpoint.model to the served model name")
    for name in ("path", "models_path"):
        value = endpoint.get(name)
        if name == "models_path" and value is None:
            continue
        if not isinstance(value, str) or not value.startswith("/") or any(c in value for c in "?#\r\n") or value.startswith("//"):
            raise ValueError(f"Set endpoint.{name} to an absolute API path")
    if endpoint.get("api_key_env") and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", endpoint["api_key_env"]):
        raise ValueError("api_key_env must name an environment variable")
    for name, value in endpoint.get("headers", {}).items():
        if not re.fullmatch(r"[A-Za-z0-9-]+", name) or not isinstance(value, str) or "\n" in value or "\r" in value:
            raise ValueError("Invalid request header")
        if name.lower() in ("authorization", "cookie", "proxy-authorization"):
            raise ValueError("Use api_key_env for credentials")
    workload = config["workload"]
    if workload["type"] == "single_turn":
        data = Path(path).resolve().parent / workload["path"]
        lines = 0
        with data.open() as stream:
            for line in stream:
                if not line.strip():
                    continue
                row = json.loads(line)
                if not isinstance(row.get("text"), str) or not row["text"]:
                    raise ValueError("Each dataset row needs nonempty text")
                if "output_length" in row:
                    positive(row["output_length"], "output_length", integer=True)
                lines += 1
        if not lines:
            raise ValueError("Dataset is empty")
        workload["path"] = str(data.resolve())
        workload["sha256"] = file_digest(data)
    elif workload["type"] == "synthetic":
        positive(workload["input_tokens"], "input_tokens", integer=True)
    else:
        raise ValueError("Supported workload types: synthetic, single_turn")
    positive(workload["output_tokens"], "output_tokens", integer=True)
    bounds = config["load"]
    points = bounds["concurrency"]
    if not isinstance(points, list) or not points or len(points) != len(set(points)):
        raise ValueError("concurrency must be a nonempty list of distinct integers")
    for point in points:
        positive(point, "concurrency", integer=True)
    positive(bounds["requests"], "requests", integer=True)
    positive(bounds.get("max_attempts_per_point", 3), "max_attempts_per_point", integer=True)
    for key in ("duration_seconds", "request_timeout_seconds", "grace_seconds", "deadline_seconds"):
        positive(bounds[key], key)
    if bounds["deadline_seconds"] <= bounds["duration_seconds"] + bounds["grace_seconds"]:
        raise ValueError("deadline_seconds must allow duration, grace and startup")
    for metric in config.get("metrics", []):
        check_url(metric["url"])
        if not metric.get("name"):
            raise ValueError("Give each metrics producer a name")
        for requirement in metric.get("required", []):
            if not requirement.get("metric") or not requirement.get("why"):
                raise ValueError("Required metrics need metric and why")
    for key, value in config.get("goals", {}).items():
        if key not in ("ttft_p95_ms", "latency_p95_ms", "max_error_fraction"):
            raise ValueError(f"Unsupported goal: {key}")
        if key == "max_error_fraction":
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
                raise ValueError("max_error_fraction must be between 0 and 1")
        else:
            positive(value, key)
    if smoke:
        config["workload"] = {"type": "synthetic", "input_tokens": 16, "output_tokens": 16, "tokenizer": "builtin"}
        config["load"].update(concurrency=[1], requests=1)
    return config
