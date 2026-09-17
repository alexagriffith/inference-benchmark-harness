"""Optional deployment identity checks through an explicit Kubernetes context."""

import json
import subprocess


def inspect(config):
    scope = config["kubernetes"]
    base = ["kubectl", "--context", scope["context"], "--request-timeout=10s"]
    checks = []
    for target in scope["deployments"]:
        def get(kind, name=None, selector=None):
            args = base + ["-n", target["namespace"], "get", kind]
            if name:
                args.append(name)
            if selector:
                args += ["-l", selector]
            args += ["-o", "json"]
            result = subprocess.run(args, capture_output=True, text=True, timeout=15)
            if result.returncode:
                raise ValueError("Kubernetes read failed; check context, names and read permission")
            return json.loads(result.stdout)
        try:
            deployment = get("deployment", target["name"])
            spec, status = deployment["spec"], deployment.get("status", {})
            expected = target["replicas"]
            matched = spec["selector"]
            selectors = [f"{key}={value}" for key, value in matched.get("matchLabels", {}).items()]
            for expression in matched.get("matchExpressions", []):
                key, operator = expression["key"], expression["operator"]
                if operator in ("In", "NotIn"):
                    selectors.append(f"{key} {'in' if operator == 'In' else 'notin'} ({','.join(expression['values'])})")
                elif operator in ("Exists", "DoesNotExist"):
                    selectors.append(key if operator == "Exists" else "!" + key)
                else:
                    raise ValueError("Unrecognized selector operator")
            if not selectors:
                raise ValueError("Deployment has no pod selector")
            pods = get("pods", selector=",".join(selectors))["items"]
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
    return checks
