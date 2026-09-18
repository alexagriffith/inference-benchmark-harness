# Metric reference

Use this as a discovery seed, then confirm the deployed version and scrape output. The engine names below were observed on vLLM 0.27.1; router names and labels were checked against llm-d-router v0.10.0. They are not a promise about another release. Save source names, ingested names, units and producer identity with the run.

## Client evidence

AIPerf 0.12.0 exports `profile_export_aiperf.json` (schema 1.4) and `profile_export.jsonl`. Read each exported `unit`; do not infer it from an old tool's column name.

| Export key | Meaning | Use |
|---|---|---|
| `time_to_first_token` | Client time to first token; milliseconds in the qualified path | Compare against a declared TTFT goal |
| `request_latency` | Client request duration; milliseconds | End-to-end experience for completed requests |
| `inter_token_latency` | Client timing between tokens; milliseconds | Streaming responsiveness; not automatically equivalent to another tool's per-request time-per-output-token average |
| `request_throughput` | Completed requests per second | Compare achieved throughput with offered load |
| `request_count`, `error_request_count` | Successful and failed request counts; requests | Reconcile the aggregate with native records |
| Record `metadata.request_start_ns`, `request_end_ns` | Request timestamps, nanoseconds | Align client activity and server collection |


For experiment decisions, name the statistic as well as the metric:

| Decision | Exact measurement | Where to read it |
|---|---|---|
| How long before the answer starts? | `time_to_first_token.p95`, ms | Native aggregate; harness alias `ttft_p95_ms` |
| Does the stream pause? | `inter_token_latency.p95`, ms | Native aggregate if exported; no V1 goal or summary alias |
| How long until the answer finishes? | `request_latency.p95`, ms | Native aggregate; harness alias `latency_p95_ms` |
| How many requests complete per second? | `request_throughput.avg`, requests/s | Native aggregate; harness alias `request_throughput_rps` |
| How much traffic fails? | Failed records / all request records, fraction | Harness `error_fraction`; show numerator and denominator |

Use first-token and inter-token timing for interactive streaming; add full-request duration when completion time is the question. Keep output lengths comparable. Missing measurements are unknown, not zero. These statistics are per repeat; their variation is not a pooled percentile or confidence interval.

Report errors separately from successful-request latency. Keep native records and token counts so differences in request shape remain visible.

## Engine signals

The observed engine labels include `model_name` and `engine`. Attach the scraped pod or endpoint identity separately: two pods can both call their engine `0`.

| Source metric | Type / unit | What it can establish |
|---|---|---|
| `vllm:num_requests_running` | Gauge / requests | Engine occupancy |
| `vllm:num_requests_waiting` | Gauge / requests | Requests waiting inside the engine |
| `vllm:kv_cache_usage_perc` | Gauge / fraction; 1 means 100% | KV-cache pressure |
| `vllm:num_preemptions_total` | Counter / preemptions | Engine preemption activity; not router eviction proof |
| `vllm:request_success_total` | Counter / requests; also `finished_reason` | Completed requests by finish reason |
| `vllm:prompt_tokens_total`, `vllm:generation_tokens_total` | Counters / tokens | Input and output work |
| `vllm:prefix_cache_hits_total`, `vllm:prefix_cache_queries_total` | Counters / tokens | Token-based cache reuse; use matching-window deltas, not request-hit rate |
| `vllm:time_to_first_token_seconds` | Histogram / seconds | Engine-side first-token timing |
| `vllm:inter_token_latency_seconds` | Histogram / seconds | Engine inter-token timing |
| `vllm:request_time_per_output_token_seconds` | Histogram / seconds | Per-request time-per-output-token distribution |
| `vllm:e2e_request_latency_seconds` | Histogram / seconds | Engine request duration |
| `vllm:request_queue_time_seconds` | Histogram / seconds | Engine queue time |
| `vllm:request_prefill_time_seconds`, `vllm:request_decode_time_seconds` | Histograms / seconds | Prefill and decode timing |

Counter resets and rollout changes break a naive before/after subtraction. Keep per-producer series until identity and time windows are reconciled. An aggregate cache ratio requires a nonzero denominator and matching populations.

## Endpoint Picker signals

The model labels in these definitions are `model_name` and `target_model_name`. Do not assume an objective-name label exists: keep the declared objective-to-priority mapping and verify the actual request classification separately.

| Source metric | Type / unit | Declared labels | What it can establish |
|---|---|---|---|
| `llm_d_epp_flow_control_queue_size` | Gauge / requests | `fairness_id`, `priority`, `inference_pool`, model labels | Requests held by flow control; not engine in-flight work |
| `llm_d_epp_flow_control_queue_bytes` | Gauge / bytes | Same as queue size | Memory held in the flow-control queue |
| `llm_d_epp_flow_control_request_queue_duration_seconds` | Histogram / seconds | `fairness_id`, `priority`, `outcome`, `inference_pool`, model labels | Time from enqueue to final flow-control outcome |
| `llm_d_epp_flow_control_pool_saturation` | Gauge / detector signal | `inference_pool` | Dispatch gate signal; not GPU utilization |
| `llm_d_epp_flow_control_requests_total` | Counter / requests | `outcome`, `priority`, `inference_pool` | Flow-control outcomes; inspect actual outcome values |
| `llm_d_epp_request_total` | Counter / requests | Model labels, `fairness_id`, `priority` | Router requests by class |
| `llm_d_epp_request_ttft_seconds` | Histogram / seconds | Model labels, `fairness_id`, `priority`, `streaming` | Router-observed first-token timing |

A saturation value of 1 is the declared gating set point in this router version; an empty pool can also report 1. Interpret it with endpoint readiness and the effective detector configuration. Queueing alone does not prove eviction, priority protection or fair service.

Prometheus classic histograms expose `_bucket`, `_sum` and `_count` series; buckets include `le`. Keep those components and their dimensions for percentile queries. AIPerf's parsed server exports may normalize counter names by removing `_total`; the raw scrape name and the parsed key are not necessarily identical. New Relic can transform the representation again.

[Router definitions at v0.10.0](https://github.com/llm-d/llm-d-router/blob/v0.10.0/pkg/epp/metrics/llm_d_router_metrics.go)

## Collection and New Relic

AIPerf scrapes the configured Prometheus-format producer URLs directly. A Prometheus database is optional. `verify` prints discovered names and missing requirements; it checks names, not label attribution or semantic equivalence. Required metrics need valid exported samples and endpoint fetch coverage spanning the request window. The pinned exporter normalizes counter and histogram names; the validator uses their exported types. This does not prove uninterrupted per-metric availability or correct labels. An unchanged metric is not a failed scrape.

```json
"metrics": [{
  "name": "engine-1",
  "url": "http://engine-1:8000/metrics",
  "required": [{"metric": "vllm:num_requests_waiting", "why": "Identify engine queue pressure"}]
}]
```

Use a stable URL for each replica, not a Service that alternates between pods. Inference bearer authentication does not configure metric authentication. Qualify approved producer access from the actual runner location. Metrics without requirements are optional; missing optional GPU data does not invalidate client smoke. Missing class attribution prevents priority/fairness claims.

New Relic is a separate monitoring service. Existing agents can send it engine, router and GPU metrics; this package does not install agents, query New Relic or upload native files. Keep compact run state and native evidence on operator-controlled storage. New Relic can hold the infrastructure history alongside it, correlated by saved UTC windows and producer identities.

| Verify | Why |
|---|---|
| Source name, type, unit and labels | A rename can also change meaning; absent lazy counters are not zero |
| Target/pod and GPU identities | Avoid missing replicas or double-counting duplicate collectors |
| Ingested names and attributes | Filters, relabeling and histogram conversion can change queries |
| Before/during/after samples | Ingestion lag and scrape intervals can hide a short smoke |
| Matching run window and clock | Comparisons need the same population and interval |

Read-only NRQL discovery examples; replace names and add your environment filters:

```sql
FROM Metric SELECT uniques(metricName)
WHERE (metricName LIKE 'vllm%' OR metricName LIKE 'llm_d_epp%')
SINCE 30 minutes ago

FROM Metric SELECT keyset()
WHERE metricName = '<observed-ingested-metric-name>'
SINCE 30 minutes ago
```

For analysis, query the saved UTC run window. These are documented examples, not a tested account integration. New Relic's agent defaults to a 30-second scrape interval; confirm the installed configuration. See [agent setup](https://docs.newrelic.com/docs/infrastructure/prometheus-integrations/install-configure-prometheus-agent/setup-prometheus-agent/) and [metric discovery](https://docs.newrelic.com/docs/data-apis/understand-data/metric-data/query-metric-data-type/).

If a required signal is absent, record **producer/version → source name/unit → observed failure → blocked conclusion → owner/next check**. Name-only changes can be configured in `metrics[].required[].metric`; unit conversion and ingested-name mapping require external queries or a future adapter. Follow [debugging](operator-guide.md#debugging).

## GPU and platform boundaries

The harness explicitly uses `--no-gpu-telemetry`. Generic server scraping and AIPerf's dedicated GPU telemetry are separate paths. No dedicated GPU-summary export or dashboard is provided by V1.

For remote NVIDIA serving nodes, an existing DCGM exporter is the relevant source; local `pynvml` measures the benchmark host. Verify exporter/node/GPU UUID/pod attribution, all-node coverage and scrape timing before making GPU-efficiency claims. A load-balanced exporter service may omit nodes. Dedicated integration can be added later without deploying another exporter. See [AIPerf GPU telemetry](https://docs.nvidia.com/aiperf/tutorials/metrics-analysis/gpu-telemetry-with-ai-perf#path-2-other-inference-servers-custom-dcgm).

The NVIDIA device plugin allocates GPU resources; it does not collect telemetry. Device-sharing `replicas` differ from model Deployment replicas. Capture sharing/MIG configuration before interpreting advertised resources as physical GPUs. See [device-plugin configuration](https://github.com/NVIDIA/k8s-device-plugin).

Component versions and enabled features determine available metrics. vLLM/Endpoint Picker signals do not require KServe; validate the deployed inventory. Never subtract independently aggregated percentiles to infer router latency, or infer fairness/priority protection from client latency alone.
