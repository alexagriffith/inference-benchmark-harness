import copy
import unittest
from unittest.mock import patch

from bench.routing import inspect_routing


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.config = {"endpoint": {"headers": {"x-llm-d-inference-objective": "interactive"}}, "kubernetes": {
            "context": "fixture", "routing": {"namespace": "inference", "pool": "model-pool", "route": "model-route",
            "model_deployment": "model", "picker_deployment": "picker", "gateway": {"namespace": "gateway", "name": "entry"},
            "objectives": [{"name": "interactive", "priority": 10}], "selected_objective": "interactive"}}}
        parent = {"name": "entry", "namespace": "gateway"}
        conditions = [{"type": name, "status": "True", "observedGeneration": 1} for name in ("Accepted", "ResolvedRefs")]
        self.resources = {
            "inferencepools.inference.networking.k8s.io": {"spec": {"selector": {"matchLabels": {"app": "model"}},
                "endpointPickerRef": {"name": "picker-service", "port": {"number": 9002}}}},
            "gateways.gateway.networking.k8s.io": {"metadata": {"generation": 1}, "status": {"conditions": [
                {"type": "Programmed", "status": "True", "observedGeneration": 1}]}},
            "httproutes.gateway.networking.k8s.io": {"metadata": {"generation": 1}, "spec": {
                "parentRefs": [parent], "rules": [{"backendRefs": [{"name": "model-pool", "kind": "InferencePool",
                "group": "inference.networking.k8s.io"}]}]}, "status": {"parents": [{"parentRef": parent, "conditions": conditions}]}},
            "service": {"spec": {"selector": {"app": "picker"}, "ports": [{"port": 9002}]}},
            "inferenceobjectives.llm-d.ai": {"metadata": {"generation": 1}, "spec": {"poolRef": {"name": "model-pool"}, "priority": 10}}
        }

    def read(self, context, namespace, kind, name=None, selector=None):
        self.assertEqual(context, "fixture")
        if kind == "deployment":
            return {"spec": {"selector": {"matchLabels": {"app": name}}}}
        if kind == "pods":
            return {"items": [{"metadata": {"uid": selector, "name": selector}}]}
        return copy.deepcopy(self.resources[kind])

    def checks(self):
        with patch("bench.routing.read", side_effect=self.read):
            return {check["name"]: check for check in inspect_routing(self.config)}

    def test_valid_bindings_with_absent_controller_status(self):
        checks = self.checks()
        self.assertFalse(any(check["status"] == "fail" for check in checks.values()))
        self.assertEqual(checks["objective_binding:interactive"]["status"], "pass")
        self.assertEqual(checks["objective_status:interactive"]["status"], "unverified")
        self.assertEqual(checks["request_attribution"]["status"], "unverified")

    def test_pool_cannot_select_other_model(self):
        self.resources["inferencepools.inference.networking.k8s.io"]["spec"]["selector"]["matchLabels"]["app"] = "other"
        self.assertEqual(self.checks()["pool_model_binding"]["status"], "fail")

    def test_route_with_another_active_backend_fails(self):
        rule = self.resources["httproutes.gateway.networking.k8s.io"]["spec"]["rules"][0]
        rule["backendRefs"].append({"name": "other", "kind": "InferencePool", "group": "inference.networking.k8s.io"})
        self.assertEqual(self.checks()["route_pool_binding"]["status"], "fail")

    def test_old_route_acceptance_does_not_pass(self):
        self.resources["httproutes.gateway.networking.k8s.io"]["metadata"]["generation"] = 2
        self.assertEqual(self.checks()["route_parent"]["status"], "fail")

    def test_acceptance_by_another_gateway_does_not_pass(self):
        self.resources["httproutes.gateway.networking.k8s.io"]["status"]["parents"][0]["parentRef"] = {"name": "other", "namespace": "gateway"}
        self.assertEqual(self.checks()["route_parent"]["status"], "fail")

    def test_objective_wrong_pool_or_priority_fails(self):
        spec = self.resources["inferenceobjectives.llm-d.ai"]["spec"]
        spec["poolRef"]["name"] = "other-model"
        self.assertEqual(self.checks()["objective_binding:interactive"]["status"], "fail")
        spec["poolRef"]["name"] = "model-pool"
        spec["priority"] = 0
        self.assertEqual(self.checks()["objective_binding:interactive"]["status"], "fail")

    def test_current_controller_rejection_fails(self):
        self.resources["inferenceobjectives.llm-d.ai"]["status"] = {"conditions": [{"type": "Accepted", "status": "False", "observedGeneration": 1}]}
        self.assertEqual(self.checks()["objective_status:interactive"]["status"], "fail")

    def test_wrong_request_objective_header_fails(self):
        self.config["endpoint"]["headers"]["x-llm-d-inference-objective"] = "other"
        self.assertEqual(self.checks()["objective_request_header"]["status"], "fail")


if __name__ == "__main__":
    unittest.main()
