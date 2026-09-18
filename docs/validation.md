# Validation status

Version 0.1.0 is a first operator package. It is not a capacity result or a certification of a deployment.

| Check | Reproduce | Scope |
|---|---|---|
| Contract tests | `make test` | Local validation, sequential points, retained goal failures, checkpoint integrity, metric coverage and route/objective binding failures |
| Actual AIPerf integration | `make test-integration AIPERF=/path/to/aiperf` | AIPerf 0.12.0 against a loopback streaming fixture; generated/file prompts, bearer auth, direct metrics, server failure, native sweep and constant/Poisson rate commands |
| Operator readiness | `make verify CONFIG=/path/to/config.json` | Read configured resources and endpoints without inference |
| Operator smoke | `make smoke CONFIG=/path/to/config.json RUN=/path/to/new-run` | One short request against the selected environment |

Integration tests retain exact commands and outputs in the temporary directory printed on completion. Failed runs remain available for diagnosis. The fixture does not simulate GPU scheduling, production TLS, service-mesh filters, real tokenization or New Relic ingestion.

During qualification, a short run stalled after all requests completed but before record processing finished. The outer deadline stopped it without accepting incomplete evidence. Explicitly configuring one record processor was followed by a passing test; this is not proof that every upstream startup race is eliminated. `record_processors` can be configured for larger workloads after load-generator qualification.

Native AIPerf comma-separated concurrency sweeps were executed successfully as a separate command test. The harness currently uses one native `profile` per point to place preflight, evidence checks and checkpoints between points. It does not implement request scheduling itself.

The final container passed 27 contract tests and the 33-request integration suite on Linux arm64, Python 3.12, as user 10001 with a read-only root filesystem. The suite includes constant and Poisson rate commands, a concurrency cap and a broad constant-pacing check. This small test qualifies command behavior, not a statistical arrival-distribution model. A Kubernetes Job and operator-specific image architecture, networking, identity and storage remain unverified. Multi-turn replay, automatic serving-policy changes and priority/fairness conclusions are outside this version's validated path.

A process-lifecycle regression also verifies that an owned helper cannot keep serving after its parent exits, even when the helper ignores graceful termination. Final cleanup kills remaining members of the owned process group. This does not prove remote serving cancellation.
