from __future__ import annotations

from collections.abc import Iterable
from typing import Any

SECTOR_FUNCTIONAL_PAIR_SEPARATOR = "::"


def sector_functional_pair_id(sector_id: str, query_family_id: str) -> str:
    return f"{sector_id}{SECTOR_FUNCTIONAL_PAIR_SEPARATOR}{query_family_id}"


def configured_sector_functional_pairs(policy: dict[str, Any]) -> set[str]:
    configured = policy.get("sector_functional_coverage")
    if not isinstance(configured, dict):
        return set()
    return {
        sector_functional_pair_id(str(sector_id), str(query_family_id))
        for sector_id, query_family_ids in configured.items()
        if isinstance(query_family_ids, list)
        for query_family_id in query_family_ids
        if str(sector_id).strip() and str(query_family_id).strip()
    }


def covered_sector_functional_pairs(
    sectors: Iterable[str],
    query_families: Iterable[str],
    required_pairs: Iterable[str],
) -> set[str]:
    required = set(required_pairs)
    return {
        pair
        for sector_id in sectors
        for query_family_id in query_families
        if (pair := sector_functional_pair_id(str(sector_id), str(query_family_id))) in required
    }
