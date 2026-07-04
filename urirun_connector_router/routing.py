# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""URI-schema routing kernel.

This package answers the question the NL planner must know before any action is
dispatched: where will this URI run, and which execution layer blocks it?

The module is deliberately small and mostly dependency-free. Pure URI parsing,
target resolution, safety classification and layer diagnosis work without
``urirun`` installed. Registry flattening/compilation lazily imports the runtime
only when callers ask for those compatibility helpers.
"""
from __future__ import annotations

import json
import re
import urllib.request
from typing import Any


# Arbitrary-command verbs are never auto-classified safe: a route that runs whatever
# string it is given must not be offered to planners or merged into a remote registry
# as safe. Deny wins over any declared safe flag.
UNSAFE_URI_PARTS = (
    "/terminal/command/run",
    "/command/exec",
    "://sudo",
    "/command/install",
    "/command/upgrade",
)

_CONNECTOR_REQUIRED_ADAPTERS = frozenset({
    "configured-camera",
    "configured-media",
    "configured-ssh",
    "configured-files",
})
_EXTERNAL_ADAPTERS = frozenset({
    "configured-api",
    "fetch",
    "argv-template",
    "shell-template",
})
_READONLY_VERBS = ("/query/", "/info/", "/status/")
_READONLY_SHELL_COMMAND_PATHS = frozenset({
    "command/date",
    "command/echo",
    "command/uname",
    "command/which",
})


def _runtime_libs():
    """Return the urirun registry/runtime modules, or raise a focused error.

    ``urirun-connector-router`` can be used as a pure parser/diagnoser without
    the full runtime. Only registry materialisation needs these imports.
    """
    try:
        from urirun.runtime import _registry as reglib, v2
        return reglib, v2
    except Exception:
        try:
            import urirun_runtime._registry as reglib  # type: ignore
            import urirun_runtime.v2 as v2  # type: ignore
            return reglib, v2
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "registry routing helpers require urirun or urirun-runtime"
            ) from exc


def uri_is_denied(uri: str) -> bool:
    """True when a URI carries an arbitrary-exec/admin verb."""
    text = str(uri or "")
    return any(part in text for part in UNSAFE_URI_PARTS)


def route_is_safe(uri: str, declared: bool | None = None) -> bool:
    """Single source of truth for route safety.

    Safe iff the URI is non-empty, the binding author did not declare it unsafe,
    and the denylist does not flag it. Deny wins over every allow signal.
    """
    uri = str(uri or "")
    return bool(uri and declared is not False and not uri_is_denied(uri))


def route_class(route: dict) -> str:
    """Classify a route descriptor for UI/discovery display."""
    adapter = str(route.get("adapter") or "")
    if adapter in _CONNECTOR_REQUIRED_ADAPTERS:
        return "connector_required"
    if adapter in _EXTERNAL_ADAPTERS:
        return "external"
    if effect_of_route(route) == "query":
        return "metadata"
    uri = str(route.get("uri") or "")
    if any(v in uri for v in _READONLY_VERBS):
        return "metadata"
    return "executable"


def safe_route(route: dict) -> bool:
    """Route-dict wrapper around :func:`route_is_safe`."""
    return route_is_safe(str(route.get("uri", "")), route.get("safe"))


def parse_uri(uri: str) -> dict[str, Any]:
    """``scheme://target/noun/verb/action`` -> URI parts."""
    raw = str(uri or "")
    scheme, sep, rest = raw.partition("://")
    if not sep:
        return {
            "uri": raw,
            "scheme": "",
            "target": "",
            "path": raw,
            "segments": [],
            "valid": False,
        }
    segs = [s for s in rest.split("/") if s]
    target = segs[0] if segs else ""
    return {
        "uri": raw,
        "scheme": scheme,
        "target": target,
        "path": "/".join(segs[1:]),
        "segments": segs[1:],
        "valid": bool(scheme and target),
    }


def route_target(uri: str) -> str:
    """The URI authority/target, independent of where a mesh routes it."""
    return str(parse_uri(uri).get("target") or "")


def effect_of(uri: str) -> str:
    """Read vs mutation by URI verb."""
    text = str(uri or "")
    parsed = parse_uri(text)
    if parsed.get("scheme") == "shell" and parsed.get("path") in _READONLY_SHELL_COMMAND_PATHS:
        return "query"
    return "query" if any(v in text for v in _READONLY_VERBS) else "command"


def _route_contract(route: dict | None) -> dict:
    if not isinstance(route, dict):
        return {}
    direct = route.get("contract")
    if isinstance(direct, dict):
        return direct
    meta = route.get("meta")
    if isinstance(meta, dict) and isinstance(meta.get("contract"), dict):
        return meta["contract"]
    return {}


def effect_of_route(route: dict | None, uri: str = "") -> str:
    """Read vs mutation, preferring the route contract over URI spelling.

    URI verbs are a useful compatibility fallback, but the contract is the
    authoritative source once a route descriptor is available.
    """
    if isinstance(route, dict):
        direct = str(route.get("effect") or "").strip()
        if direct:
            return direct
        declared = str(_route_contract(route).get("effect") or "").strip()
        if declared:
            return declared
        # Some live node route descriptors carry kind="command" as a binding/
        # adapter class even for query-shaped diagnostics. Treat kind="query" as
        # a positive read-only signal, but never let kind="command" override the
        # URI/contract fallback.
        if str(route.get("kind") or "").strip() == "query":
            return "query"
    return effect_of(uri or str((route or {}).get("uri") or ""))


def _node_url_map(mesh: Any) -> dict[str, str]:
    """Normalize mesh nodes to ``{name: url}``."""
    if isinstance(mesh, dict) and "nodes" in mesh:
        mesh = mesh["nodes"]
    out: dict[str, str] = {}
    if isinstance(mesh, dict):
        for key, value in mesh.items():
            if isinstance(value, str):
                out[str(key)] = value
            elif isinstance(value, dict) and value.get("url"):
                out[str(value.get("name", key))] = str(value["url"])
    elif isinstance(mesh, list):
        for item in mesh:
            if isinstance(item, dict) and item.get("name") and item.get("url"):
                out[str(item["name"])] = str(item["url"])
    return out


def mesh_routes(mesh: Any) -> list[dict]:
    if isinstance(mesh, dict) and isinstance(mesh.get("routes"), list):
        return [r for r in mesh["routes"] if isinstance(r, dict)]
    if isinstance(mesh, list):
        return [r for r in mesh if isinstance(r, dict) and r.get("uri")]
    return []


def resolve_target(target: str, mesh: Any) -> dict[str, Any]:
    """A URI target -> host, named node, or unknown."""
    target = str(target or "").strip()
    nodes = _node_url_map(mesh)
    if target in ("", "host", "local"):
        return {"target": target or "host", "kind": "host", "node": None, "url": None}
    if target in nodes:
        return {"target": target, "kind": "node", "node": target, "url": nodes[target]}
    return {"target": target, "kind": "unknown", "node": None, "url": None}


def _template_part_matches(template: str, actual: str) -> bool:
    return (
        template == actual
        or (template.startswith("{") and template.endswith("}"))
        or (template.startswith(":") and len(template) > 1)
    )


def uri_matches_template(template: str, uri: str) -> bool:
    """Match exact routes and ``{param}``/``:param`` URI templates."""
    t = parse_uri(template)
    u = parse_uri(uri)
    if not t["valid"] or not u["valid"]:
        return False
    if not _template_part_matches(str(t["scheme"]), str(u["scheme"])):
        return False
    if not _template_part_matches(str(t["target"]), str(u["target"])):
        return False
    t_segments = list(t.get("segments") or [])
    u_segments = list(u.get("segments") or [])
    if len(t_segments) != len(u_segments):
        return False
    return all(_template_part_matches(a, b) for a, b in zip(t_segments, u_segments))


def route_for_uri(uri: str, routes: list[dict] | None) -> dict | None:
    """Return the best route descriptor for a concrete URI.

    Exact matches win over templated matches. This mirrors runtime routing enough
    for preflight diagnostics without importing the registry engine.
    """
    routes = routes or []
    for route in routes:
        if str(route.get("uri") or "") == uri:
            return route
    for route in routes:
        template = str(route.get("uri") or "")
        if template and uri_matches_template(template, uri):
            return route
    return None


def _route_node(route: dict | None) -> str:
    if not route:
        return ""
    for key in ("node", "service", "executor", "runsOn"):
        value = str(route.get(key) or "").strip()
        if value:
            return value
    meta = route.get("meta")
    if isinstance(meta, dict):
        value = str(meta.get("node") or "").strip()
        if value:
            return value
    return ""


def _target_for_route(uri: str, route: dict | None, mesh: Any) -> dict[str, Any]:
    logical = resolve_target(route_target(uri), mesh)
    routed_node = _route_node(route)
    if routed_node:
        nodes = _node_url_map(mesh)
        return {
            "target": route_target(uri),
            "kind": "node" if routed_node not in ("host", "local") else "host",
            "node": None if routed_node in ("host", "local") else routed_node,
            "url": nodes.get(routed_node),
            "logicalKind": logical["kind"],
            "routedBy": "route.node",
        }
    logical["logicalKind"] = logical["kind"]
    logical["routedBy"] = "uri-target"
    return logical


def reachable(url: str, timeout: float = 4.0) -> dict[str, Any]:
    """Probe a node's ``/health`` endpoint."""
    try:
        with urllib.request.urlopen(url.rstrip("/") + "/health", timeout=timeout) as response:
            data = json.loads(response.read() or b"{}")
        return {"reachable": True, "name": data.get("name"), "routeCount": data.get("routeCount")}
    except Exception as exc:  # noqa: BLE001
        return {"reachable": False, "error": f"{type(exc).__name__}: {exc}"[:160]}


def _node_records(mesh: Any) -> dict[str, dict]:
    """Normalize mesh/discovery node rows to ``{name: row}``.

    Unlike ``_node_url_map`` this keeps rows without a URL so target diagnosis
    can distinguish "node missing" from "node known but missing URL".
    """
    rows = mesh.get("nodes") if isinstance(mesh, dict) else mesh
    out: dict[str, dict] = {}
    if isinstance(rows, dict):
        for key, value in rows.items():
            if isinstance(value, dict):
                name = str(value.get("name") or value.get("node") or key)
                out[name] = {**value, "name": name}
            elif isinstance(value, str):
                out[str(key)] = {"name": str(key), "url": value}
    elif isinstance(rows, list):
        for item in rows:
            if isinstance(item, dict):
                name = str(item.get("name") or item.get("node") or "").strip()
                if name:
                    out[name] = item
    return out


def _target_nodes_from_selection(selected_nodes: list[str] | None,
                                 selected_targets: list[str] | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for node in selected_nodes or []:
        clean = str(node or "").strip()
        if clean and clean != "host" and clean not in seen:
            out.append(clean)
            seen.add(clean)
    for target in selected_targets or []:
        clean = str(target or "").strip()
        if not clean.startswith("node:"):
            continue
        node = clean.split(":", 1)[1].strip()
        if node and node not in seen:
            out.append(node)
            seen.add(node)
    return out


def _target_remediation(node: str, status: str, url: str = "") -> dict[str, Any] | None:
    """Typed remediation data for target diagnosis.

    The router owns the classification and remediation facts. UI-specific
    surfaces such as chat cards may wrap these fields, but should not recreate
    the decision tree.
    """
    if status == "missing-node-url":
        return {
            "class": "no-node-url",
            "status": status,
            "node": node,
            "errorType": "NodeMissing",
            "message": (
                f"Node '{node}' is missing from mesh discovery or has no URL. "
                f"Start the node and add --node-url {node}=http://<ip>:8765."
            ),
            "humanAction": (
                f"Start urirun on node '{node}' and add its URL:\n"
                f"  urirun node serve --name {node}\n"
                f"  --node-url {node}=http://<ip>:8765"
            ),
            "command": f"urirun node serve --name {node}",
            "dashboardUrl": f"?node={node}&fix=no-node-url",
        }
    if status == "uri-process-unreachable":
        return {
            "class": "unreachable",
            "status": status,
            "node": node,
            "url": url,
            "errorType": "NodeOffline",
            "message": f"Node '{node}' URL is known, but the URI process is unreachable.",
            "humanAction": (
                f"Start or restart the URI process on node '{node}':\n"
                f"  urirun node serve --name {node}"
            ),
            "command": f"urirun node serve --name {node}",
            "dashboardUrl": f"?node={node}&fix=unreachable",
        }
    return None


def _diagnose_target_node(node: str, row: dict | None, *, probe: bool = False) -> dict[str, Any]:
    layers: list[dict[str, Any]] = [
        {"layer": "target-selection", "ok": True, "detail": f"selected node:{node}"},
    ]
    if not row:
        layers.append({
            "layer": "mesh-discovery",
            "ok": False,
            "detail": "missing from mesh discovery",
        })
        layers.append({"layer": "node-url", "ok": False, "detail": "no node URL"})
        remediation = _target_remediation(node, "missing-node-url")
        return {
            "node": node,
            "ok": False,
            "status": "missing-node-url",
            "url": "",
            "remediationClass": "no-node-url",
            "remediation": remediation,
            "layers": layers,
        }

    url = str(row.get("url") or row.get("nodeUrl") or "").strip()
    layers.append({"layer": "mesh-discovery", "ok": True, "detail": "node present in mesh discovery"})
    if not url:
        layers.append({"layer": "node-url", "ok": False, "detail": "no node URL"})
        remediation = _target_remediation(node, "missing-node-url")
        return {
            "node": node,
            "ok": False,
            "status": "missing-node-url",
            "url": "",
            "remediationClass": "no-node-url",
            "remediation": remediation,
            "layers": layers,
        }

    layers.append({"layer": "node-url", "ok": True, "detail": url})
    reachability = None
    if probe:
        reachability = reachable(url)
        is_reachable = bool(reachability.get("reachable"))
    elif "reachable" in row:
        is_reachable = bool(row.get("reachable"))
    else:
        is_reachable = True
    layers.append({
        "layer": "uri-process",
        "ok": is_reachable,
        "detail": (
            "reachable"
            if is_reachable else str((reachability or {}).get("error") or row.get("error") or "unreachable")
        ),
        **({"probe": reachability} if reachability is not None else {}),
    })
    if not is_reachable:
        remediation = _target_remediation(node, "uri-process-unreachable", url)
        return {
            "node": node,
            "ok": False,
            "status": "uri-process-unreachable",
            "url": url,
            "remediationClass": "unreachable",
            "remediation": remediation,
            "layers": layers,
        }
    return {
        "node": node,
        "ok": True,
        "status": "ok",
        "url": url,
        "remediationClass": None,
        "remediation": None,
        "layers": layers,
    }


def diagnose_targets(selected_nodes: list[str] | None = None,
                     selected_targets: list[str] | None = None,
                     mesh: Any = None,
                     probe: bool = False) -> dict[str, Any]:
    """Diagnose selected execution targets before planning/dispatch.

    This is the target-level sibling of ``diagnose_plan``. It answers the
    operator question before any URI step exists: does each explicitly selected
    node exist, have a URL, and expose a reachable URI process?
    """
    selected_nodes = [str(n) for n in (selected_nodes or []) if str(n)]
    selected_targets = [str(t) for t in (selected_targets or []) if str(t)]
    target_nodes = _target_nodes_from_selection(selected_nodes, selected_targets)
    rows = _node_records(mesh or {})
    diagnosed = [_diagnose_target_node(node, rows.get(node), probe=probe) for node in target_nodes]
    blocked = [
        {
            "node": item["node"],
            "status": item["status"],
            "remediationClass": item.get("remediationClass"),
            "remediation": item.get("remediation"),
        }
        for item in diagnosed if not item.get("ok")
    ]
    return {
        "ok": not blocked,
        "selectedNodes": selected_nodes,
        "selectedTargets": selected_targets,
        "nodes": diagnosed,
        "blockedNodes": blocked,
        "remediationClass": blocked[0]["remediationClass"] if blocked else None,
        "remediation": blocked[0].get("remediation") if blocked else None,
    }


def _target_detail(rt: dict[str, Any]) -> str:
    if rt["kind"] == "host":
        if rt.get("routedBy") == "route.node" and rt.get("target") not in ("host", "local"):
            return f"logical target {rt['target']!r} routed to host"
        return "runs on host (local)"
    if rt["kind"] == "node":
        suffix = f" ({rt['url']})" if rt.get("url") else ""
        via = " via route.node" if rt.get("routedBy") == "route.node" else ""
        return f"runs on node '{rt['node']}'{suffix}{via}"
    return f"target '{rt['target']}' not in mesh and no route.node override"


def execution_layers(uri: str, mesh: Any, probe: bool = False) -> dict[str, Any]:
    """Diagnose one URI's execution chain layer by layer.

    Layers:
    ``parse`` -> URI syntax
    ``target`` -> logical URI target and optional route.node override
    ``route`` -> route catalogue/capability, when a catalogue is available
    ``reachability`` -> live node probe, opt-in
    ``safety`` -> query/command and denylist/declared-safe status
    """
    layers: list[dict[str, Any]] = []
    parsed = parse_uri(uri)
    layers.append({
        "layer": "parse",
        "ok": bool(parsed["valid"]),
        "detail": f"scheme={parsed['scheme'] or '<none>'} target={parsed['target'] or '<none>'} path={parsed['path']}",
    })

    routes = mesh_routes(mesh)
    route = route_for_uri(uri, routes)
    rt = _target_for_route(uri, route, mesh)
    layers.append({"layer": "target", "ok": rt["kind"] != "unknown", "detail": _target_detail(rt)})

    if routes:
        layers.append({
            "layer": "route",
            "ok": route is not None,
            "detail": (
                f"matched {route.get('uri')} ({route.get('routeClass') or route_class(route)})"
                if route else "no route descriptor matched this URI"
            ),
        })
    else:
        layers.append({"layer": "route", "ok": True, "skipped": True, "detail": "no route catalogue supplied"})

    if probe and rt["kind"] == "node" and rt.get("url"):
        health = reachable(str(rt["url"]))
        layers.append({
            "layer": "reachability",
            "ok": bool(health["reachable"]),
            "detail": (
                f"reachable, {health.get('routeCount')} routes"
                if health["reachable"] else str(health.get("error") or "unreachable")
            ),
        })
    elif probe and rt["kind"] == "node" and not rt.get("url"):
        layers.append({"layer": "reachability", "ok": False, "detail": "node has no URL in mesh"})

    declared = route.get("safe") if isinstance(route, dict) else None
    safe = route_is_safe(uri, declared)
    eff = effect_of_route(route, uri)
    layers.append({
        "layer": "safety",
        "ok": safe,
        "detail": (
            "read-only (query)"
            if eff == "query" and safe
            else "MUTATING (command) - needs execution allow"
            if safe
            else "blocked by route safety denylist or safe:false"
        ),
    })

    blocked = next((layer["layer"] for layer in layers if not layer["ok"]), None)
    runs_on = rt["node"] if rt["kind"] == "node" else ("host" if rt["kind"] == "host" else None)
    return {
        "uri": uri,
        "uriTarget": parsed.get("target") or "",
        "runsOn": runs_on,
        "kind": rt["kind"],
        "effect": eff,
        "route": route,
        "routeUri": route.get("uri") if isinstance(route, dict) else None,
        "ok": blocked is None,
        "blockedAt": blocked,
        "layers": layers,
    }


def diagnose_plan(steps: list, mesh: Any, probe: bool = False) -> dict[str, Any]:
    """Diagnose every step before execution."""
    uris = [(s.get("uri") if isinstance(s, dict) else str(s)) for s in (steps or [])]
    diagnosed = [execution_layers(str(uri), mesh, probe) for uri in uris if uri]
    return {
        "ok": all(d["ok"] for d in diagnosed),
        "stepCount": len(diagnosed),
        "runsOnByStep": {d["uri"]: d["runsOn"] for d in diagnosed},
        "blockedSteps": [
            {"uri": d["uri"], "blockedAt": d["blockedAt"]}
            for d in diagnosed if not d["ok"]
        ],
        "steps": diagnosed,
    }


def _inventory_sources(mesh: Any) -> list[Any]:
    if not isinstance(mesh, dict):
        return []
    out: list[Any] = []
    for key in ("inventories", "inventory", "envInventories", "envInventory"):
        if mesh.get(key) is not None:
            out.append(mesh[key])
    return out


def _inventory_map(mesh: Any) -> dict[str, dict]:
    """Normalize Twin inventory shapes to ``{node: inventory}``.

    Router stays dependency-free and accepts the shapes already used by chat/flow:
    ``{"inventories": {"host": {...}}}``, ``{"inventory": {...}}`` or a list of
    inventory dicts carrying a ``node`` field.
    """
    out: dict[str, dict] = {}

    def add(node: str, value: Any) -> None:
        if isinstance(value, dict):
            out[str(node or value.get("node") or "host")] = value

    for source in _inventory_sources(mesh):
        if isinstance(source, dict):
            if isinstance(source.get("domains"), dict):
                add(str(source.get("node") or "host"), source)
                continue
            for node, inv in source.items():
                add(str(node), inv)
        elif isinstance(source, list):
            for inv in source:
                if isinstance(inv, dict):
                    add(str(inv.get("node") or "host"), inv)
    return out


def _inventory_for_node(mesh: Any, node: str | None) -> dict:
    inventories = _inventory_map(mesh)
    if not inventories:
        return {}
    key = str(node or "host")
    inv = inventories.get(key) or inventories.get("host") or {}
    return inv if isinstance(inv, dict) else {}


def _domain_options(inventory: dict, domain: str) -> list[dict]:
    raw = (inventory.get("domains") or {}).get(domain) or []
    out: list[dict] = []
    for item in raw:
        if isinstance(item, dict):
            value = item.get("value", item.get("id"))
            out.append({**item, "value": value, "label": str(item.get("label") or value)})
        else:
            out.append({"value": item, "label": str(item)})
    return [opt for opt in out if opt.get("value") is not None]


def _skip_by_payload(payload: dict, cfg: dict) -> bool:
    for key, allowed in (cfg.get("skipWhen") or {}).items():
        val = str(payload.get(key) or "").strip().lower()
        if val and val in {str(item).strip().lower() for item in (allowed or [])}:
            return True
    return False


def _has_explicit(payload: dict, param: str, cfg: dict) -> bool:
    if param not in payload:
        return False
    empty = {_value_key(item) for item in (cfg.get("emptyValues") or [None, ""])}
    return _value_key(payload.get(param)) not in empty


def _value_key(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if re.fullmatch(r"-?\d+", text):
            return int(text)
        return text.lower()
    return value


def _option_value_keys(options: list[dict]) -> set[Any]:
    return {_value_key(opt.get("value")) for opt in options}


def _plan_steps_by_uri(steps: list | None) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for step in steps or []:
        if not isinstance(step, dict):
            continue
        uri = str(step.get("uri") or "")
        if uri and uri not in out:
            out[uri] = step
    return out


def _env_domain_violations(report_step: dict, plan_step: dict, mesh: Any) -> list[dict]:
    """Validate explicit payload enum values against Twin inventory domains."""
    contract = _route_contract(report_step.get("route"))
    domains = contract.get("domains") if isinstance(contract, dict) else {}
    if not isinstance(domains, dict) or not domains:
        return []
    payload = plan_step.get("payload") or {}
    if not isinstance(payload, dict):
        payload = {}
    inventory = _inventory_for_node(mesh, report_step.get("runsOn") or report_step.get("uriTarget") or "host")
    out: list[dict] = []
    for param, cfg in domains.items():
        if not isinstance(cfg, dict) or cfg.get("type") != "enum" or not cfg.get("domain"):
            continue
        if _skip_by_payload(payload, cfg):
            continue
        options = _domain_options(inventory, str(cfg.get("domain") or ""))
        if not options:
            continue
        allowed = _option_value_keys(options)
        if _has_explicit(payload, str(param), cfg):
            value = payload.get(param)
            if _value_key(value) not in allowed:
                out.append({
                    "kind": "env-domain-invalid",
                    "uri": report_step.get("uri"),
                    "parameter": str(param),
                    "domain": cfg.get("domain"),
                    "value": value,
                    "allowed": [opt.get("value") for opt in options],
                    "node": report_step.get("runsOn") or report_step.get("uriTarget") or "host",
                })
            continue
        if cfg.get("optional") is False and len(options) > 1:
            out.append({
                "kind": "env-domain-missing",
                "uri": report_step.get("uri"),
                "parameter": str(param),
                "domain": cfg.get("domain"),
                "allowed": [opt.get("value") for opt in options],
                "node": report_step.get("runsOn") or report_step.get("uriTarget") or "host",
            })
    return out


def _acceptance_violations(report: dict, steps: list | None = None, mesh: Any = None) -> list[dict]:
    """Plan acceptance violations that are independent of the plan generator.

    Routing failures are already deterministic in ``diagnose_plan``. This layer adds
    contract-level facts exposed on route metadata, so LLM, recall and heuristic plans
    all pass through the same predicate.
    """
    out: list[dict] = []
    by_uri = _plan_steps_by_uri(steps)
    for step in report.get("steps") or []:
        if not step.get("ok", True):
            out.append({
                "kind": "routing-blocked",
                "uri": step.get("uri"),
                "blockedAt": step.get("blockedAt"),
            })
            continue
        contract = _route_contract(step.get("route"))
        declared_effect = str(contract.get("effect") or "").strip()
        if declared_effect and declared_effect != step.get("effect"):
            out.append({
                "kind": "effect-mismatch",
                "uri": step.get("uri"),
                "declared": declared_effect,
                "observed": step.get("effect"),
            })
        out.extend(_env_domain_violations(step, by_uri.get(str(step.get("uri") or ""), {}), mesh))
    return out


def accept_plan(steps: list, mesh: Any, probe: bool = False) -> dict[str, Any]:
    """Universal deterministic predicate for accepting a candidate URI plan.

    The generator is intentionally irrelevant: the same function accepts or rejects
    plans from LLM, recall, examples or heuristics. It does not choose a route; it
    checks whether the proposed route sequence is admissible for the current mesh
    and declared route contracts.
    """
    report = diagnose_plan(steps, mesh, probe=probe)
    violations = _acceptance_violations(report, steps, mesh)
    accepted = not violations
    return {
        "ok": accepted,
        "accepted": accepted,
        "kind": "plan-acceptance",
        "violations": violations,
        "report": report,
        "stepCount": report.get("stepCount", 0),
    }


def routes_from_registry(registry: dict, source: str = "built-in") -> list[dict]:
    """Flatten a compiled registry to route descriptors."""
    reglib, _v2 = _runtime_libs()
    routes = []
    for item in reglib.flatten_registry_document(registry):
        entry = item["routeEntry"]
        config = entry.get("config") or {}
        meta = entry.get("meta") or {}
        declared = config.get("safe", meta.get("safe"))
        descriptor = {
            "uri": item["uri"],
            "kind": entry.get("kind"),
            "adapter": entry.get("adapter"),
            "safe": route_is_safe(item["uri"], declared),
            "title": meta.get("label") or meta.get("title") or item["uri"],
            "source": source,
            "inputSchema": config.get("inputSchema") or entry.get("inputSchema") or {"type": "object"},
            "meta": meta,
        }
        descriptor["effect"] = effect_of_route(descriptor, item["uri"])
        descriptor["routeClass"] = route_class(descriptor)
        routes.append(descriptor)
    return sorted(routes, key=lambda item: item["uri"])


def registry_fingerprint(routes: list[dict]) -> str:
    """Stable short etag for a served route surface."""
    import hashlib
    items = sorted((route.get("uri", ""), route.get("kind", "")) for route in routes)
    return hashlib.sha256(repr(items).encode("utf-8")).hexdigest()[:16]


def binding_for_remote_route(route: dict) -> dict:
    return {
        "kind": "service",
        "adapter": "http-service",
        "inputSchema": route.get("inputSchema") or {"type": "object"},
        "meta": {
            "label": route.get("title") or route.get("uri"),
            "node": route.get("node"),
            "sourceAdapter": route.get("adapter"),
        },
    }


def registry_from_routes(routes: list[dict]) -> dict:
    _reglib, v2 = _runtime_libs()
    bindings = {route["uri"]: binding_for_remote_route(route) for route in routes if safe_route(route)}
    return v2.compile_registry({"version": v2.VERSION, "bindings": bindings}, on_conflict="keep")


def target_nodes(prompt: str, nodes: list[dict], explicit: list[str] | None = None) -> list[str]:
    reachable_nodes = [node["name"] for node in nodes if node.get("reachable")]
    if explicit:
        selected = [name for name in explicit if name in reachable_nodes]
        return selected or explicit
    lowered = prompt.lower()
    mentioned = [name for name in reachable_nodes if name.lower() in lowered]
    return mentioned or reachable_nodes


def route_targets_for_nodes(routes: list[dict], node_names: list[str]) -> list[str]:
    """Map host-config node names to URI targets exposed by their routes."""
    all_targets: list[str] = []
    by_node: dict[str, list[str]] = {}
    for route in routes:
        try:
            target = route_target(str(route.get("uri") or ""))
        except Exception:
            continue
        if target not in all_targets:
            all_targets.append(target)
        node = str(route.get("node") or "")
        if node:
            by_node.setdefault(node, [])
            if target not in by_node[node]:
                by_node[node].append(target)

    expanded: list[str] = []
    for name in node_names:
        candidates = by_node.get(name) or ([name] if name in all_targets else [])
        for target in candidates or [name]:
            if target not in expanded:
                expanded.append(target)
    return expanded


__all__ = [
    "UNSAFE_URI_PARTS",
    "accept_plan",
    "binding_for_remote_route",
    "diagnose_plan",
    "effect_of",
    "execution_layers",
    "mesh_routes",
    "parse_uri",
    "registry_fingerprint",
    "registry_from_routes",
    "resolve_target",
    "route_class",
    "route_for_uri",
    "route_is_safe",
    "route_target",
    "route_targets_for_nodes",
    "routes_from_registry",
    "safe_route",
    "target_nodes",
    "uri_is_denied",
    "uri_matches_template",
]
