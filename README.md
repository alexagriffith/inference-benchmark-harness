# Inference benchmark harness

Run bounded AIPerf tests against an existing streaming Chat Completions endpoint. Preserve each attempt and validate it before continuing.

## Install and configure

Python 3.11+ on Linux or macOS. AIPerf is pinned to 0.12.0.

```sh
python3 -m pip install '.[runtime]'
cp examples/benchmark.json /path/benchmark.json
```

Edit the copy before running:

| Input | Set |
|---|---|
| `endpoint` | Reachable URL, served model, API path; routing headers and token environment variable if needed |
| `workload` | Generated token lengths or a local single-turn JSONL file |
| `load` | Concurrency **or** arrival-rate points, repeats and execution limits |
| `goals` | Optional latency/error limits; keep `{}` for discovery |
| `metrics` | Producer URLs and required metric names with their purpose |
| `kubernetes` | Optional explicit context, expected replicas and routing checks |

Example values check mechanics; choose representative inputs and bounded load for your experiment. [Operator guide](docs/operator-guide.md) · [Metric reference](docs/metrics.md).

## Run

From the checkout, use separate durable output directories:

```sh
make plan-smoke CONFIG=/path/benchmark.json RUN=/path/results/smoke
make verify CONFIG=/path/benchmark.json
make smoke CONFIG=/path/benchmark.json RUN=/path/results/smoke
make plan CONFIG=/path/benchmark.json RUN=/path/results/sweep
make benchmark CONFIG=/path/benchmark.json RUN=/path/results/sweep
make report RUN=/path/results/sweep
```

| Command | Behavior |
|---|---|
| `plan`, `plan-smoke` | Preview commands and request budgets; no network or writes |
| `verify` | Read runtime, model listing, metrics and optional Kubernetes checks; no inference |
| `smoke` | One generated request, at most 16 output tokens |
| `benchmark` / `sweep` | Sequential points × repeats; check each attempt before continuing |
| `report` | Read saved status; incomplete or unsuccessful campaigns return nonzero |
| `resume` | Deliberately continue the same config and run directory after diagnosis |

The example uses **three valid repeats per point**. Invalid evidence stops immediately. A valid goal miss or request error is retained; remaining repeats at that point finish before higher load is stopped. Inference is never automatically retried. See [recovery](docs/operator-guide.md#recovery) before using `make resume CONFIG=/path/benchmark.json RUN=/path/results/sweep`.

## Scope and evidence

One configuration describes one workload, endpoint and fixed topology. The harness does not deploy, scale or tune serving policies. No KServe, OpenShift or Prometheus database is required. Multi-turn, tools, Responses API, arrival-time replay, coordinated endpoints and New Relic querying are outside V1.

Results retain native AIPerf files, config, commands, checks, summaries and timestamped provenance. Native files may contain prompts and operational data; keep them in your environment and select what to share. [Storage and timestamps](docs/operator-guide.md#evidence-and-storage).

## Test

```sh
make test
make test-integration AIPERF=/path/to/aiperf
```

Integration uses real AIPerf against a local simulated server, with no GPU or cluster. It checks payloads, authentication, pacing, repeats, metric collection and failure handling. It does not establish model performance or deployment compatibility. [Container and Job instructions](docs/operator-guide.md#execution-environment).

Apache-2.0. AIPerf is a separate dependency with its own license.
