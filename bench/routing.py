"""Verify declared gateway, pool, picker and objective bindings without traffic."""

import subprocess

from .kubernetes import read, selector_text
from .provenance import observed


def current_condition(resource, conditions, kind):
    generation = resource["metadata"]["generation"]
    return next((item.get("status") for item in conditions
                 if item.get("type") == kind and item.get("observedGeneration") == generation), None)


@observed("routing_inspection")
def inspect_routing(config):
    scope = config["kubernetes"]
    routing = scope["routing"]
    namespace = routing["namespace"]
    checks = []

    def get(kind, name=None, ns=namespace, selector=None):
        return read(scope["context"], ns, kind, name, selector)

    def add(name, passed, detail):
        checks.append({"name": name, "status": "pass" if passed else "fail", "detail": detail})

    def selected_ids(selector):
        pods = get("pods", selector=selector_text(selector))["items"]
        return sorted(pod["metadata"]["uid"] for pod in pods if not pod["metadata"].get("deletionTimestamp"))

    try:
        pool = get("inferencepools.inference.networking.k8s.io", routing["pool"])
        model = get("deployment", routing["model_deployment"])
        model_ids = selected_ids(model["spec"]["selector"])
        add("pool_model_binding", bool(model_ids) and model_ids == selected_ids(pool["spec"]["selector"]),
            "The pool must select exactly the declared model Deployment's active pods")
        if routing.get("picker_deployment"):
            reference = pool["spec"]["endpointPickerRef"]
            service = get("service", reference["name"])
            picker = get("deployment", routing["picker_deployment"])
            picker_ids = selected_ids(picker["spec"]["selector"])
            add("pool_picker_binding", reference.get("kind", "Service") == "Service"
                and reference.get("group", "") == "" and bool(picker_ids)
                and any(port["port"] == reference["port"]["number"] for port in service["spec"]["ports"])
                and picker_ids == selected_ids({"matchLabels": service["spec"]["selector"]}),
                {"service": reference["name"], "failure_mode": reference.get("failureMode"),
                 "meaning": "Pool picker Service selects the declared picker Deployment"})
    except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
        add("pool_read", False, str(exc))

    try:
        gateway_ref = routing["gateway"]
        gateway = get("gateways.gateway.networking.k8s.io", gateway_ref["name"], gateway_ref["namespace"])
        add("gateway_programmed", current_condition(gateway, gateway.get("status", {}).get("conditions", []), "Programmed") == "True",
            "Gateway must be programmed for its current generation")
        route = get("httproutes.gateway.networking.k8s.io", routing["route"])

        def expected_parent(reference):
            return (reference.get("name") == gateway_ref["name"]
                    and reference.get("namespace", namespace) == gateway_ref["namespace"]
                    and reference.get("kind", "Gateway") == "Gateway"
                    and reference.get("group", "gateway.networking.k8s.io") == "gateway.networking.k8s.io"
                    and (not gateway_ref.get("section") or reference.get("sectionName") == gateway_ref["section"]))

        parents = [parent for parent in route.get("status", {}).get("parents", []) if expected_parent(parent.get("parentRef", {}))]
        accepted = any(all(current_condition(route, parent.get("conditions", []), kind) == "True"
                           for kind in ("Accepted", "ResolvedRefs")) for parent in parents)
        add("route_parent", any(expected_parent(ref) for ref in route["spec"].get("parentRefs", [])) and accepted,
            "The selected Gateway parent must accept and resolve this route's current generation")
        rule = route["spec"]["rules"][routing.get("rule_index", 0)]
        backends = [backend for backend in rule.get("backendRefs", []) if backend.get("weight", 1) > 0]
        correct_pool = bool(backends) and all(backend.get("kind") == "InferencePool"
                                             and backend.get("group") == "inference.networking.k8s.io"
                                             and backend.get("name") == routing["pool"]
                                             and backend.get("namespace", namespace) == namespace for backend in backends)
        add("route_pool_binding", correct_pool,
            {"rule_index": routing.get("rule_index", 0), "matches": rule.get("matches", []),
             "meaning": "Selected rule's active backends all reference the expected pool; confirm the request matches this rule"})
    except (OSError, ValueError, KeyError, IndexError, TypeError, subprocess.TimeoutExpired) as exc:
        add("route_read", False, str(exc))

    for expected in routing.get("objectives", []):
        name = expected["name"]
        try:
            objective = get("inferenceobjectives.llm-d.ai", name)
            reference = objective["spec"]["poolRef"]
            binding = (reference.get("name") == routing["pool"] and reference.get("namespace", namespace) == namespace
                       and reference.get("kind", "InferencePool") == "InferencePool"
                       and reference.get("group", "inference.networking.k8s.io") == "inference.networking.k8s.io"
                       and objective["spec"].get("priority", 0) == expected["priority"])
            add("objective_binding:" + name, binding, {"pool": routing["pool"], "priority": expected["priority"]})
            accepted = current_condition(objective, objective.get("status", {}).get("conditions", []), "Accepted")
            checks.append({"name": "objective_status:" + name,
                           "status": "pass" if accepted == "True" else "fail" if accepted == "False" else "unverified",
                           "detail": "Controller status is distinct from the declared binding and actual request classification"})
        except (OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as exc:
            add("objective_read:" + name, False, str(exc))
    selected = routing.get("selected_objective")
    if selected:
        headers = {key.lower(): value for key, value in config["endpoint"].get("headers", {}).items()}
        add("objective_request_header", headers.get(routing.get("objective_header", "x-llm-d-inference-objective").lower()) == selected,
            "The configured request header must name the selected objective")
    checks.append({"name": "request_attribution", "status": "unverified",
                   "detail": "Use matching gateway/router evidence from smoke to confirm custom filters and actual objective selection; object bindings alone cannot prove it"})
    return checks
