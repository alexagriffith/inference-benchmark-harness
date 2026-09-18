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

## Operator checklist

Use the [metric reference](metric-reference.md) to choose the minimum evidence for the experiment. Complete this once for each producer and repeat after a version, replica or collector change.

1. **Identify the source.** Record component version, pod or endpoint identity, approved metrics URL and access method. Reach it from the actual benchmark location. A laptop port-forward working does not prove a Job can reach it.
2. **Inspect the raw metric.** Confirm the source name, type, unit and labels. A lazy counter absent before its first event is unknown, not a pre-existing zero. Require it only when the planned claim needs it.
3. **Find it in New Relic.** Discover metric names and attributes instead of assuming the scrape name and pod labels survived ingestion. Check filters, relabeling and histogram conversion with the monitoring owner.
4. **Check the time window.** Record UTC start/end, scrape interval, retention resolution and relevant gaps. Compare fresh samples from before, during and after the run. Choose an interval that can resolve the behavior being studied; a short smoke is not a time-series qualification.
5. **Preserve attribution.** Keep per-replica identity and the priority/flow dimensions needed for the comparison. A service that alternates between engine pods is not a reliable per-pod counter source. Avoid counting duplicate collectors twice.
6. **Record the limit.** If collection is incomplete, name the missing signal and the conclusion it prevents. Client smoke results can still be useful without GPU telemetry; a fairness claim needs demand and service attributed to the relevant flows.

These read-only New Relic Query Language (NRQL) discovery examples follow the documented [metric discovery interface](https://docs.newrelic.com/docs/data-apis/understand-data/metric-data/query-metric-data-type/). Replace the placeholders and add the environment filter appropriate to your account:

```sql
FROM Metric SELECT uniques(metricName)
WHERE (metricName LIKE 'vllm%' OR metricName LIKE 'llm_d_epp%')
SINCE 30 minutes ago
```

```sql
FROM Metric SELECT keyset()
WHERE metricName = '<observed-ingested-metric-name>'
SINCE 30 minutes ago
```

For the actual experiment, set the query time range to the saved UTC run window. A discovery result proves that data exists in the selected range, not that every replica or the full experiment was collected. Query the observed attributes; [integration-specific discovery](https://docs.newrelic.com/docs/infrastructure/prometheus-integrations/view-query-data/view-query-your-prometheus-data/) shows examples, but attribute names vary with the ingestion path. These queries are documentation-checked examples, not a verified account integration.

When requesting a missing signal, use this short record:

```text
Question: Is waiting occurring inside the engine?
Producer and version: <engine image / version>
Source metric: vllm:num_requests_waiting (requests)
Identity needed: each serving pod and engine
Observed: <absent at source / present at source but absent in New Relic / stale>
Consequence: engine queue pressure cannot be attributed during this run
Next check and owner: <engine owner or monitoring owner, based on observed layer>
```
