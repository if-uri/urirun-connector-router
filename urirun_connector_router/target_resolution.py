"""Target resolution: which node(s) a request runs on, as pure transforms over request state.

Single source for the "where does this run" math the host chat orchestrator used to inline. Pure:
dicts/lists/sets in, dicts/lists out — no hub runtime, no NodeClient, no I/O. NL-intent → target
inference that needs an LLM stays in the planner; deterministic target policy such as "prompt names
a known node" and "stale UI node selection defaults back to host" lives here so chat does not grow a
second routing kernel.

The host imports these and keeps thin wrappers where a value must be sourced from the hub (e.g.
``with_local_host_routes`` takes the host's entry-point routes as an argument rather than importing
``object_registry`` here, so this package stays a leaf routing connector).
"""
from __future__ import annotations

import re


LOCAL_NL_KEYWORDS = (
    "lokalnym", "lokalny", "lokalnie", "lokalnego", "lokalnej",
    "tym komputerze", "ten komputer", "tego komputera",
    "komputerze hosta", "komputer hosta", "na hoscie", "na hoście",
    "hosta nvidia", "host nvidia",
    "local computer", "my computer", "this computer", "this machine",
)

REMOTE_NL_KEYWORDS = (
    "zdalny", "zdalnym", "zdalnego", "zdalne", "zdalnej", "zdalnie",
    "remote", "zewnętrznym", "zewnetrznym", "external",
    "on node", "na nodzie", "na node",
)

NODE_NAME_STOPWORDS = {
    "host", "hosta", "hoscie", "hoście", "local", "lokalny", "lokalnym", "zdalny", "zdalnym", "remote",
    "komputer", "komputerze", "laptop", "laptopie", "maszyna", "machine",
    "node", "nodzie", "wezel", "wezle", "węzeł", "węźle", "na", "w",
    "zrob", "zrób", "uzyj", "użyj", "wskazalem", "wskazałem",
}


def _looks_like_node_identifier(node: str) -> bool:
    """A bare inferred node must look like an identifier, not a random sentence word."""
    return bool(re.search(r"[0-9_.-]", node or ""))


def prompt_node_match(prompt: str, alias_map: dict[str, str]) -> str:
    """Return the known node alias that appears first in the prompt."""
    text = prompt.casefold()
    best_pos = len(text) + 1
    best_node = ""
    for alias, node in sorted((alias_map or {}).items(), key=lambda item: len(str(item[0])), reverse=True):
        clean_alias = str(alias or "").casefold()
        if not clean_alias:
            continue
        match = re.search(rf"(?<![\w.-]){re.escape(clean_alias)}(?![\w.-])", text)
        if match and match.start() < best_pos:
            best_pos = match.start()
            best_node = str(node or "")
    return best_node


def explicit_node_name_from_prompt(prompt: str, alias_map: dict[str, str]) -> str:
    """Return a named remote node even when the UI currently has only host selected."""
    matched = prompt_node_match(prompt, alias_map)
    if matched and matched != "host":
        return matched
    text = prompt.casefold()
    patterns = (
        r"(?<![\w.-])(?:node|nodzie|wezel|wezle|węzeł|węźle)\s+(?P<node>[a-z0-9][a-z0-9_.-]*)",
        r"(?<![\w.-])(?:laptop|laptopie|komputer|komputerze|machine)\s+(?P<node>[a-z0-9][a-z0-9_.-]*)",
        r"(?<![\w.-])(?P<node>[a-z0-9][a-z0-9_.-]*)\s+(?:laptop|node)(?![\w.-])",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if not match:
            continue
        node = (match.group("node") or "").strip("._-")
        if not node or node in NODE_NAME_STOPWORDS:
            continue
        if pattern == patterns[-1] and not _looks_like_node_identifier(node):
            continue
        if node:
            return node
    return ""


def prompt_names_remote(prompt: str, alias_map: dict[str, str]) -> bool:
    """True when the prompt explicitly names a remote node or remote target class."""
    text = prompt.lower()
    if any(keyword in text for keyword in REMOTE_NL_KEYWORDS):
        return True
    node = explicit_node_name_from_prompt(prompt, alias_map)
    return bool(node and node != "host")


def prompt_says_local(prompt: str) -> bool:
    """True when the prompt explicitly asks for the local machine."""
    text = prompt.lower()
    return any(keyword in text for keyword in LOCAL_NL_KEYWORDS)


def selected_nodes_from_targets(selected_nodes: list[str], selected_targets: list[str]) -> list[str]:
    """Keep API callers and browser form state consistent: node targets imply selected nodes."""
    out: list[str] = []
    seen: set[str] = set()
    for node in selected_nodes:
        clean = str(node).strip()
        if clean and clean not in seen:
            out.append(clean)
            seen.add(clean)
    for target in selected_targets:
        clean = str(target).strip()
        if not clean.startswith("node:"):
            continue
        node = clean.split(":", 1)[1].strip()
        if node and node not in seen:
            out.append(node)
            seen.add(node)
    return out


def parse_chat_nodes_targets(payload: dict) -> tuple[list[str], list[str]]:
    """Extract requested nodes/targets from a chat/API payload."""
    requested_nodes = [str(i).strip() for i in (payload.get("nodes") or []) if str(i).strip()]
    requested_targets = [str(i).strip() for i in (payload.get("targets") or []) if str(i).strip()]
    return requested_nodes, requested_targets


def target_selection_explicit(payload: dict) -> bool:
    """True when node/target state is an explicit routing command, not stale UI state."""
    if "target_explicit" not in payload and "targetExplicit" not in payload:
        return False
    raw = payload.get("target_explicit", payload.get("targetExplicit"))
    if isinstance(raw, str):
        return raw.strip().lower() not in {"0", "false", "no", "off"}
    return bool(raw)


def init_selected_targets(requested_nodes: list[str], requested_targets: list[str]) -> list[str]:
    """Initial target set before NL correction: explicit targets win, otherwise host + nodes."""
    if requested_targets:
        return list(requested_targets)
    return ["host", *[f"node:{name}" for name in requested_nodes]]


def infer_node_targets(prompt: str, requested_nodes: list[str], requested_targets: list[str],
                       alias_map: dict[str, str]) -> list[str] | None:
    """Infer a remote target only when the request does not already explicitly pick one."""
    if requested_nodes:
        return None
    target_set = {str(target).strip() for target in (requested_targets or []) if str(target).strip()}
    if target_set and target_set != {"host"}:
        return None
    matched = explicit_node_name_from_prompt(prompt, alias_map)
    return [f"node:{matched}"] if matched and matched != "host" else None


def has_explicit_remote_selection(requested_nodes: list[str], requested_targets: list[str],
                                  target_explicit: bool = True) -> bool:
    """True when the UI/API deliberately selected a remote node."""
    if not target_explicit:
        return False
    if any(str(node).strip() for node in requested_nodes or []):
        return True
    return any(str(target).strip().startswith("node:") for target in requested_targets or [])


def resolve_selected_targets(payload: dict, prompt: str,
                             alias_map: dict[str, str]) -> tuple[list[str], list[str], list[str], list[str]]:
    """Resolve requested and effective node/target sets for chat routing.

    Returns ``(requested_nodes, requested_targets, selected_nodes, selected_targets)``.
    Stale copied UI state defaults back to host unless the prompt names a remote node;
    explicit UI/API node choices remain authoritative.
    """
    requested_nodes, requested_targets = parse_chat_nodes_targets(payload)
    target_explicit = target_selection_explicit(payload)
    selected_targets = init_selected_targets(requested_nodes, requested_targets)
    inferred = infer_node_targets(
        prompt,
        requested_nodes if target_explicit else [],
        requested_targets if target_explicit else [],
        alias_map,
    )
    if inferred is not None:
        selected_targets = inferred
    selected_nodes = selected_nodes_from_targets(
        list(requested_nodes) if target_explicit else [],
        selected_targets,
    )
    if not has_explicit_remote_selection(requested_nodes, requested_targets, target_explicit):
        selected_nodes, selected_targets = apply_host_default_when_no_node_in_prompt(
            prompt, selected_nodes, selected_targets, alias_map)
    return requested_nodes, requested_targets, selected_nodes, selected_targets


def apply_host_default_when_no_node_in_prompt(
    prompt: str,
    selected_nodes: list[str],
    selected_targets: list[str],
    alias_map: dict[str, str],
) -> tuple[list[str], list[str]]:
    """Default stale remote selections back to host unless the prompt names a remote node."""
    has_remote = any(str(target) != "host" for target in selected_targets or [])
    if not has_remote:
        return selected_nodes, selected_targets
    if prompt_names_remote(prompt, alias_map):
        return selected_nodes, selected_targets
    return [], ["host"]


def rebuild_node_targets(selected_targets: list[str], actual: list[str],
                         has_local: bool, existing_remote: set[str]) -> list[str]:
    """Rebuild the target list after a flow resolved its actual node set.

    Keeps the originally-selected ``node:*`` targets, prepends ``host`` when the flow runs
    anything locally, and appends any newly-discovered nodes not already selected."""
    targets: list[str] = [t for t in selected_targets if t.startswith("node:")]
    if has_local:
        targets = ["host"] + targets
    for node in actual:
        if node not in existing_remote:
            targets.append(f"node:{node}")
    return targets


def inactive_node_urls(nodes: list, active_names: set[str]) -> set:
    """URLs of reachable nodes that are NOT in the active selection — used to prune the serviceMap."""
    return {
        n["url"] for n in nodes
        if n.get("reachable") and n.get("name") not in active_names and n.get("url")
    }


def route_targets_active(route: dict, active_names: set[str], include_host: bool) -> bool:
    """True when a route's node is in the active selection (host routes gated by ``include_host``)."""
    node = str(route.get("node") or "").strip()
    if node and node != "host":
        return node in active_names
    return include_host


def filter_mesh_for_targets(discovered: dict, selected_targets: list[str]) -> dict:
    """Return a copy of ``discovered`` with serviceMap filtered to only route to selected nodes.

    When ``selected_targets`` is ``["host"]`` (no remote node), removes all serviceMap entries that
    point to remote node URLs and drops remote-node routes — so ``kvm://host/...`` stays local
    instead of being treated as a remote node capability during execution/memory capture."""
    active_names = {t.split(":", 1)[1] for t in selected_targets if t.startswith("node:")}
    include_host = not selected_targets or "host" in selected_targets

    full_map = discovered.get("serviceMap") or {}
    nodes = discovered.get("nodes") or []
    inactive_urls = inactive_node_urls(nodes, active_names)
    routes = [r for r in (discovered.get("routes") or []) if route_targets_active(r, active_names, include_host)]
    service_map = {k: v for k, v in full_map.items() if v not in inactive_urls}
    if routes == (discovered.get("routes") or []) and service_map == full_map:
        return discovered
    return {**discovered, "routes": routes, "serviceMap": service_map}


def with_local_host_routes(discovered: dict, selected_targets: list[str],
                           local_routes: list[dict] | None) -> dict:
    """Merge the host's local entry-point routes into ``discovered`` when host is a target.

    ``local_routes`` is injected by the caller (the host owns the entry-point route source); this
    function only does the host-gated, de-duplicated merge."""
    include_host = not selected_targets or "host" in selected_targets
    if not include_host or not local_routes:
        return discovered
    routes = list(discovered.get("routes") or [])
    seen = {str(route.get("uri") or "") for route in routes}
    extra = [route for route in local_routes if str(route.get("uri") or "") not in seen]
    if not extra:
        return discovered
    return {**discovered, "routes": [*routes, *extra], "localHostRoutes": local_routes}
