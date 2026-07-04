#!/usr/bin/env python3
# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Single-source gate for the URI routing kernel.

The routing kernel lives in ``urirun_connector_router.routing``. Historical
paths in ``urirun`` must be shims/re-exports, not second implementations.

Usage:

  python -m urirun_connector_router.check_single_source .
  python -m urirun_connector_router.check_single_source . ../urirun/adapters/python
"""
from __future__ import annotations

import sys
from pathlib import Path


try:
    from urirun_contract.check_single_source import run_marker_gate
except ModuleNotFoundError:  # monorepo checkout, package not installed yet
    _ROOT = Path(__file__).resolve().parents[2]
    _CONTRACT = _ROOT / "urirun-contract"
    if _CONTRACT.is_dir():
        sys.path.insert(0, str(_CONTRACT))
    from urirun_contract.check_single_source import run_marker_gate


ROUTING_MARKERS = {
    "routing_core": [
        r"^def parse_uri\(",
        r"^def execution_layers\(",
        r"^def diagnose_plan\(",
    ],
    "routing_templates": [
        r"^def uri_matches_template\(",
        r"^def route_for_uri\(",
    ],
    "routing_registry": [
        r"^def routes_from_registry\(",
        r"^def registry_from_routes\(",
    ],
    "target_resolution": [
        r"^def explicit_node_name_from_prompt\(",
        r"^def apply_host_default_when_no_node_in_prompt\(",
    ],
}


def main(*roots: str) -> int:
    return run_marker_gate(
        ROUTING_MARKERS,
        roots or (".",),
        ok_label="one source",
        missing_label="missing",
        source_hint="keep the implementation in urirun_connector_router.routing; make old paths shims",
    )


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:]))
