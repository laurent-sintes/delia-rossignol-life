from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .pdf_layout import CVLayoutRules


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    proposal_id: str
    source_id: str
    locator: str


@dataclass(frozen=True, slots=True)
class CVSequenceStep:
    label: str
    responsibilities: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CVHighlightCard:
    label: str
    items: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CVHighlight:
    label: str
    cards: tuple[CVHighlightCard, ...]


@dataclass(frozen=True, slots=True)
class CVExperience:
    entity_id: str
    period: str
    heading: str
    mission: str
    responsibilities: tuple[str, ...]
    bullet_limit: int
    responsibility_sequence: tuple[CVSequenceStep, ...]
    organization_name: str
    organization_tagline: str
    context_label: str
    highlight: CVHighlight | None
    evidence: tuple[EvidenceRef, ...]


@dataclass(frozen=True, slots=True)
class CVContinuityGroup:
    group_id: str
    label: str
    context_label: str
    period: str
    job_role: str
    experiences: tuple[CVExperience, ...]
    responsibility_sequence: tuple[CVSequenceStep, ...]
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
    layout_rules: CVLayoutRules
    strategy_id: str
    name: str
    email: str
    phone: str
    tagline: str
    signature: str
    profile_summary: str
    key_skills: tuple[str, ...]
    tools_line: str
    recent_continuity_groups: tuple[CVContinuityGroup, ...]
    recent_experiences: tuple[CVExperience, ...]
    complementary_experiences: tuple[CVExperience, ...]
    education: tuple[CVEducation, ...]
    language_and_interests: str
    photo: Path
    evidence: tuple[EvidenceRef, ...]

    @property
    def source_ids(self) -> tuple[str, ...]:
        return tuple(sorted({item.source_id for item in self.evidence}))
