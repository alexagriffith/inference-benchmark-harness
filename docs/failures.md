# Failure handling

| Condition | Automatic behavior | Operator action |
|---|---|---|
| Temporary connection failure or HTTP 502/503/504 during a read-only check | At most three reads, with 1-second and 2-second delays | Fix the path if the check remains unavailable |
| Wrong model, rejected authentication, unready deployment or missing required metric | Stop before inference | Correct the named precondition, then resume |
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
