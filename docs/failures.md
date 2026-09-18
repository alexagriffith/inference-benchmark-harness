# Failure handling

| Condition | Automatic behavior | Operator action |
|---|---|---|
| Temporary connection failure or HTTP 502/503/504 during a read-only check | At most three reads, with 1-second and 2-second delays | Fix the path if the check remains unavailable |
| Wrong model, rejected authentication, unready deployment or missing required metric | Stop before inference | Restore the planned precondition, then resume; changed experiment configuration needs a new run |
| AIPerf exits unsuccessfully, exceeds its deadline or leaves incomplete exports | Stop and preserve the attempt | Inspect logs and evidence; deliberate resume makes a new attempt |
| Interrupt or termination signal | Terminate the process group owned by this run and save the outcome | Inspect the partial attempt before resume |
| Valid measurement misses a goal or includes request errors | Retain the measurement and stop increasing load | Resume advances to the next point, without rerunning this result |
| Previous supervisor vanished without a checkpoint | Refuse automatic recovery | Reconcile running processes and evidence; use a new campaign after resolving ownership |
| Configuration, dataset or accepted evidence changed | Refuse to skip or resume under the old identity | Create a new experiment with the changed inputs |

Inference traffic is never automatically retried. A point permits three attempts by default, including preflight failures; configure `load.max_attempts_per_point` before the campaign if needed. Reaching this limit calls for diagnosis. The harness does not generate runtime patches, alter serving configuration or loosen goals.

The campaign lock prevents simultaneous owners on a local filesystem. Shared filesystems must support advisory locks and atomic rename. Keep one operator per output directory. Kubernetes Job retries are disabled in the example because a new pod must not silently replay traffic.

Stopping the client does not prove that every serving layer cancelled its work. After an interruption or timeout, verify that the previous traffic has drained before deliberately resuming. Use the engine and router signals appropriate to your deployment.

The free-space check catches an almost-full output filesystem; it is not a prediction of the run's artifact size. Size durable storage for your request count and payloads. If a collector or runner is evicted, incomplete evidence remains incomplete.

`events.jsonl` records timestamps, event codes, point and attempt identifiers, reasons and next actions. `retryable` describes whether a corrected preflight can be retried; it does not authorize automatic inference replay. The native log supplies deeper diagnostics.

## Find the failing layer

Use the failed attempt's `preflight.json`, `aiperf.log`, `summary.json` and native exports. A fix starts a new attempt or experiment; it does not rewrite the old evidence.

| Symptom | Likely layer | First check | Next owner or action |
|---|---|---|---|
| Name resolution, connection or certificate failure | Run location / network / trust | Check the exact configured host and port from the runner's network; inspect the certificate chain and approved proxy path | Network or platform owner; configure the approved trust path, then verify again |
| HTTP 401/403 | Authentication / authorization | Confirm the environment variable is set without printing its value; inspect the endpoint's required authentication scheme | API owner; use an approved identity |
| Model not listed or HTTP 404 | API path / served name | Compare the configured path and model with the serving API; model-list endpoints may be disabled intentionally | Serving owner; set `models_path` to null only when unavailable, then qualify with a smoke request |
| Route resolves but requests fail at external processing | Gateway / mesh / picker transport | Inspect current route and Gateway conditions, Service port, mesh logs and custom filter behavior | Gateway or mesh owner; preserve required mutual TLS |
| HTTP 200 but wrong class or backend | Routing / objective mapping | Compare the selected route rule, positive-weight backends, objective binding and request header; correlate actual server attribution | Routing owner; configuration checks alone do not establish request classification |
| Extra pods or mismatched image IDs during rollout | Deployment | Inspect selected Ready pods and rollout generation; wait for the intended stable population | Deployment owner; do not accept mixed old/new settings as one point |
| Source metric exists but New Relic has no current series | Collection / ingestion | Check target discovery, scrape success, filters, labels and run-time samples | Monitoring owner; retain direct evidence if available and state the remaining limitation |
| Requests finish but AIPerf does not export | Client processing | Check the native log, process outcome, processor count and available CPU/memory | Benchmark operator; preserve the attempt and diagnose before deliberate resume |
| Completed evidence exceeds the latency goal | Serving / load / workload | Compare same-window engine queue, cache, token lengths, router queue and platform pressure | Retain the result; follow the decision guide before changing one experimental variable |
| Timeout or eviction leaves partial files | Runner / storage / platform | Check the saved reason, free storage, Job termination status and surviving traffic | Operator and platform owner; recover artifacts and confirm drain before another attempt |

[Interpret valid results and choose the next experiment](next-steps.md).
