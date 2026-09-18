# Operator guide

A campaign answers: **How does this workload behave across the tested load points on this fixed deployment?** Goals add acceptance limits; they are not required to collect a baseline.

## Run sequence

`plan → verify → smoke → inspect/drain → benchmark → report`

Within a benchmark: `check → run → validate → checkpoint`, repeated for every repeat at every point. One Python supervisor invokes AIPerf child processes; these modules are not separate pods. AIPerf generates traffic and exports measurements. The supervisor decides whether to continue.

A smoke checks the request path; it does not warm every replica or establish steady state. Before measured runs, the operator establishes cache/warmup conditions and confirms earlier traffic has drained. Keep model/image, tensor parallelism, replica count, route, serving limits and run location fixed. Save the serving owner's effective configuration separately; a declared object does not prove a process loaded it.

## Workload

For generated input, set `input_tokens`, `output_tokens` and `tokenizer` in the example. The built-in tokenizer needs no model download but may differ from the server. Use an approved matching local tokenizer when exact generated lengths matter. Results use server-reported token counts; missing usage stays unknown.

For private single-turn prompts, replace the workload block:

```json
{"type":"single_turn", "path":"prompts.jsonl", "output_tokens":64, "tokenizer":"builtin"}
```

Each JSONL line is `{"text":"A prompt","output_length":64}`. Paths are relative to the config file. A row's `output_length` overrides the default. This input does not preserve conversation history, tool execution or production arrival timing.

Keep the input/output length distribution, request mix, shared prefixes and cache state representative. An output limit is a ceiling, not a guarantee that the model generates that many tokens. Reusing identical prompts can warm caches and change later results.

## Targets

Example only—replace these values with agreed application requirements:

```json
"goals": {
  "ttft_p95_ms": 500,
  "latency_p95_ms": 5000,
  "max_error_fraction": 0.01
}
```

These mean p95 time to first token at most 500 ms, p95 whole-request latency at most 5 seconds, and errors at most 1%. Latency and error goals are evaluated separately; an error is not a fast successful response. A p95 target is not a maximum-latency guarantee. Long answers need an appropriate whole-request target. Inter-token latency and per-workload-class goals are not implemented gates.

Omit a goal you have not agreed. Empty goals collect measurements without asserting a target pass. Three requests or 20 requests cannot establish reliable tail behavior; choose observation length and repeat count for the decision and observed variability. Set `load.repeats` (example: 3) and `load.max_attempts_per_repeat` (example: 3). A repeat is one measurement; a replacement attempt only repairs invalid execution.

A first discovery sweep can use `"goals": {}` (or omit the field). The evaluator then emits measurements with no goal verdicts. Configuration validation checks supported goal names and numeric limits; `bench/evidence.py` compares each supplied limit with observed values, and `bench/runner.py` controls progression. These are harness checks, not AIPerf CLI flags or Kubernetes InferenceObjectives.

Without goals, invalid evidence still stops immediately. The current runner also retains request errors, finishes repeats at that point and stops before higher load—even when an explicit error-fraction goal would tolerate those errors. That conservative progression rule is separate from target evaluation. Add agreed goals in a new campaign; changing goals changes the configuration fingerprint and is not a same-config resume.

## Load

Choose one axis per campaign:

| Shape | Fields | Meaning |
|---|---|---|
| Closed loop | `"concurrency": [1, 2, 4]` | Maintain up to this many outstanding requests |
| Regular arrivals | `"rates": [0.5, 1, 2], "arrival": "constant", "max_concurrency": 4` | Target requests/second with regular spacing and an outstanding-request cap |
| Random arrivals | Same rate fields, `"arrival": "poisson"` | Random arrival gaps at the target average, subject to the cap |

Keep the remaining `load` limits. A binding cap can prevent the desired arrival rate; compare actual arrivals and achieved throughput. Three Poisson requests do not validate a distribution.

**Starting procedure:** smoke at one; choose a conservative, bounded increasing range; inspect the first valid target miss before adding load. If pass/fail points bracket a useful boundary, try intermediate points in a new campaign. Repeat near that boundary; do not assume noisy results are monotonic. A valid unfavorable result remains evidence. No automatic midpoint search or warmup is performed.


## Matrix and next steps

One config expands to **load points × repeats**. `[1, 2, 4]` with three repeats produces nine measurements. `make plan` prints the commands and request budget. A request count or duration ends sending, whichever comes first; grace allows outstanding requests to finish. The process deadline includes AIPerf startup and export, but not all pre/postflight reads or hashing. Give a Job sufficient overall time.

| Evidence | Next experiment |
|---|---|
| Verify or smoke fails | Fix the named check; preserve the failed attempt |
| Discovery sweep completes without goals | Inspect latency, throughput, errors and variation; agree targets before judging suitability |
| Target met or missed near a boundary | Test a bounded intermediate range in a new campaign; retain unfavorable results |
| Another fixed replica count is needed | Operator changes deployment, waits for readiness, updates expected replicas and starts a new campaign |
| Priority or fairness is the question | Plan overlapping demand and suitable equal-priority/isolated controls outside this single-workload runner |

Any positive expected replica count is supported. Replicas are not GPU counts: tensor parallelism and device sharing determine GPU use. The harness neither scales nor coordinates multiple configurations. Benchmark `goals` evaluate client latency/errors; Kubernetes InferenceObjectives classify requests. They are separate inputs. A disabled flow-control gate does not prove every detector/filter is inactive.

## Kubernetes checks

Add this block when the runner has read access through kubectl:

```json
{
  "kubernetes": {
    "context": "YOUR_CONTEXT",
    "deployments": [
      {"namespace": "inference", "name": "model-server", "replicas": 1},
      {"namespace": "inference", "name": "endpoint-picker", "replicas": 1}
    ]
  }
}
```

The runner reads Deployments and selected pods, checks rollout convergence and records image identities. It never scales them. Use your deployment owner to establish the experiment's replica count; preserve tensor parallelism, model, cache settings and other serving parameters. One replica may still use multiple GPUs.

To verify llm-d object bindings, add `routing` inside `kubernetes`:

```json
{
  "routing": {
    "namespace": "inference",
    "model_deployment": "model-server",
    "picker_deployment": "endpoint-picker",
    "pool": "model-pool",
    "route": "model-route",
    "rule_index": 0,
    "gateway": {"namespace": "gateway-system", "name": "inference-gateway"},
    "objectives": [{"name": "interactive", "priority": 10}],
    "selected_objective": "interactive"
  }
}
```

For this example, also set `endpoint.headers` to `{"x-llm-d-inference-objective":"interactive"}`. The runner verifies pool/model and picker-Service ownership, current Gateway/HTTPRoute acceptance, the selected rule's pool references, objective pool/priority bindings and the configured header. `rule_index` is zero-based. Confirm the actual request matches that rule's path, host and header conditions; the report includes its matches. All declared model/picker Deployments must also appear in the readiness list.

An objective's missing or stale controller status is `unverified`, not a failed declared binding. A current explicit rejection fails the check. When a custom application maps a client field to an objective, omit `selected_objective` unless the benchmark directly sets the objective header; capture the actual classification separately.

These checks do not prove custom filters, effective scheduling policy or actual request classification. Use matching gateway/router evidence from smoke for those claims. The endpoint-only path remains available when the runner cannot use the Kubernetes API. Kubernetes read permissions are needed for the selected namespaces' Deployments, pods, Services, Gateways, HTTPRoutes, InferencePools and InferenceObjectives; no write permission is used.

Before comparing policies, the serving owner should record the actual picker image ID, startup arguments, mounted scheduling configuration and the version-specific loaded configuration reported by the process, when available. Compare the running pod with the deployment owner's intended configuration. Editing a ConfigMap or higher-level serving resource alone does not prove the process loaded it. If effective controls cannot be established, retain that uncertainty and do not attribute a latency change to a particular policy.


## Execution environment

| Location | Required checks |
|---|---|
| Approved Python host | Endpoint/metric access, identity, CA trust, CPU capacity and durable storage |
| Local container | Same checks from inside the container; writable results and scratch directories |
| Kubernetes Job | Approved image, architecture, service DNS, mesh identity, volumes and Job completion |

For an authorized local tunnel, use an explicit context in a separate terminal:

```sh
kubectl --context YOUR_CONTEXT -n YOUR_NAMESPACE port-forward service/YOUR_GATEWAY 8000:80
```

Use `http://127.0.0.1:8000` from the host. Forward individual metric producers separately. A container's loopback belongs to that container; qualify its actual endpoint path. Tunnel latency is included in client timing, so prefer a stable direct path for performance comparisons. Stop only your own tunnels.

Build the supplied multi-stage image with your approved builder:

```sh
docker build -f Containerfile -t inference-benchmark-harness:0.1.0 .
docker run --rm --read-only --tmpfs /tmp:rw,size=512m \
  -v "$PWD/tests:/opt/harness/tests:ro" \
  -v "$PWD/examples:/opt/harness/examples:ro" \
  -v /path/to/test-artifacts:/results:rw -e TMPDIR=/results \
  --entrypoint python inference-benchmark-harness:0.1.0 \
  tests/integration.py --aiperf /opt/venv/bin/aiperf
```

Results must be writable by UID 10001. Adapt [the Job example](../examples/job.yaml) to an approved image and existing input/output PVCs. It uses no API token, requires no GPU and disables Job retries. The default image contains no kubectl: enable Kubernetes checks only in an environment providing kubectl and the required read permissions. Check sidecar completion, CA trust and network policy; preserve required mutual TLS.

If the base image is unavailable or unapproved, rebuild on an approved Python 3.11+ Linux base or install in an approved virtual environment. Match builder/runtime libraries, registry and dependency mirror; rerun unit tests, fixture integration, verify and smoke. A different image requires qualification, not just a changed `FROM` line. The example does not imply organizational approval.

## Recovery

| Condition | Automatic behavior | Operator action |
|---|---|---|
| Temporary connection failure or HTTP 502/503/504 during a read-only check | At most three reads, with 1-second and 2-second delays | Fix the path if the check remains unavailable |
| Wrong model, rejected authentication, unready deployment or missing required metric | Stop before inference | Restore the planned precondition, then resume; changed experiment configuration needs a new run |
| AIPerf exits unsuccessfully, exceeds its deadline or leaves incomplete exports | Stop and preserve the attempt | Inspect logs and evidence; deliberate resume makes a new attempt |
| Interrupt or termination signal | Terminate the process group owned by this run and save the outcome | Inspect the partial attempt before resume |
| Valid measurement misses a goal or includes request errors | Retain it, finish the declared repeats at this load, then stop before higher load | Resume advances after those repeats, without rerunning accepted results |
| Previous supervisor vanished without a checkpoint | Refuse automatic recovery | Reconcile running processes and evidence; use a new campaign after resolving ownership |
| Configuration, dataset or accepted evidence changed | Refuse to skip or resume under the old identity | Create a new experiment with the changed inputs |

Inference traffic is never automatically retried. Each repeat permits three attempts by default, including preflight failures; configure `load.max_attempts_per_repeat` before the campaign. The legacy `max_attempts_per_point` name remains accepted when the new name is absent. Reaching this limit calls for diagnosis. The harness does not generate runtime patches, alter serving configuration or loosen goals.

The campaign lock prevents simultaneous owners on a local filesystem. Shared filesystems must support advisory locks and atomic rename. Keep one operator per output directory. Kubernetes Job retries are disabled in the example because a new pod must not silently replay traffic.

Stopping the client does not prove that every serving layer cancelled its work. After an interruption or timeout, verify that the previous traffic has drained before deliberately resuming. Use the engine and router signals appropriate to your deployment.

The free-space check catches an almost-full output filesystem; it is not a prediction of the run's artifact size. Size durable storage for your request count and payloads. If a collector or runner is evicted, incomplete evidence remains incomplete.


The client inherits the campaign lock. Do not delete a lock file to bypass ownership; resolve surviving owned processes first. Cleanup is bounded, best-effort signaling of the launched process group; it does not cover escaped descendants or prove remote serving cancellation. `report` distinguishes incomplete work, invalid evidence and goal misses through its saved status and exit code.

## Debugging

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

## Evidence and storage

Each run directory contains configuration, state, events and a provenance ledger. Each attempt retains pre/postflight checks, command, execution outcome, AIPerf log, native exports, summary and checksums. Point summaries compare accepted repeats. Their p95 range is neither a pooled percentile nor a confidence interval.

Native exports can contain prompts and operational data even when raw-response export is disabled. Retain them under your data policy. Storage grows with requests, prompt size, scrape dimensions and repeat/attempt count; measure a small run before budgeting a large one. The 64 MiB free-space guard is not a size estimate. A New Relic dashboard is not a replacement for resumable state or native client evidence; [collection details](metrics.md#collection-and-new-relic).

| Field | Meaning |
| --- | --- |
| `started`, `finished` | When an operation began and ended on the runner |
| `recorded` | When its ledger entry was written |
| `timestamp_ns` | Integer Unix time in nanoseconds, matching AIPerf request timestamp units |
| `timestamp_utc` | The same instant as UTC text, with nine fractional digits and `Z` |
| `duration_ns` | Elapsed time from a monotonic clock; unaffected by wall-clock adjustments |
| `artifact`, `sha256` | Relative file path and hash of the saved contents |


Acquisitions, errors and saved artifacts are recorded in `provenance.jsonl`. Acquisition times describe when the runner read a config or endpoint, not when the remote configuration changed. Native files keep their original format; provenance records when they were observed and hashed. Use AIPerf's request/scrape times for measurement.

Use durable output storage with working advisory locks and atomic rename. Collect evidence before deleting a Job or its volumes. Hard failure can occur between a save and its ledger entry; absent provenance is not reconstructed. Clock synchronization is required across hosts. JavaScript readers should display UTC text or use lossless integers for nanosecond timestamps. The ledger hashes prior state versions but does not archive every overwritten state file.
