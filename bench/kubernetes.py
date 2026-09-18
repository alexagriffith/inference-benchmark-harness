"""Optional deployment identity checks through an explicit Kubernetes context."""

import json
import subprocess

from .provenance import observed, timestamp


@observed("kubernetes_acquisition", source=lambda context, namespace, kind, name=None, selector=None:
          {"namespace": namespace, "kind": kind, "name": name})
def read(context, namespace, kind, name=None, selector=None):
    args = ["kubectl", "--context", context, "--request-timeout=10s", "-n", namespace, "get", kind]
    if name:
        args.append(name)
    if selector:
        args += ["-l", selector]
    args += ["-o", "json"]
    result = subprocess.run(args, capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise ValueError(f"Cannot read {kind}; check context, resource name and read permission")
    return json.loads(result.stdout)


def selector_text(selector):
    parts = [f"{key}={value}" for key, value in selector.get("matchLabels", {}).items()]
    for expression in selector.get("matchExpressions", []):
        key, operator = expression["key"], expression["operator"]
        if operator in ("In", "NotIn"):
            parts.append(f"{key} {'in' if operator == 'In' else 'notin'} ({','.join(expression['values'])})")
        elif operator in ("Exists", "DoesNotExist"):
            parts.append(key if operator == "Exists" else "!" + key)
        else:
            raise ValueError("Unrecognized selector operator")
    if not parts:
        raise ValueError("Resource has no pod selector")
    return ",".join(parts)


@observed("deployment_inspection")
def inspect(config):
    scope = config["kubernetes"]
    checks = []
    for target in scope["deployments"]:
        started = timestamp()
        def get(kind, name=None, selector=None):
            return read(scope["context"], target["namespace"], kind, name, selector)
        try:
            deployment = get("deployment", target["name"])
            spec, status = deployment["spec"], deployment.get("status", {})
            expected = target["replicas"]
            pods = get("pods", selector=selector_text(spec["selector"]))["items"]
            pods = [pod for pod in pods if not pod["metadata"].get("deletionTimestamp")]
            ready = all(any(c.get("type") == "Ready" and c.get("status") == "True"
                            for c in pod.get("status", {}).get("conditions", [])) for pod in pods)
            converged = (spec.get("replicas", 1) == expected and len(pods) == expected and ready
                         and status.get("observedGeneration", 0) >= deployment["metadata"]["generation"]
                         and all(status.get(key, 0) == expected for key in ("replicas", "updatedReplicas", "availableReplicas", "readyReplicas")))
            checks.append({"name": target["name"], "status": "pass" if converged else "fail",
                           "expected_replicas": expected, "observed_pods": len(pods),
                           "detail": "Deployment and selected pods must finish converging before traffic",
                           "identity": [{"pod": pod["metadata"]["name"], "uid": pod["metadata"]["uid"],
                                         "containers": [{key: container.get(key) for key in ("name", "image", "imageID", "restartCount")}
                                                        for container in pod.get("status", {}).get("containerStatuses", [])]} for pod in pods]})
        except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as exc:
            checks.append({"name": target["name"], "status": "fail", "detail": str(exc)})
        checks[-1]["namespace"] = target["namespace"]
        checks[-1]["observation"] = {"started": started, "finished": timestamp()}
    if scope.get("routing"):
        from .routing import inspect_routing
        checks.extend(inspect_routing(config))
    return checks


def deployment_changes(before, after):
    """Compare sampled pod identities; continuous stability needs monitoring."""
    def identities(checks):
        return {(check.get("namespace"), check["name"]): sorted(check["identity"], key=lambda pod: pod["uid"])
                for check in checks if "identity" in check}
    changes = ["postflight_failed:" + check["name"] for check in after if check["status"] == "fail"]
    if identities(before) != identities(after):
        changes.append("deployment_identity_changed")
    return changes
