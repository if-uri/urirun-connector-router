# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Routing kernel must have one implementation; compatibility paths are shims."""
from __future__ import annotations

import os

from urirun_connector_router import check_single_source


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_current_router_package_has_one_routing_source():
    assert check_single_source.main(ROOT) == 0


def test_single_source_gate_rejects_duplicate_router_kernel(tmp_path):
    body = "\n".join([
        "def parse_uri(uri):",
        "    return {}",
        "",
        "def execution_layers(uri, mesh, probe=False):",
        "    return {}",
        "",
        "def diagnose_plan(steps, mesh, probe=False):",
        "    return {}",
        "",
    ])
    (tmp_path / "one.py").write_text(body, encoding="utf-8")
    (tmp_path / "two.py").write_text(body, encoding="utf-8")

    assert check_single_source.main(str(tmp_path)) == 1
