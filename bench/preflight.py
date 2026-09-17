"""Read-only checks with bounded retries for temporary transport failures."""

import json
import os
import re
import subprocess
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from . import AIPERF_VERSION


def fetch(url, headers=None):
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=headers or {}), timeout=10) as response:
                data = response.read(8 * 1024 * 1024 + 1)
            if len(data) > 8 * 1024 * 1024:
                raise ValueError("Read exceeded 8 MiB")
            return data.decode(), attempt + 1
        except HTTPError as exc:
            exc.close()
            if exc.code not in (502, 503, 504) or attempt == 2:
                raise ValueError(f"HTTP {exc.code}; verify endpoint, access and service health") from None
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 2:
                raise ValueError("Transport unavailable after 3 reads; verify network, TLS and service health") from None
        time.sleep(attempt + 1)
    raise AssertionError("unreachable")


def verify(config, aiperf):
    checks = []
    if config.get("kubernetes"):
        from .kubernetes import inspect
        checks.extend(inspect(config))
    try:
        process = subprocess.run([aiperf, "--version"], capture_output=True, text=True, timeout=20)
        ok = process.returncode == 0 and process.stdout.strip() == AIPERF_VERSION
        checks.append({"name": "runtime", "status": "pass" if ok else "fail", "detail": f"Requires AIPerf {AIPERF_VERSION}"})
    except (OSError, subprocess.TimeoutExpired):
        checks.append({"name": "runtime", "status": "fail", "detail": "Install AIPerf or set AIPERF to its executable"})
    endpoint = config["endpoint"]
    headers = dict(endpoint.get("headers", {}))
    key = endpoint.get("api_key_env")
    if key:
        if not os.environ.get(key):
            checks.append({"name": "authentication", "status": "fail", "detail": f"Set {key} in the execution environment"})
            return checks
        headers["Authorization"] = "Bearer " + os.environ[key]
    if endpoint.get("models_path"):
        try:
            body, attempts = fetch(endpoint["url"].rstrip("/") + endpoint["models_path"], headers)
            models = [row["id"] for row in json.loads(body)["data"]]
            checks.append({"name": "model", "status": "pass" if endpoint["model"] in models else "fail", "attempts": attempts, "detail": "Served model listing; route attribution still requires server evidence"})
        except (ValueError, KeyError, TypeError):
            checks.append({"name": "model", "status": "fail", "detail": "Cannot confirm model listing; check models_path, model and access"})
    else:
        checks.append({"name": "model", "status": "unverified", "detail": "No model-list API configured; smoke must check inference"})
    for producer in config.get("metrics", []):
        try:
            body, attempts = fetch(producer["url"])
            names = set(re.findall(r"^([^#\s{]+)(?:\{|\s)", body, re.M))
            missing = [item for item in producer.get("required", []) if item["metric"] not in names]
            checks.append({"name": producer["name"], "status": "fail" if missing else "pass", "attempts": attempts, "missing": missing, "metric_names": sorted(names)})
        except ValueError as exc:
            checks.append({"name": producer["name"], "status": "fail" if producer.get("required") else "unverified", "detail": str(exc)})
    return checks
