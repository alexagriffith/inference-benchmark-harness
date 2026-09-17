# Choose the next experiment

Use the [benchmark decision guide](https://alexagriffith.github.io/flow-control-benchmarks/benchmark-decision-map/) to move from a working endpoint to a specific flow-control question. The harness supplies measurements and checks; it does not select or tune a scheduling policy automatically.

| Current evidence | Next action | What it can establish |
|---|---|---|
| Endpoint, route or required collection check fails | Follow the failed check before sending more load | A working and identified test path |
| Smoke completes with reconciled records | Run a bounded baseline with representative input and an agreed latency/error target | Client behavior as offered load changes |
| Baseline meets the target | Extend the load range in a new planned campaign, or retain the current configuration | The useful range for this workload and topology |
| Baseline misses the target | Inspect same-window engine, queue and platform signals | Whether capacity, routing, load generation or another limit warrants investigation |
| A proposed flow-control change is ready | Compare against the same workload and topology, preserving the original baseline | The effect of the changed configuration within that comparison |
| Priority protection is the question | Add interactive-alone and equal-priority controls before the differentiated-priority comparison | Whether priority explains a benefit under overlapping contention |
| Fairness is the question | Establish simultaneous demand at the same priority, then compare dispatch and completion evidence | Fairness under the tested load and policy |

Keep model, tensor parallelism, token-length distribution, cache behavior, request mix and run location comparable. Change one experimental variable at a time where practical. Repeat and counterbalance comparisons when run-to-run variability could change the decision. Report sample count and uncertainty; a few successful requests do not establish a tail-latency target.

The [guide's metrics page](https://alexagriffith.github.io/flow-control-benchmarks/benchmark-decision-map/metrics.html) explains the questions behind the signals. Check names against the deployed versions and [collection guidance](metrics.md). Keep client latency, admission/queue behavior and engine work distinct. A queue rejection is not evidence of in-flight eviction.
