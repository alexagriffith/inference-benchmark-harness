# Choose where the runner lives

The same Python CLI runs at either location. Select the endpoint reachable from that location and keep the location consistent across comparisons.

| Location | Needs | What to check |
|---|---|---|
| Workstation or approved utility host | Python, AIPerf and access to inference/metric endpoints | VPN, proxy, CA trust, API authentication, local CPU and storage |
| Workstation through port-forward | Above plus Kubernetes permission to port-forward | Keep each tunnel alive; local tunnel latency is part of client timing |
| In-cluster Job | Approved image, input/output volumes and network policy | Service DNS, service-mesh identity, CA trust, durable output and CPU capacity |

For a permitted port-forward, run it in a separate terminal with an explicit context:

```sh
kubectl --context YOUR_CONTEXT -n YOUR_NAMESPACE port-forward service/YOUR_GATEWAY 8000:80
```

Set `endpoint.url` to `http://127.0.0.1:8000`. Forward separate metrics endpoints as needed; a gateway's `/metrics` does not necessarily expose model or Endpoint Picker metrics. Stop only your own tunnels when finished. Port-forward is useful for plumbing checks; it can distort a capacity comparison.

## Optional Kubernetes checks

Add this block when the runner has read access through kubectl:

```json
{
  "kubernetes": {
    "context": "YOUR_CONTEXT",
    "deployments": [
      {"namespace": "inference", "name": "model-server", "replicas": 1},
      {"namespace": "inference", "name": "endpoint-picker", "replicas": 1}
    ]
  }
}
```

The runner reads Deployments and selected pods, checks rollout convergence and records image identities. It never scales them. Use your deployment owner to establish the experiment's replica count; preserve tensor parallelism, model, cache settings and other serving parameters. One replica may still use multiple GPUs.

These checks do not prove custom gateway filters, objective bindings or the effective scheduling policy. Capture those through your deployment tools before making policy claims. The endpoint-only path remains available when the runner cannot use the Kubernetes API.

## In-cluster package

Build `Containerfile` with your approved builder and publish the resulting image through your normal registry process. Adapt `examples/job.yaml` to your namespace, image and existing persistent volumes. Put the configuration and local dataset on the input volume; results go to the output volume. Use a unique run directory and Job name for each campaign.

The example has no Kubernetes API token and uses the endpoint-only path. Its image must be supplied by the operator. It is a deployment template, not proof of compatibility with a particular cluster. Check mesh injection and sidecar completion behavior for batch Jobs; do not disable mutual TLS to work around a failed test. If custom CAs or per-producer metric authentication are required, use your approved network/identity path and qualify it with `verify` and `smoke`.
