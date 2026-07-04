# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""urirun-connector-router - URI-schema routing and router:// diagnostics."""
from __future__ import annotations

from urirun_connector_router.routing import (
    accept_plan,
    diagnose_targets,
    diagnose_plan,
    execution_layers,
    parse_uri,
    registry_from_routes,
    resolve_target,
    route_class,
    route_for_uri,
    route_is_safe,
    route_target,
    route_targets_for_nodes,
    routes_from_registry,
    safe_route,
    target_nodes,
)


def urirun_bindings():
    from urirun_connector_router.core import urirun_bindings as _b
    return _b()


__all__ = [
    "diagnose_plan",
    "diagnose_targets",
    "accept_plan",
    "execution_layers",
    "parse_uri",
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
    "urirun_bindings",
]
