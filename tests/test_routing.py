# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""The router resolves WHERE each URI runs and diagnoses the execution layers — BEFORE acting."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from urirun_connector_router import routing as R  # noqa: E402

MESH = {"nodes": [{"name": "lenovo", "url": "http://192.168.188.201:8765"},
                  {"name": "phone", "url": "http://192.168.188.50:8195"}]}


# ── parsing + effect ──────────────────────────────────────────────────────────

def test_parse_and_effect():
    p = R.parse_uri("kvm://lenovo/screen/query/capture")
    assert p["scheme"] == "kvm" and p["target"] == "lenovo" and p["valid"]
    assert R.effect_of("kvm://lenovo/screen/query/capture") == "query"
    assert R.effect_of("kvm://lenovo/window/command/close") == "command"


def test_fixed_shell_diagnostics_are_read_only_effects():
    for uri in (
        "shell://lenovo/command/date",
        "shell://lenovo/command/uname",
        "shell://lenovo/command/which",
    ):
        assert R.effect_of(uri) == "query"


def test_route_contract_effect_overrides_command_spelled_uri():
    route = {
        "uri": "shell://lenovo/command/date",
        "node": "lenovo",
        "safe": True,
        "meta": {"contract": {"effect": "query"}},
    }
    d = R.execution_layers(
        "shell://lenovo/command/date",
        {**MESH, "routes": [route]},
    )
    assert R.effect_of_route(route, "shell://lenovo/command/date") == "query"
    assert d["effect"] == "query"
    safety = next(l for l in d["layers"] if l["layer"] == "safety")
    assert safety["detail"] == "read-only (query)"


def test_live_node_command_kind_does_not_override_query_uri():
    route = {
        "uri": "env://lenovo/runtime/query/health",
        "kind": "command",
        "adapter": "argv-template",
        "safe": True,
        "node": "lenovo",
    }
    assert R.effect_of_route(route, route["uri"]) == "query"
    d = R.execution_layers(route["uri"], {**MESH, "routes": [route]})
    assert d["effect"] == "query"
    safety = next(l for l in d["layers"] if l["layer"] == "safety")
    assert safety["detail"] == "read-only (query)"


def test_malformed_uri_is_invalid():
    assert R.parse_uri("not-a-uri")["valid"] is False


# ── locality resolution (the "where") ─────────────────────────────────────────

def test_host_target_runs_local():
    rt = R.resolve_target("host", MESH)
    assert rt["kind"] == "host" and rt["node"] is None


def test_named_node_resolves_to_its_url():
    rt = R.resolve_target("lenovo", MESH)
    assert rt["kind"] == "node" and rt["url"] == "http://192.168.188.201:8765"


def test_unknown_target_is_flagged():
    assert R.resolve_target("ghost", MESH)["kind"] == "unknown"


def test_diagnose_targets_host_only_has_no_node_blocks():
    report = R.diagnose_targets(selected_nodes=[], selected_targets=["host"], mesh=MESH)
    assert report["ok"] is True
    assert report["nodes"] == []
    assert report["blockedNodes"] == []


def test_diagnose_targets_missing_node_is_no_node_url():
    report = R.diagnose_targets(
        selected_nodes=["ghostbox"],
        selected_targets=["node:ghostbox"],
        mesh={"nodes": []},
    )

    assert report["ok"] is False
    assert report["remediationClass"] == "no-node-url"
    node = report["nodes"][0]
    assert node["status"] == "missing-node-url"
    assert node["remediation"]["class"] == "no-node-url"
    assert node["remediation"]["errorType"] == "NodeMissing"
    assert "--node-url ghostbox=http://<ip>:8765" in node["remediation"]["humanAction"]
    assert node["layers"][1]["layer"] == "mesh-discovery"
    assert node["layers"][1]["ok"] is False


def test_diagnose_targets_unreachable_node_is_uri_process_unreachable():
    report = R.diagnose_targets(
        selected_nodes=["lenovo"],
        selected_targets=["node:lenovo"],
        mesh={"nodes": [{"name": "lenovo", "url": "http://lenovo:8765", "reachable": False}]},
    )

    assert report["ok"] is False
    assert report["remediationClass"] == "unreachable"
    node = report["nodes"][0]
    assert node["status"] == "uri-process-unreachable"
    assert node["remediation"]["class"] == "unreachable"
    assert node["remediation"]["errorType"] == "NodeOffline"
    assert "urirun node serve --name lenovo" in node["remediation"]["command"]
    assert node["layers"][-1]["layer"] == "uri-process"
    assert node["layers"][-1]["ok"] is False


# ── layered diagnosis (the point: WHERE + which layer blocks) ─────────────────

def test_remote_query_resolves_clean():
    d = R.execution_layers("kvm://lenovo/screen/query/capture", MESH)
    assert d["runsOn"] == "lenovo" and d["effect"] == "query" and d["ok"]
    # the diagnosis walks the layers cheapest-first; parse → target → … → safety are always present
    names = [l["layer"] for l in d["layers"]]
    assert names[0] == "parse" and "target" in names and names[-1] == "safety"
    assert all(l["ok"] for l in d["layers"])


def test_unknown_node_blocks_at_target_layer():
    d = R.execution_layers("mqtt://ghost/topic/command/publish", MESH)
    assert d["ok"] is False and d["blockedAt"] == "target" and d["runsOn"] is None


def test_command_is_marked_mutating():
    d = R.execution_layers("fs://host/file/command/write", MESH)
    assert d["effect"] == "command"
    safety = next(l for l in d["layers"] if l["layer"] == "safety")
    assert "MUTATING" in safety["detail"]


def test_fixed_shell_date_is_not_marked_mutating():
    d = R.execution_layers(
        "shell://lenovo/command/date",
        {**MESH, "routes": [{"uri": "shell://lenovo/command/date", "node": "lenovo", "safe": True}]},
    )
    assert d["effect"] == "query"
    safety = next(l for l in d["layers"] if l["layer"] == "safety")
    assert safety["detail"] == "read-only (query)"


def test_probe_blocks_known_node_when_uri_process_unreachable(monkeypatch):
    monkeypatch.setattr(
        R,
        "reachable",
        lambda url, timeout=4.0: {"reachable": False, "error": "ConnectionRefusedError: refused"},
    )
    mesh = {
        **MESH,
        "routes": [{"uri": "kvm://lenovo/screen/query/capture", "node": "lenovo", "safe": True}],
    }

    d = R.execution_layers("kvm://lenovo/screen/query/capture", mesh, probe=True)

    assert d["runsOn"] == "lenovo"
    assert d["ok"] is False
    assert d["blockedAt"] == "reachability"
    reach = next(l for l in d["layers"] if l["layer"] == "reachability")
    assert "ConnectionRefusedError" in reach["detail"]


# ── whole-plan diagnosis (NL plan → where each step lands, before execution) ──

def test_diagnose_plan_maps_every_step_and_flags_blocked():
    plan = [{"uri": "fs://host/file/query/read"},
            {"uri": "kvm://lenovo/screen/query/capture"},
            {"uri": "mqtt://ghost/topic/command/publish"}]
    rep = R.diagnose_plan(plan, MESH)
    assert rep["stepCount"] == 3
    assert rep["runsOnByStep"]["fs://host/file/query/read"] == "host"
    assert rep["runsOnByStep"]["kvm://lenovo/screen/query/capture"] == "lenovo"
    assert rep["ok"] is False  # the ghost step is unroutable
    assert rep["blockedSteps"] == [{"uri": "mqtt://ghost/topic/command/publish", "blockedAt": "target"}]


def test_fully_routable_plan_is_ok():
    plan = [{"uri": "fs://host/file/query/read"}, {"uri": "kvm://lenovo/window/command/close"}]
    assert R.diagnose_plan(plan, MESH)["ok"] is True


def test_accept_plan_accepts_routable_plan_with_matching_contract_effect():
    mesh = {
        **MESH,
        "routes": [{
            "uri": "kvm://host/screen/query/capture",
            "node": "host",
            "meta": {"contract": {"effect": "query"}},
        }],
    }

    verdict = R.accept_plan([{"uri": "kvm://host/screen/query/capture"}], mesh)

    assert verdict["accepted"] is True
    assert verdict["violations"] == []


def test_accept_plan_rejects_descriptor_contract_effect_mismatch():
    mesh = {
        **MESH,
        "routes": [{
            "uri": "kvm://host/screen/query/capture",
            "node": "host",
            "effect": "query",
            "meta": {"contract": {"effect": "command"}},
        }],
    }

    verdict = R.accept_plan([{"uri": "kvm://host/screen/query/capture"}], mesh)

    assert verdict["accepted"] is False
    assert verdict["violations"] == [{
        "kind": "effect-mismatch",
        "uri": "kvm://host/screen/query/capture",
        "declared": "command",
        "observed": "query",
    }]


def _screen_capture_mesh_with_inventory() -> dict:
    return {
        **MESH,
        "routes": [{
            "uri": "kvm://host/screen/query/capture",
            "node": "host",
            "meta": {
                "contract": {
                    "effect": "query",
                    "domains": {
                        "monitor": {
                            "type": "enum",
                            "domain": "env:monitors.id",
                            "optional": True,
                            "emptyValues": [0, ""],
                            "skipWhen": {"scope": ["all", "all-monitors", "desktop"]},
                        },
                    },
                },
            },
        }],
        "inventories": {
            "host": {
                "node": "host",
                "fingerprint": "env-test",
                "domains": {
                    "env:monitors.id": [
                        {"value": 1, "label": "HDMI-A-1"},
                        {"value": 2, "label": "DP-2"},
                        {"value": 3, "label": "DP-1"},
                    ],
                },
            },
        },
    }


def test_accept_plan_accepts_valid_env_enum_value_from_twin_inventory():
    verdict = R.accept_plan(
        [{"uri": "kvm://host/screen/query/capture", "payload": {"monitor": 3}}],
        _screen_capture_mesh_with_inventory(),
    )

    assert verdict["accepted"] is True
    assert verdict["violations"] == []


def test_accept_plan_rejects_invalid_env_enum_value_from_twin_inventory():
    verdict = R.accept_plan(
        [{"uri": "kvm://host/screen/query/capture", "payload": {"monitor": 99}}],
        _screen_capture_mesh_with_inventory(),
    )

    assert verdict["accepted"] is False
    assert verdict["violations"] == [{
        "kind": "env-domain-invalid",
        "uri": "kvm://host/screen/query/capture",
        "parameter": "monitor",
        "domain": "env:monitors.id",
        "value": 99,
        "allowed": [1, 2, 3],
        "node": "host",
    }]


def test_accept_plan_skips_env_enum_when_scope_all():
    verdict = R.accept_plan(
        [{"uri": "kvm://host/screen/query/capture", "payload": {"scope": "all", "monitor": -1}}],
        _screen_capture_mesh_with_inventory(),
    )

    assert verdict["accepted"] is True
    assert verdict["violations"] == []
