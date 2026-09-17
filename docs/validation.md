# Validation status

Version 0.1.0 is a first operator package. It is not a capacity result or a certification of a deployment.

| Check | Reproduce | Scope |
|---|---|---|
| Contract tests | `make test` | Local validation, sequential points, retained goal failures, checkpoint integrity, metric coverage and route/objective binding failures |
| Actual AIPerf integration | `make test-integration AIPERF=/path/to/aiperf` | AIPerf 0.12.0 against a loopback streaming fixture; generated/file prompts, bearer auth, direct metrics, server failure and native sweep |
| Operator readiness | `make verify CONFIG=/path/to/config.json` | Read configured resources and endpoints without inference |
| Operator smoke | `make smoke CONFIG=/path/to/config.json RUN=/path/to/new-run` | One short request against the selected environment |

Integration tests retain exact commands and outputs in the temporary directory printed on completion. Failed runs remain available for diagnosis. The fixture does not simulate GPU scheduling, production TLS, service-mesh filters, real tokenization or New Relic ingestion.

During qualification, a short run stalled after all requests completed but before record processing finished. The outer deadline stopped it without accepting incomplete evidence. Explicitly configuring one record processor was followed by a passing test; this is not proof that every upstream startup race is eliminated. `record_processors` can be configured for larger workloads after load-generator qualification.

Native AIPerf comma-separated concurrency sweeps were executed successfully as a separate command test. The harness currently uses one native `profile` per point to place preflight, evidence checks and checkpoints between points. It does not implement request scheduling itself.

The container recipe and Kubernetes Job template require build and runtime qualification in the operator's approved environment. Multi-turn replay, rate sweeps, automatic serving-policy changes and priority/fairness conclusions are outside this version's validated path.
