# Inference benchmark harness

Run a bounded AIPerf experiment against an existing streaming chat endpoint. Start with one short request, then run isolated concurrency or rate points. Keep native evidence, structured failure events and resumable campaign state.

The operator runs this package in their own environment with their own dataset. No dashboard, Prometheus database, KServe or OpenShift installation is required. Linux and macOS are supported; Windows users can use a Linux environment.

## Start

Use Python 3.11 or later and AIPerf 0.12.0. Install in your approved Python environment:

```sh
python3 -m pip install '.[runtime]'
make help
```

Copy `examples/benchmark.json` to your working directory. Set the served model, endpoint and approved traffic bounds. Keep results in a durable directory outside the source checkout.

```sh
make plan-smoke CONFIG=/path/to/benchmark.json RUN=/path/to/first-smoke
make verify CONFIG=/path/to/benchmark.json
make smoke CONFIG=/path/to/benchmark.json RUN=/path/to/first-smoke
make plan CONFIG=/path/to/benchmark.json RUN=/path/to/first-sweep
make sweep CONFIG=/path/to/benchmark.json RUN=/path/to/first-sweep
make report RUN=/path/to/first-sweep
```

`plan` previews the configured sweep; `plan-smoke` previews only the one-request smoke. Both show commands and request budgets without executing them. `verify` checks the runtime and reads the configured model listing, metrics and optional Kubernetes readiness, route/pool and objective bindings. Neither preview nor verification sends inference. `smoke` sends one generated request with a 16-token output limit. `sweep` uses your workload and runs load points in order. Choose a new output directory for each campaign.

The example's 1/2/4 concurrency and 20-request limit qualify mechanics; they are not calibrated capacity settings. Each point stops sending at its request limit or duration, whichever comes first. Grace allows outstanding requests to finish; the outer deadline also bounds startup and export. There is no implicit warmup. Plan warmup, repeated measurements and longer steady windows before making performance claims.

## Choose the workload

Generated prompts use the built-in tokenizer without downloading a model. Its tokenization need not match the server. Server-reported token counts are used for results; missing usage stays unknown. Supply an approved local tokenizer if exact generated input length matters.

For a local JSONL dataset, replace the workload block:

```json
{
  "type": "single_turn",
  "path": "prompts.jsonl",
  "output_tokens": 64,
  "tokenizer": "builtin"
}
```

Each line contains `{"text":"A prompt","output_length":64}`. Paths are relative to the configuration file. A row's `output_length` can override the default; inspect these limits when preparing your workload. This version qualifies independent single-turn chat calls. Multi-turn conversations, raw application payloads, tools and arrival-time replay need separate adapters and tests.

Optional `goals` supports `ttft_p95_ms`, `latency_p95_ms` and `max_error_fraction`. Use your actual targets; an empty object records measurements without claiming a performance pass. Optional `endpoint.headers` carries non-secret routing headers. Set `endpoint.api_key_env` to an environment variable name for bearer authentication. `endpoint.models_path` can be `null` when no listing API exists; model identity then remains unverified until smoke and server attribution.

## Choose concurrency or arrival rate

Use `load.concurrency: [1, 2, 4]` to maintain a selected number of outstanding requests. To prescribe arrivals instead, replace that field with:

```json
{
  "rates": [0.5, 1, 2],
  "arrival": "constant",
  "max_concurrency": 4
}
```

Keep the other `load` limits. Rates are requests per second; fractional values are allowed. Choose `constant` for regular arrivals or `poisson` for randomized arrivals at a target average. AIPerf performs the scheduling. The concurrency cap prevents unlimited outstanding work, so a rate target is not a guarantee of achieved arrivals under pressure. Inspect native request timestamps and actual throughput.

Select exactly one axis per campaign. Points run sequentially in the supplied order with the same evidence and resume rules. `smoke` always uses one generated request at concurrency one, including with a rate configuration. These modes do not replay production arrival timestamps or prove that a synthetic workload represents production.

## Read the outcome

Every attempt keeps the exact command, preflight findings, execution status, native exports, summary and checksums. `events.jsonl` is an append-only dashboard input; `state.json` is an atomic checkpoint. Completion means the configured points were processed, not that a latency goal or policy claim passed.

If a campaign stops, inspect its reason before `make resume CONFIG=... RUN=...`. Completed points are retained. A missed goal advances to the next point only on deliberate resume; it is never rerun to obtain a better result. Failed attempts remain visible. See [failure handling](docs/failures.md).

Native artifacts can contain prompts, responses and operational metadata. Keeping those artifacts locally is normal. Review and select what to share according to your environment's requirements.

## Run and verify

- [Workstation and cluster execution](docs/run-locations.md)
- [Metrics and New Relic](docs/metrics.md)
- [Validation and current limits](docs/validation.md)
- [Choose the next experiment](docs/next-steps.md)

```sh
make test
make test-integration AIPERF=/path/to/aiperf
```

The integration test starts a loopback HTTP fixture and runs the actual AIPerf executable. It needs no GPU, Kubernetes cluster or production endpoint.

Licensed under Apache-2.0. AIPerf remains a separate dependency with its own license and notices.
