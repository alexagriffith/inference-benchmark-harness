"""Separate evidence completeness, request outcomes and declared goals."""

import json
import math
import os
from datetime import datetime
from pathlib import Path

from . import AIPERF_VERSION
from .config import file_digest


def finite_nonnegative(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w") as stream:
        json.dump(value, stream, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def manifest(directory):
    return {str(path.relative_to(directory)): file_digest(path)
            for path in sorted(directory.rglob("*")) if path.is_file() and path.name != "manifest.json"}


def analyze(directory, config, execution):
    invalid = []
    rows = []
    native = directory / "native"
    summary = {}
    failed = 0
    try:
        summary = json.loads((native / "profile_export_aiperf.json").read_text())
        with (native / "profile_export.jsonl").open() as stream:
            rows = [json.loads(line) for line in stream if line.strip()]
        if summary.get("aiperf_version") != AIPERF_VERSION or summary.get("schema_version") != "1.4":
            invalid.append("unsupported_export_version")
        if summary.get("was_cancelled"):
            invalid.append("native_cancelled")
        good = sum(not row.get("error") and not row.get("metadata", {}).get("was_cancelled")
                   and "request_latency" in row.get("metrics", {}) for row in rows)
        failed = len(rows) - good
        if not rows or len(rows) > config["load"]["requests"]:
            invalid.append("request_count_out_of_bounds")
        if 0 < len(rows) < config["load"]["requests"]:
            measured_seconds = (datetime.fromisoformat(summary["end_time"]) - datetime.fromisoformat(summary["start_time"])).total_seconds()
            if measured_seconds < config["load"]["duration_seconds"]:
                invalid.append("stopped_before_request_or_time_limit")
        aggregate_good = summary.get("request_count", {}).get("avg", 0)
        aggregate_bad = summary.get("error_request_count", {}).get("avg", 0)
        if aggregate_good != good or aggregate_bad != failed:
            invalid.append("request_counts_disagree")
        for row in rows:
            metadata = row.get("metadata", {})
            start, end = metadata.get("request_start_ns"), metadata.get("request_end_ns")
            if type(start) is not int or type(end) is not int or start <= 0 or end < start:
                invalid.append("invalid_request_timestamps")
            if not row.get("error") and "request_latency" not in row.get("metrics", {}):
                invalid.append("incomplete_request_record")
            if not row.get("error"):
                latency = row.get("metrics", {}).get("request_latency", {})
                if not isinstance(latency, dict) or latency.get("unit") != "ms" or not finite_nonnegative(latency.get("value")):
                    invalid.append("invalid_request_latency")
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        invalid.append("missing_or_malformed_client_evidence")
    if execution["exit_code"] != 0:
        invalid.append("client_process_failed")
    if execution.get("reason"):
        invalid.append(execution["reason"])
    coverage = []
    endpoints_with_samples, endpoint_info = set(), {}
    if config.get("metrics"):
        try:
            with (native / "server_metrics_export.jsonl").open() as stream:
                for line in stream:
                    if line.strip():
                        endpoints_with_samples.add(json.loads(line)["endpoint_url"])
            server = json.loads((native / "server_metrics_export.json").read_text())
            endpoint_info = server["summary"]["endpoint_info"]
        except (OSError, ValueError, KeyError, TypeError):
            endpoints_with_samples, endpoint_info = set(), {}
    for producer in config.get("metrics", []):
        covered = False
        try:
            fetches = endpoint_info[producer["url"]]
            starts = [row["metadata"]["request_start_ns"] for row in rows]
            ends = [row["metadata"]["request_end_ns"] for row in rows]
            # JSONL stores changed values; the fetch timeline includes unchanged scrapes.
            covered = (producer["url"] in endpoints_with_samples and fetches["total_fetches"] >= 2
                       and fetches["first_fetch_ns"] <= min(starts)
                       and fetches["last_fetch_ns"] >= max(ends))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            pass
        coverage.append({"producer": producer["name"], "window_covered": covered})
        if producer.get("required") and not covered:
            invalid.append("required_metrics_window_incomplete:" + producer["name"])
    goals = []
    for name, bound in config.get("goals", {}).items():
        if name == "max_error_fraction":
            measured = failed / len(rows) if rows else None
        else:
            key = "time_to_first_token" if name == "ttft_p95_ms" else "request_latency"
            metric = summary.get(key, {}) if isinstance(summary, dict) else {}
            measured = metric.get("p95") if isinstance(metric, dict) and metric.get("unit") == "ms" else None
        if measured is not None and not finite_nonnegative(measured):
            invalid.append("invalid_goal_measurement:" + name)
            measured = None
        goals.append({"goal": name, "limit": bound, "observed": measured,
                      "status": "unverified" if measured is None or invalid else "met" if measured <= bound else "missed"})
    if invalid:
        for goal in goals:
            goal["status"] = "unverified"
    return {"evidence": "invalid" if invalid else "complete", "reasons": sorted(set(invalid)),
            "requests": len(rows), "failed_requests": failed,
            "requested_limit": config["load"]["requests"], "metrics": coverage, "goals": goals,
            "claim": "Observed client behavior for this workload and run location; no policy attribution"}
