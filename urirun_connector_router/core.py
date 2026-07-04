# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""router:// connector facade over the pure URI routing kernel.

The pure routing API lives in :mod:`urirun_connector_router.routing` and has no
hard dependency on ``urirun``. When ``urirun`` is installed this module registers
read-only ``router://`` bindings; when it is not installed the public functions
still return ordinary dict envelopes and the CLI can print a static binding doc.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable

try:
    import urirun as _urirun  # type: ignore
except Exception:  # noqa: BLE001
    _urirun = None

try:
    from urirun_connector_router import routing as R
except ImportError:  # flat-module deploy
    import routing as R  # type: ignore

CONNECTOR_ID = "router"
_HAS_URIRUN_CONNECTOR = _urirun is not None and hasattr(_urirun, "connector")
conn = _urirun.connector(CONNECTOR_ID, scheme="router") if _HAS_URIRUN_CONNECTOR else None

_MESH_PATHS = (
    os.path.expanduser("~/.urirun/mesh.json"),
    os.path.join(os.getcwd(), ".urirun", "mesh.json"),
    os.path.expanduser("~/.urirun/nodes.json"),
)


def _handler(route: str, **kwargs):
    if conn is not None:
        return conn.handler(route, isolated=False, **kwargs)

    def _decorate(fn: Callable):
        return fn

    return _decorate


def _ok(**fields: Any) -> dict[str, Any]:
    if _urirun is not None and hasattr(_urirun, "ok"):
        return _urirun.ok(**fields)
    return {"ok": True, **fields}


def _fail(message: str, **fields: Any) -> dict[str, Any]:
    if _urirun is not None and hasattr(_urirun, "fail"):
        return _urirun.fail(message, **fields)
    return {"ok": False, "error": message, **fields}


def _load_mesh(payload: dict) -> Any:
    """Mesh from payload, then standard mesh/nodes config paths."""
    if isinstance(payload, dict) and payload.get("mesh") is not None:
        return payload["mesh"]
    for path in _MESH_PATHS:
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            continue
    return {"nodes": []}


@_handler("route/query/resolve", meta={"label": "Resolve where one URI runs + diagnose layers"})
def resolve(uri: str = "", mesh: Any = None, probe: bool = False) -> dict[str, Any]:
    """One URI -> execution location plus layer-by-layer diagnosis."""
    if not uri:
        return _fail("uri is required", connector=CONNECTOR_ID)
    diag = R.execution_layers(uri, _load_mesh({"mesh": mesh}), probe=bool(probe))
    return _ok(connector=CONNECTOR_ID, action="resolve", **diag)


@_handler("plan/query/diagnose", meta={"label": "Diagnose where every NL-plan step runs"})
def diagnose(steps: list | None = None, mesh: Any = None, probe: bool = False) -> dict[str, Any]:
    """Plan step URIs -> per-step execution location and blocked layers."""
    report = R.diagnose_plan(steps or [], _load_mesh({"mesh": mesh}), probe=bool(probe))
    return _ok(connector=CONNECTOR_ID, action="diagnose", **report)


@_handler("target/query/diagnose", meta={"label": "Diagnose selected host/node targets"})
def target_diagnose(selectedNodes: list | None = None,
                    selectedTargets: list | None = None,
                    mesh: Any = None,
                    probe: bool = False) -> dict[str, Any]:
    """Selected host/node targets -> missing node URL / reachability diagnostics."""
    report = R.diagnose_targets(
        selected_nodes=selectedNodes or [],
        selected_targets=selectedTargets or [],
        mesh=_load_mesh({"mesh": mesh}),
        probe=bool(probe),
    )
    return _ok(connector=CONNECTOR_ID, action="target-diagnose", **report)


@_handler("plan/query/accept", meta={"label": "Accept or reject a candidate URI plan"})
def accept(steps: list | None = None, mesh: Any = None, probe: bool = False) -> dict[str, Any]:
    """Universal deterministic predicate for plans from LLM, recall or heuristics."""
    verdict = R.accept_plan(steps or [], _load_mesh({"mesh": mesh}), probe=bool(probe))
    return _ok(connector=CONNECTOR_ID, action="accept", **verdict)


@_handler("mesh/query/targets", meta={"label": "List resolvable execution targets"})
def targets(mesh: Any = None) -> dict[str, Any]:
    """Return ``host`` plus every named node in the mesh."""
    nodes = R._node_url_map(_load_mesh({"mesh": mesh}))  # intentionally private-normalizer reuse
    return _ok(
        connector=CONNECTOR_ID,
        action="targets",
        targets=["host"] + sorted(nodes),
        nodes=[{"node": node, "url": url} for node, url in sorted(nodes.items())],
    )


def _static_bindings() -> dict[str, Any]:
    bindings = {
        "router://host/route/query/resolve": {
            "kind": "function",
            "adapter": "local-function",
            "inputSchema": {"type": "object"},
            "meta": {"label": "Resolve where one URI runs + diagnose layers"},
        },
        "router://host/plan/query/diagnose": {
            "kind": "function",
            "adapter": "local-function",
            "inputSchema": {"type": "object"},
            "meta": {"label": "Diagnose where every NL-plan step runs"},
        },
        "router://host/target/query/diagnose": {
            "kind": "function",
            "adapter": "local-function",
            "inputSchema": {"type": "object"},
            "meta": {"label": "Diagnose selected host/node targets"},
        },
        "router://host/plan/query/accept": {
            "kind": "function",
            "adapter": "local-function",
            "inputSchema": {"type": "object"},
            "meta": {"label": "Accept or reject a candidate URI plan"},
        },
        "router://host/mesh/query/targets": {
            "kind": "function",
            "adapter": "local-function",
            "inputSchema": {"type": "object"},
            "meta": {"label": "List resolvable execution targets"},
        },
    }
    return {"version": "urirun.bindings.v2", "bindings": bindings}


def urirun_bindings() -> dict[str, Any]:
    return conn.bindings() if conn is not None else _static_bindings()


def connector_manifest() -> dict[str, Any]:
    if conn is not None and hasattr(conn, "manifest"):
        return conn.manifest()
    return {"id": CONNECTOR_ID, "scheme": "router", "bindings": sorted(_static_bindings()["bindings"])}


def main() -> int:
    print(json.dumps(urirun_bindings(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
