"""Command-line entry point for the benchmark harness."""

import argparse
import json
from pathlib import Path
import signal
import sys

from .config import load, load_points
from .preflight import verify
from .runner import campaign, command


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    for name in ("plan", "verify", "run"):
        child = sub.add_parser(name)
        child.add_argument("--config", required=True)
        child.add_argument("--aiperf", default="aiperf")
        child.add_argument("--smoke", action="store_true")
        if name != "verify":
            child.add_argument("--run", required=True)
        if name == "run":
            child.add_argument("--execute", action="store_true", required=True)
            child.add_argument("--resume", action="store_true")
    report = sub.add_parser("report")
    report.add_argument("--run", required=True)
    args = parser.parse_args()
    def interrupted(signum, frame):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    try:
        if args.action == "report":
            root = Path(args.run)
            result = {"state": json.loads((root / "state.json").read_text()),
                      "attempts": {str(path.parent.name): json.loads(path.read_text()) for path in sorted(root.glob("point-*/summary.json"))}}
        else:
            config = load(args.config, args.smoke)
            if args.action == "plan":
                points, bounds = load_points(config), config["load"]
                requests = len(points) * bounds["requests"]
                result = {
                    "status": "plan_only",
                    "budget": {
                        "points": len(points), "requests_per_point": bounds["requests"],
                        "max_requests_first_pass": requests,
                        "max_requests_with_manual_retries": requests * bounds.get("max_attempts_per_point", 3),
                        "process_deadline_seconds_per_attempt": bounds["deadline_seconds"],
                        "automatic_inference_retries": 0,
                    },
                    "commands": [command(config, point, Path(args.run).resolve() / f"point-{index + 1:02d}-attempt-{index + 1:03d}", args.aiperf)
                                 for index, point in enumerate(points)],
                }
            elif args.action == "verify":
                result = {"checks": verify(config, args.aiperf)}
                result["status"] = "preflight_failed" if any(c["status"] == "fail" for c in result["checks"]) else "ready_for_smoke"
            else:
                result = campaign(config, args.run, args.aiperf, args.resume)
        print(json.dumps(result, indent=2))
        return 0 if result.get("status", "complete") in ("complete", "ready_for_smoke", "plan_only") else 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"Cannot continue: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Interrupted; inspect the saved campaign state before resuming", file=sys.stderr)
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
