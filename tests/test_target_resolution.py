# Author: Tom Sapletta · https://tom.sapletta.com
# Part of the ifURI solution.
"""Target-selection policy belongs to the router package, not chat orchestration."""
from __future__ import annotations

from urirun_connector_router import target_resolution as T


ALIAS = {"lenovo": "lenovo", "laptop": "lenovo"}


def test_host_default_strips_stale_remote_when_prompt_omits_node():
    nodes, targets = T.apply_host_default_when_no_node_in_prompt(
        "opublikuj post na LinkedIn",
        ["lenovo"],
        ["host", "node:lenovo"],
        ALIAS,
    )

    assert nodes == []
    assert targets == ["host"]


def test_host_default_keeps_remote_when_prompt_names_node():
    nodes, targets = T.apply_host_default_when_no_node_in_prompt(
        "opublikuj post na LinkedIn na lenovo",
        ["lenovo"],
        ["host", "node:lenovo"],
        ALIAS,
    )

    assert nodes == ["lenovo"]
    assert targets == ["host", "node:lenovo"]


def test_explicit_node_name_uses_alias_map_before_generic_patterns():
    assert T.explicit_node_name_from_prompt("otworz przegladarke na laptop", ALIAS) == "lenovo"


def test_explicit_node_name_falls_back_to_node_pattern():
    assert T.explicit_node_name_from_prompt("zrob zrzut na node workstation-1", {}) == "workstation-1"


def test_explicit_node_name_does_not_treat_local_host_forms_as_nodes():
    assert T.explicit_node_name_from_prompt("zrob zrzut ekranu na komputerze hosta", ALIAS) == ""
    assert T.explicit_node_name_from_prompt("na komputerze hosta nvidia zrob zrzut ekranu", ALIAS) == ""


def test_explicit_node_name_does_not_treat_sentence_words_as_nodes():
    assert T.explicit_node_name_from_prompt("jesli nie wskazalem node, uzyj host i zrob zrzut", ALIAS) == ""
    assert T.explicit_node_name_from_prompt("na tym komputerze zrob zrzut ekranu", ALIAS) == ""


def test_reverse_node_pattern_requires_identifier_shape_without_alias():
    assert T.explicit_node_name_from_prompt("zrob zrzut na workstation-1 node", {}) == "workstation-1"
    assert T.explicit_node_name_from_prompt("sprawdz status android node", {}) == ""


def test_prompt_says_local_is_owned_by_target_resolution():
    assert T.prompt_says_local("zrob zrzut na lokalnym komputerze")
    assert T.prompt_says_local("zrob zrzut ekranu na komputerze hosta")
    assert T.prompt_says_local("na tym komputerze zrob zrzut ekranu")
    assert not T.prompt_says_local("zrob zrzut na zdalnym komputerze")


def test_resolve_selected_targets_defaults_stale_url_state_to_host():
    requested_nodes, requested_targets, selected_nodes, selected_targets = T.resolve_selected_targets(
        {
            "nodes": ["lenovo"],
            "targets": ["host", "node:lenovo"],
            "target_explicit": False,
        },
        "opublikuj post na LinkedIn",
        ALIAS,
    )

    assert requested_nodes == ["lenovo"]
    assert requested_targets == ["host", "node:lenovo"]
    assert selected_nodes == []
    assert selected_targets == ["host"]


def test_resolve_selected_targets_infers_named_node_from_prompt_despite_stale_state():
    requested_nodes, requested_targets, selected_nodes, selected_targets = T.resolve_selected_targets(
        {
            "nodes": ["old-node"],
            "targets": ["host", "node:old-node"],
            "target_explicit": False,
        },
        "opublikuj post na LinkedIn na lenovo",
        ALIAS,
    )

    assert requested_nodes == ["old-node"]
    assert requested_targets == ["host", "node:old-node"]
    assert selected_nodes == ["lenovo"]
    assert selected_targets == ["node:lenovo"]


def test_resolve_selected_targets_keeps_explicit_remote_selection():
    assert T.resolve_selected_targets(
        {
            "nodes": ["lenovo"],
            "targets": ["host", "node:lenovo"],
            "target_explicit": True,
        },
        "opublikuj post na LinkedIn",
        ALIAS,
    )[2:] == (["lenovo"], ["host", "node:lenovo"])


def test_selected_nodes_from_targets_dedupes_explicit_and_target_nodes():
    assert T.selected_nodes_from_targets(["  lenovo  ", "lenovo"], ["host", "node:lenovo", "node:kiosk"]) == [
        "lenovo",
        "kiosk",
    ]
