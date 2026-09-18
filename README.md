# Inference benchmark harness

Run bounded AIPerf tests against an existing streaming Chat Completions endpoint. Preserve each attempt and validate it before continuing.

## Install and configure

Python 3.11+ on Linux or macOS. AIPerf is pinned to 0.12.0.

```sh
python3 -m pip install '.[runtime]'
cp examples/benchmark.json /path/benchmark.json
```

Edit the copy before running:

| Input | You supply | Example / omission behavior |
|---|---|---|
| `endpoint` | URL, served model, API path; required headers/authentication | Example uses localhost and a placeholder model; no headers or token |
| `workload` | Representative token lengths or local single-turn JSONL | Synthetic 128 input / 64 output tokens; built-in tokenizer |
| `load` | Load points, repeats and execution limits | Concurrency 1, 2, 4; three repeats. Omitting `repeats` uses **one** |
| `goals` | Agreed latency/error limits, when known | `{}` collects a baseline without a target pass |
| `metrics` | Required producer URLs, names and purpose | `[]` collects no server metrics; insufficient for flow-control claims |
| `kubernetes` | Context, expected replicas and routing objects if inspecting the cluster | Omitted: no Kubernetes identity/routing checks |

Example budgets: **20 requests or 60 seconds per repeat**, 30-second request timeout, 35-second grace and 180-second process deadline. Three attempts per repeat are allowed through deliberate recovery; inference is not automatically retried. These are mechanics values, not calibrated workload or capacity recommendations. See [defaults and fixed behavior](docs/operator-guide.md#defaults-and-fixed-behavior).

## Run

From the checkout, replace `/path/...` with your config and durable output paths. Complete each check before the next step; preserve failures and use [debugging](docs/operator-guide.md#debugging) if a command fails.

1. Preview the smoke command and budget; confirm the endpoint and inputs.

   ```sh
   make plan-smoke CONFIG=/path/benchmark.json RUN=/path/results/smoke
   ```

2. Verify access, runtime and required metrics. Continue only when the result is `ready_for_smoke`.

   ```sh
   make verify CONFIG=/path/benchmark.json
   ```

3. Send one short smoke request. Check its evidence; establish [cache/warmup and drain conditions](docs/operator-guide.md#run-sequence) before measuring.

   ```sh
   make smoke CONFIG=/path/benchmark.json RUN=/path/results/smoke
   ```

4. Preview the measured sweep, then execute the reviewed budget in a separate directory.

   ```sh
   make plan CONFIG=/path/benchmark.json RUN=/path/results/sweep
   make benchmark CONFIG=/path/benchmark.json RUN=/path/results/sweep
   ```

5. Read the saved status and repeat summaries. An incomplete or unsuccessful campaign returns nonzero; `complete` without goals does not establish suitability.

   ```sh
   make report RUN=/path/results/sweep
   ```

`make help` lists commands. Plans send no traffic or network requests; `verify` reads endpoints but sends no inference. `benchmark` is an alias for `sweep`.

The example uses **three valid repeats per point**. Invalid evidence stops immediately. A valid goal miss or request error is retained; remaining repeats at that point finish before higher load is stopped. Inference is never automatically retried. See [recovery](docs/operator-guide.md#recovery) before using `make resume CONFIG=/path/benchmark.json RUN=/path/results/sweep`.

## Scope and evidence

One configuration describes one workload, endpoint and fixed topology. The harness does not deploy, scale or tune serving policies. No KServe, OpenShift or Prometheus database is required. Coordinated mixed workloads/endpoints, multi-turn, tools, Responses API, arrival-time replay and New Relic querying are outside V1.

Results retain native AIPerf files, config, commands, checks, summaries and timestamped provenance. Native files may contain prompts and operational data; keep them in your environment and select what to share. [Storage and timestamps](docs/operator-guide.md#evidence-and-storage).

Before handoff, follow the [qualification checklist](docs/operator-guide.md#handoff-check). Keep this README as the command entry point, the [operator guide](docs/operator-guide.md) for decisions/configuration/recovery, and the [metric reference](docs/metrics.md) for names, units and purpose.

## Test

```sh
make test
make test-integration AIPERF=/path/to/aiperf
```

Integration uses real AIPerf against a local simulated server, with no GPU or cluster. It checks payloads, authentication, pacing, repeats, metric collection and failure handling. It does not establish model performance or deployment compatibility. [Container and Job instructions](docs/operator-guide.md#execution-environment).

Apache-2.0. AIPerf is a separate dependency with its own license.
