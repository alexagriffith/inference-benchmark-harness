# Metric reference

Use this as a discovery seed, then confirm the deployed version and scrape output. The engine names below were observed on vLLM 0.27.1; router names and labels were checked against llm-d-router v0.10.0. They are not a promise about another release. Save source names, ingested names, units and producer identity with the run.

## Client evidence

AIPerf 0.12.0 exports `profile_export_aiperf.json` (schema 1.4) and `profile_export.jsonl`. Read each exported `unit`; do not infer it from an old tool's column name.

| Export key | Meaning | Use |
|---|---|---|
| `time_to_first_token` | Client time to first token; milliseconds in the qualified path | Compare against a declared TTFT goal |
| `request_latency` | Client request duration; milliseconds | End-to-end experience for completed requests |
| `inter_token_latency` | Client timing between tokens, as defined by AIPerf | Streaming responsiveness; not automatically equivalent to another tool's per-request time-per-output-token average |
| `request_count`, `error_request_count` | Successful and failed request counts | Reconcile the aggregate with native records |
| Record `metadata.request_start_ns`, `request_end_ns` | Request timestamps, nanoseconds | Align client activity and server collection |

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

[Router definitions at v0.10.0](https://github.com/llm-d/llm-d-router/blob/v0.10.0/pkg/epp/metrics/llm_d_router_metrics.go) · [Collection and New Relic checklist](metrics.md)
