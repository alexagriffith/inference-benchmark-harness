# Diagnose a failed check

Run `make verify CONFIG=/path/to/benchmark.json`. It reads configured targets without inference and prints named checks, discovered `metric_names`, and any `missing` requirements. Save its JSON output with your run notes. There is no separate `debug` command.

| Symptom | Inspect | Action |
|---|---|---|
| Required name missing | `metric_names`, `missing`, producer URL and actual exporter version | If the new name has equivalent meaning, edit `metrics[].required[].metric`; keep `why`. A changed config starts a new run. |
| Metric exists for wrong model/pod | Producer identity, source labels, collection filters | Correct the target or selector. A matching name alone does not establish attribution. |
| Units or histogram changed | Source type/unit and monitoring ingestion mapping | Correct the conversion/query. Do not fix a semantic mismatch with a name-only alias. |
| HTTP 401/403 or TLS failure | Identity, certificate trust and approved route | Correct access. Inference bearer credentials do not configure metric-producer authentication. |
| Monitoring samples missing/stale | Collector status, ingestion lag, query filters and exact run window | Missing is not zero. Hold claims needing that evidence; direct collection can be used when approved. |
| Model-list 404 | Gateway routes and `endpoint.models_path` | If listing is intentionally absent, set it to null; verify the served model using smoke and server evidence. No KServe dependency is assumed. |
| Native export incomplete | `execution.json`, `aiperf.log`, native directory and storage | Preserve the attempt; diagnose before deliberate resume. |
| Pod replaced/restarted | `preflight.json` and `postflight.json` when enabled | Reestablish a stable deployment; preserve the invalid run and plan a fresh comparison. |

New Relic query/import, unit conversion and source-to-ingested metric mapping are not implemented adapters. Validate those externally for the exact collection path. Direct preflight currently validates metric names, not label attribution or full time-series semantics. Configuration changes do not alter historical results.
