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

To verify llm-d object bindings, add `routing` inside `kubernetes`:

```json
{
  "routing": {
    "namespace": "inference",
    "model_deployment": "model-server",
    "picker_deployment": "endpoint-picker",
    "pool": "model-pool",
    "route": "model-route",
    "rule_index": 0,
    "gateway": {"namespace": "gateway-system", "name": "inference-gateway"},
    "objectives": [{"name": "interactive", "priority": 10}],
    "selected_objective": "interactive"
  }
}
```

For this example, also set `endpoint.headers` to `{"x-llm-d-inference-objective":"interactive"}`. The runner verifies pool/model and picker-Service ownership, current Gateway/HTTPRoute acceptance, the selected rule's pool references, objective pool/priority bindings and the configured header. `rule_index` is zero-based. Confirm the actual request matches that rule's path, host and header conditions; the report includes its matches. All declared model/picker Deployments must also appear in the readiness list.

An objective's missing or stale controller status is `unverified`, not a failed declared binding. A current explicit rejection fails the check. When a custom application maps a client field to an objective, omit `selected_objective` unless the benchmark directly sets the objective header; capture the actual classification separately.

These checks do not prove custom filters, effective scheduling policy or actual request classification. Use matching gateway/router evidence from smoke for those claims. The endpoint-only path remains available when the runner cannot use the Kubernetes API. Kubernetes read permissions are needed for the selected namespaces' Deployments, pods, Services, Gateways, HTTPRoutes, InferencePools and InferenceObjectives; no write permission is used.

Before comparing policies, the serving owner should record the actual picker image ID, startup arguments, mounted scheduling configuration and the version-specific loaded configuration reported by the process, when available. Compare the running pod with the deployment owner's intended configuration. Editing a ConfigMap or higher-level serving resource alone does not prove the process loaded it. If effective controls cannot be established, retain that uncertainty and do not attribute a latency change to a particular policy.

## In-cluster package

Build `Containerfile` with your approved builder and publish the resulting image through your normal registry process. Adapt `examples/job.yaml` to your namespace, image and existing persistent volumes. Put the configuration and local dataset on the input volume; results go to the output volume. Use a unique run directory and Job name for each campaign.

The example has no Kubernetes API token and uses the endpoint-only path. Its image must be supplied by the operator. It is a deployment template, not proof of compatibility with a particular cluster. Check mesh injection and sidecar completion behavior for batch Jobs; do not disable mutual TLS to work around a failed test. If custom CAs or per-producer metric authentication are required, use your approved network/identity path and qualify it with `verify` and `smoke`.


For a local image check, build and run the fixture suite with an existing writable artifact directory. These commands contact only a loopback test server inside the container:

```sh
podman build -t localhost/inference-benchmark-harness:0.1.0 .
podman run --rm --read-only --tmpfs /tmp:rw,size=512m \
  -v "$PWD/tests:/opt/harness/tests:ro" \
  -v "$PWD/examples:/opt/harness/examples:ro" \
  -v /path/to/test-artifacts:/results:rw -e TMPDIR=/results \
  --entrypoint python localhost/inference-benchmark-harness:0.1.0 \
  tests/integration.py --aiperf /opt/venv/bin/aiperf
```

The artifact mount must be writable by the container user (10001); configure ownership through your container runtime. Outputs remain in the mounted directory after the container exits. The multi-stage build includes a compiler for dependencies that lack a wheel on the selected architecture; the runtime image contains the installed Python environment without the compiler. A local container pass does not establish Kubernetes network or volume access.
