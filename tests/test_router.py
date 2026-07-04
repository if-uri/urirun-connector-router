# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""router:// — WHERE each URI runs, diagnosed BEFORE acting. The point: an NL plan's execution
location is KNOWN (and its failing layer NAMED) before any mutating action fires."""
from __future__ import annotations

from urirun_connector_router import routing as R
from urirun_connector_router.core import accept, diagnose, resolve, target_diagnose, targets

MESH = {"nodes": [
    {"name": "lenovo", "url": "http://192.168.188.201:8765"},
    {"name": "laptop", "url": "http://127.0.0.1:8766"},
]}


# ── pure routing core ────────────────────────────────────────────────────────
def test_parse_uri_splits_scheme_target_path():
    p = R.parse_uri("kvm://lenovo/screen/query/capture")
    assert p["scheme"] == "kvm" and p["target"] == "lenovo" and p["path"] == "screen/query/capture"
    assert p["valid"]
    assert not R.parse_uri("not-a-uri")["valid"]


def test_effect_of_query_vs_command():
    assert R.effect_of("kvm://host/screen/query/capture") == "query"
    assert R.effect_of("kvm://lenovo/cdp/page/command/navigate") == "command"


def test_effect_of_route_prefers_declared_contract_effect():
    route = {
        "uri": "demo://host/report/command/read",
        "meta": {"contract": {"effect": "query"}},
    }
    assert R.effect_of("demo://host/report/command/read") == "command"
    assert R.effect_of_route(route, "demo://host/report/command/read") == "query"


def test_resolve_target_host_node_unknown():
    assert R.resolve_target("host", MESH)["kind"] == "host"
    n = R.resolve_target("lenovo", MESH)
    assert n["kind"] == "node" and n["url"] == "http://192.168.188.201:8765"
    assert R.resolve_target("ghost", MESH)["kind"] == "unknown"


def test_execution_layers_known_node_query_is_ok():
    d = R.execution_layers("kvm://lenovo/screen/query/capture", MESH, probe=False)
    assert d["runsOn"] == "lenovo" and d["effect"] == "query"
    assert d["ok"] and d["blockedAt"] is None
    assert [l["layer"] for l in d["layers"]] == ["parse", "target", "route", "safety"]
    assert d["layers"][2]["skipped"] is True


def test_execution_layers_unknown_target_blocks_at_target():
    d = R.execution_layers("kvm://ghost/screen/query/capture", MESH)
    assert not d["ok"] and d["blockedAt"] == "target" and d["runsOn"] is None


def test_execution_layers_flags_mutation():
    d = R.execution_layers("kvm://lenovo/cdp/page/command/navigate", MESH)
    assert d["effect"] == "command"
    assert any(l["layer"] == "safety" and "MUTATING" in l["detail"] for l in d["layers"])


def test_route_node_overrides_logical_host_target():
    mesh = {
        **MESH,
        "routes": [{"uri": "kvm://host/screen/query/capture", "node": "lenovo"}],
    }
    d = R.execution_layers("kvm://host/screen/query/capture", mesh)
    assert d["uriTarget"] == "host"
    assert d["runsOn"] == "lenovo"
    assert d["routeUri"] == "kvm://host/screen/query/capture"
    assert any(l["layer"] == "target" and "via route.node" in l["detail"] for l in d["layers"])


def test_route_catalog_blocks_missing_capability():
    mesh = {**MESH, "routes": [{"uri": "fs://host/file/query/stat"}]}
    d = R.execution_layers("kvm://host/screen/query/capture", mesh)
    assert not d["ok"]
    assert d["blockedAt"] == "route"


def test_templated_route_matches_concrete_uri():
    route = {"uri": "kvm://host/monitor/{monitor}/query/screenshot", "node": "lenovo"}
    d = R.execution_layers("kvm://host/monitor/2/query/screenshot", {**MESH, "routes": [route]})
    assert d["ok"]
    assert d["runsOn"] == "lenovo"
    assert d["routeUri"] == route["uri"]


def test_safety_blocks_denied_uri():
    d = R.execution_layers("shell://host/command/exec", {"routes": [{"uri": "shell://host/command/exec"}]})
    assert not d["ok"]
    assert d["blockedAt"] == "safety"


# ── plan diagnosis (the headline: know WHERE before acting) ───────────────────
def test_diagnose_plan_maps_each_step_to_its_node():
    steps = [
        {"uri": "kvm://lenovo/cdp/session/command/ensure"},
        {"uri": "kvm://lenovo/cdp/page/command/navigate"},
        {"uri": "kvm://host/screen/query/capture"},
        {"uri": "llm://ghost/chat/command/complete"},   # unknown target → blocked
    ]
    rep = R.diagnose_plan(steps, MESH)
    assert rep["runsOnByStep"]["kvm://lenovo/cdp/page/command/navigate"] == "lenovo"
    assert rep["runsOnByStep"]["kvm://host/screen/query/capture"] == "host"
    assert not rep["ok"]
    assert rep["blockedSteps"] == [{"uri": "llm://ghost/chat/command/complete", "blockedAt": "target"}]


def test_diagnose_plan_uses_route_node_for_host_uri():
    mesh = {
        **MESH,
        "routes": [{"uri": "kvm://host/screen/query/capture", "node": "lenovo"}],
    }
    rep = R.diagnose_plan([{"uri": "kvm://host/screen/query/capture"}], mesh)
    assert rep["ok"]
    assert rep["runsOnByStep"]["kvm://host/screen/query/capture"] == "lenovo"


# ── router:// handlers ───────────────────────────────────────────────────────
def test_resolve_handler():
    r = resolve(uri="kvm://lenovo/screen/query/capture", mesh=MESH)
    assert r["ok"] and r["runsOn"] == "lenovo" and r["action"] == "resolve"


def test_diagnose_handler():
    r = diagnose(steps=[{"uri": "kvm://host/x/query/y"}], mesh=MESH)
    assert r["ok"] and r["stepCount"] == 1


def test_target_diagnose_handler_flags_missing_node():
    r = target_diagnose(
        selectedNodes=["ghostbox"],
        selectedTargets=["node:ghostbox"],
        mesh={"nodes": []},
    )
    assert r["ok"] is False
    assert r["action"] == "target-diagnose"
    assert r["remediationClass"] == "no-node-url"


def test_accept_handler_rejects_invalid_plan():
    r = accept(steps=[{"uri": "kvm://ghost/x/query/y"}], mesh=MESH)
    assert r["ok"] is False
    assert r["accepted"] is False
    assert r["violations"][0]["kind"] == "routing-blocked"


def test_targets_handler_lists_host_plus_nodes():
    r = targets(mesh=MESH)
    assert r["targets"] == ["host", "laptop", "lenovo"]
