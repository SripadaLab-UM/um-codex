"""The Toolkit's model list, newest release first (M7)."""

from __future__ import annotations

import random

from umcodex.toolkit import by_release

# Codex's own catalog order (`codex debug models --bundled`, 0.157.1), then older ones.
CATALOG = [
    "gpt-6-astra",
    "gpt-6-sol",
    "gpt-6-luna",
    "gpt-5.6-sol",
    "gpt-5.6-terra",
    "gpt-5.6-luna",
    "gpt-5.5",
]


def test_models_sort_by_release_newest_first():
    shuffled = list(CATALOG)
    random.Random(7).shuffle(shuffled)
    assert by_release(shuffled) == CATALOG


def test_versions_compare_as_numbers_and_unknown_names_go_last():
    found = by_release(
        ["gpt-5.10", "gpt-5.9", "gpt-5.4", "gpt-5.4.1", "gpt-6", "gpt-4o", "o3", "o4-mini", "codex-x"]
    )
    assert found == [
        "gpt-6",
        "gpt-5.10",
        "gpt-5.9",
        "gpt-5.4.1",
        "gpt-5.4",
        "gpt-4o",
        "o4-mini",
        "o3",
        "codex-x",
    ]


def test_within_a_version_the_plain_name_comes_after_the_known_variants():
    assert by_release(["gpt-5.6-mini", "gpt-5.6", "gpt-5.6-terra", "gpt-5.6-sol"]) == [
        "gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6", "gpt-5.6-mini",
    ]  # fmt: skip
