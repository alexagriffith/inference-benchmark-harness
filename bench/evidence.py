"""Separate evidence completeness, request outcomes and declared goals."""

import json
import os
from datetime import datetime
from pathlib import Path

from . import AIPERF_VERSION
from .config import file_digest


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
            if metadata.get("request_end_ns", 0) < metadata.get("request_start_ns", 0) or not metadata.get("request_start_ns"):
                invalid.append("invalid_request_timestamps")
            if not row.get("error") and "request_latency" not in row.get("metrics", {}):
                invalid.append("incomplete_request_record")
    except (OSError, ValueError, KeyError, TypeError):
        invalid.append("missing_or_malformed_client_evidence")
    if execution["exit_code"] != 0:
        invalid.append("client_process_failed")
    if execution.get("reason"):
        invalid.append(execution["reason"])
    coverage = []
    for producer in config.get("metrics", []):
        covered = False
        try:
            samples = [json.loads(line) for line in (native / "server_metrics_export.jsonl").read_text().splitlines() if line.strip()]
            updates = [row for row in samples if row.get("endpoint_url") == producer["url"]]
            server = json.loads((native / "server_metrics_export.json").read_text())
            fetches = server["summary"]["endpoint_info"][producer["url"]]
            starts = [row["metadata"]["request_start_ns"] for row in rows]
            ends = [row["metadata"]["request_end_ns"] for row in rows]
            # JSONL stores changed values; the fetch timeline includes unchanged scrapes.
            covered = (bool(updates) and fetches["total_fetches"] >= 2
                       and fetches["first_fetch_ns"] <= min(starts)
                       and fetches["last_fetch_ns"] >= max(ends))
        except (OSError, ValueError, KeyError, TypeError):
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
            metric = summary.get(key, {})
            measured = metric.get("p95") if metric.get("unit") == "ms" else None
        goals.append({"goal": name, "limit": bound, "observed": measured,
                      "status": "unverified" if measured is None or invalid else "met" if measured <= bound else "missed"})
    return {"evidence": "invalid" if invalid else "complete", "reasons": sorted(set(invalid)),
            "requests": len(rows), "failed_requests": failed,
            "requested_limit": config["load"]["requests"], "metrics": coverage, "goals": goals,
            "claim": "Observed client behavior for this workload and run location; no policy attribution"}
