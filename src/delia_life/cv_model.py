from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    proposal_id: str
    source_id: str
    locator: str


@dataclass(frozen=True, slots=True)
class CVExperience:
    entity_id: str
    period: str
    heading: str
    mission: str
    responsibilities: tuple[str, ...]
    bullet_limit: int
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class CVEducation:
    entity_id: str
    primary: str
    secondary: str
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class CVViewModel:
    template_id: str
    template_version: str
    strategy_id: str
    name: str
    email: str
    phone: str
    tagline: str
    signature: str
    profile_summary: str
    key_skills: tuple[str, ...]
    tools_line: str
    recent_experiences: tuple[CVExperience, ...]
    complementary_experiences: tuple[CVExperience, ...]
    education: tuple[CVEducation, ...]
    language_and_interests: str
    photo: Path
    evidence: tuple[EvidenceRef, ...]

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_id for item in self.evidence}))
