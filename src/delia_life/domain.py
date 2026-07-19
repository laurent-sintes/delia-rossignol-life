from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ValidationError


@dataclass(frozen=True, slots=True)
class ProposalTarget:
    entity_type: str
    entity_id: str
    field: str

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> ProposalTarget:
        try:
            target = cls(
                entity_type=str(value["entity_type"]),
                entity_id=str(value["entity_id"]),
                field=str(value["field"]),
            )
        except KeyError as error:
            raise ValidationError(f"Proposal target is missing {error.args[0]}") from error
        if not all((target.entity_type, target.entity_id, target.field)):
            raise ValidationError("Proposal target components cannot be empty")
        return target

    @property
    def key(self) -> tuple[str, str, str]:
        return self.entity_type.casefold(), self.entity_id.casefold(), self.field.casefold()

    def entity_path(self, knowledge_root: Path) -> Path:
        return knowledge_root / self.entity_type / f"{self.entity_id}.json"
