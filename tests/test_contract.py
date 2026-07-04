# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""The router is a connector, so it carries a contract — conform + every handler route covered."""
import json
import os

import pytest

_uc = pytest.importorskip("urirun_contract")
_scaffold = pytest.importorskip("urirun_contract.contract_scaffold")
conform, Contract = _uc.conform, _uc.Contract

PKG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "urirun_connector_router")
CONTRACTS = os.path.join(PKG, "contracts.json")


def _load() -> dict:
    doc = json.load(open(CONTRACTS))
    return {r: Contract(version=c["version"], effect=c["effect"], reversible=c["reversible"],
                        inverse_route=c.get("inverseRoute", ""), inp=c["inp"], out=c["out"],
                        errors=tuple(c["errors"]), examples=tuple(c["examples"]))
            for r, c in doc["contracts"].items()}


def test_contract_conforms():
    conform(_load())


def test_every_handler_route_has_a_contract():
    # derive routes from the connector's REAL bindings (robust to the @_handler wrapper that
    # discover_routes' `.handler(` regex misses); needs urirun to build the connector.
    pytest.importorskip("urirun")
    import sys
    sys.path.insert(0, os.path.dirname(PKG))
    from urirun_connector_router import core
    declared = set(json.load(open(CONTRACTS))["contracts"])
    for uri in core.urirun_bindings()["bindings"]:
        route = uri.split("://host/", 1)[1] if "://host/" in uri else uri.split("://", 1)[-1]
        assert route in declared, f"handler route {route!r} has no contract"
