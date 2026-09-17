# Collect the signals needed for the question

Start with client evidence. Add required server signals when the experiment needs them. Empty or missing telemetry is unknown, not zero.

| Question | Signal | Why it matters |
|---|---|---|
| Did requests finish? | Native records, error outcomes, cancellation and process status | Reconcile attempts before interpreting speed |
| How long did users wait? | TTFT, request latency, inter-token timing and token counts | Describe the observed client experience with units and sample count |
| Is the engine under pressure? | Running/waiting requests, KV-cache use, preemptions and completions, per replica | Distinguish engine pressure from transport or scheduling delays |
| Did flow control act? | Endpoint Picker queue depth/time, saturation, dispatch and rejection outcomes, objective/flow labels | Establish admission behavior and the identity receiving service |
| Did the platform limit the test? | Ready replicas, restarts, CPU/GPU and network/storage pressure | Separate load-generator or platform limits from serving limits |

For vLLM, inspect actual names such as `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:kv_cache_usage_perc` and `vllm:request_success_total`. Names and labels depend on version. Endpoint Picker flow-control families use `llm_d_epp_*` in the reviewed router release; do not substitute a guessed generic name. Some counters only appear after the first relevant event.

Configure each approved direct endpoint separately, especially when a service load-balances multiple replicas:

```json
{
  "metrics": [
    {
      "name": "engine-1",
      "url": "http://engine-1:8000/metrics",
      "required": [
        {"metric": "vllm:num_requests_running", "why": "Observe engine occupancy during this capacity experiment"}
      ]
    }
  ]
}
```

Use an empty `required` list for optional collection. Unreachable optional telemetry is reported without blocking client measurements. A failed required check stops before load. Afterward the runner verifies the endpoint's native fetch timeline spans client requests. AIPerf JSONL omits unchanged values, so update timestamps alone are not scrape-health evidence. Window coverage does not prove an adequate sampling frequency or absence of internal gaps; inspect sampling and fetch counts for the duration and question.

## New Relic

A Prometheus-format endpoint is a data source; Prometheus and New Relic are collection/query choices. Direct AIPerf collection does not require a Prometheus database. Keep the existing New Relic agent if it already collects the necessary producers.

Check the exact target selection, ingested metric names, resource attributes, histogram representation and fresh samples for the run window. New Relic's Prometheus agent defaults to a 30-second scrape interval and supports filters/relabeling; a short smoke can fall between samples. Avoid duplicate collection jobs. These settings are documented in [New Relic's agent setup](https://docs.newrelic.com/docs/infrastructure/prometheus-integrations/install-configure-prometheus-agent/setup-prometheus-agent/).

If a signal is missing, report the producer, expected source metric, experiment question and whether direct collection or ingestion failed. No New Relic integration is installed or reconfigured by this package. Its behavior must be checked in the operator's environment.

## Platform boundaries

Red Hat AI Inference 3.5 documents vLLM, Endpoint Picker and platform monitoring in its [llm-d monitoring guide](https://docs.redhat.com/en/documentation/red_hat_ai_inference/3.5/html/monitor_and_troubleshoot_distributed_inference_with_llm-d_deployments/monitoring-llmd-deployments). vLLM and router signals come from those components; KServe lifecycle metrics are not required by this harness. Upstream and product deployments can differ in versions, enabled features, labels, monitoring discovery and transport. Observe the deployed components before treating two inventories as equivalent.

Never derive router latency by subtracting independently aggregated percentiles. A client latency improvement alone does not prove priority or fairness; those comparisons require matched workloads, controls and server attribution.
