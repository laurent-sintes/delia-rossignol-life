"""Deterministic geometry and layout checks for generated PDF documents."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from math import ceil
from typing import Any

TOLERANCE = 0.05


@dataclass(frozen=True, slots=True)
class CVLayoutRules:
    spacing_unit_pt: float
    text_gap_pt: float
    component_gap_pt: float
    card_padding_pt: float
    experience_gap_pt: float
    safe_bottom_pt: float

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> CVLayoutRules:
        rules = cls(
            spacing_unit_pt=float(value["spacing_unit_pt"]),
            text_gap_pt=float(value["text_gap_pt"]),
            component_gap_pt=float(value["component_gap_pt"]),
            card_padding_pt=float(value["card_padding_pt"]),
            experience_gap_pt=float(value["experience_gap_pt"]),
            safe_bottom_pt=float(value["safe_bottom_pt"]),
        )
        rules.validate()
        return rules

    def validate(self) -> None:
        if self.spacing_unit_pt <= 0:
            raise ValueError("layout spacing unit must be positive")
        for name, value in (
            ("text_gap_pt", self.text_gap_pt),
            ("component_gap_pt", self.component_gap_pt),
            ("card_padding_pt", self.card_padding_pt),
            ("experience_gap_pt", self.experience_gap_pt),
            ("safe_bottom_pt", self.safe_bottom_pt),
        ):
            if value <= 0:
                raise ValueError(f"layout {name} must be positive")
            quotient = value / self.spacing_unit_pt
            if abs(quotient - round(quotient)) > TOLERANCE:
                raise ValueError(f"layout {name} must be a multiple of spacing_unit_pt")


@dataclass(frozen=True, slots=True)
class CardGeometry:
    outer_x: float
    outer_top: float
    outer_width: float
    outer_height: float
    stroke_width: float
    path_x: float
    path_bottom: float
    path_width: float
    path_height: float
    label_baseline: float
    divider_y: float
    body_baselines: tuple[float, ...]
    label_to_divider_gap: float
    divider_to_body_gap: float
    padding: float

    @property
    def outer_right(self) -> float:
        return self.outer_x + self.outer_width

    @property
    def outer_bottom(self) -> float:
        return self.outer_top - self.outer_height


@dataclass(frozen=True, slots=True)
class LayoutBox:
    name: str
    page: int
    kind: str
    left: float
    right: float
    top: float
    bottom: float

    def validate(self) -> None:
        if self.right < self.left or self.top < self.bottom:
            raise ValueError(f"invalid layout box: {self.name}")

    def as_dict(self) -> dict[str, float | int | str]:
        return {
            "name": self.name,
            "page": self.page,
            "kind": self.kind,
            "left": self.left,
            "right": self.right,
            "top": self.top,
            "bottom": self.bottom,
        }


def _snap_up(value: float, unit: float) -> float:
    return ceil((value - TOLERANCE) / unit) * unit


def calculate_card_geometry(
    *,
    x: float,
    top: float,
    width: float,
    line_count: int,
    label_size: float,
    label_leading: float,
    body_size: float,
    body_leading: float,
    rules: CVLayoutRules,
    minimum_height: float,
    stroke_width: float = 0.8,
) -> CardGeometry:
    """Calculate a stroked card whose visible outline stays inside its allocation."""
    if width <= stroke_width or line_count < 1:
        raise ValueError("card geometry requires a positive width and at least one body line")
    content_height = (
        rules.card_padding_pt
        + label_leading
        + rules.text_gap_pt
        + stroke_width
        + rules.text_gap_pt
        + (line_count * body_leading)
        + rules.card_padding_pt
    )
    outer_height = _snap_up(max(minimum_height, content_height), rules.spacing_unit_pt)
    outer_bottom = top - outer_height
    path_x = x + (stroke_width / 2)
    path_bottom = outer_bottom + (stroke_width / 2)

    label_top = top - rules.card_padding_pt
    label_baseline = label_top - label_size
    label_bottom = label_top - label_leading
    divider_y = label_bottom - rules.text_gap_pt - (stroke_width / 2)
    body_top = divider_y - (stroke_width / 2) - rules.text_gap_pt
    body_baselines = tuple(body_top - body_size - (index * body_leading) for index in range(line_count))

    return CardGeometry(
        outer_x=x,
        outer_top=top,
        outer_width=width,
        outer_height=outer_height,
        stroke_width=stroke_width,
        path_x=path_x,
        path_bottom=path_bottom,
        path_width=width - stroke_width,
        path_height=outer_height - stroke_width,
        label_baseline=label_baseline,
        divider_y=divider_y,
        body_baselines=body_baselines,
        label_to_divider_gap=rules.text_gap_pt,
        divider_to_body_gap=rules.text_gap_pt,
        padding=rules.card_padding_pt,
    )


@dataclass(slots=True)
class LayoutAudit:
    safe_left: float
    safe_right: float
    safe_top: float
    safe_bottom: float
    spacing_unit: float
    frames: list[dict[str, float | str]] = field(default_factory=list)
    elements: list[dict[str, float | int | str]] = field(default_factory=list)
    gaps: list[dict[str, float | str]] = field(default_factory=list)
    alignments: list[dict[str, float | str]] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    overflow_count: int = 0

    def add_box(self, box: LayoutBox) -> None:
        box.validate()
        self.elements.append(box.as_dict())
        if box.left < self.safe_left - TOLERANCE:
            self.violations.append(f"{box.name} crosses the safe left boundary")
            self.overflow_count += 1
        if box.right > self.safe_right + TOLERANCE:
            self.violations.append(f"{box.name} crosses the safe right boundary")
            self.overflow_count += 1
        if box.top > self.safe_top + TOLERANCE:
            self.violations.append(f"{box.name} crosses the safe upper boundary")
            self.overflow_count += 1
        if box.bottom < self.safe_bottom - TOLERANCE:
            self.violations.append(f"{box.name} crosses the safe lower boundary")
            self.overflow_count += 1

    def add_card(self, name: str, page: int, geometry: CardGeometry) -> None:
        self.frames.append(
            {
                "name": name,
                "page": float(page),
                "left": geometry.outer_x,
                "right": geometry.outer_right,
                "top": geometry.outer_top,
                "bottom": geometry.outer_bottom,
            }
        )
        self.add_box(
            LayoutBox(
                name=name,
                page=page,
                kind="card",
                left=geometry.outer_x,
                right=geometry.outer_right,
                top=geometry.outer_top,
                bottom=geometry.outer_bottom,
            )
        )
        visible_left = geometry.path_x - (geometry.stroke_width / 2)
        visible_right = geometry.path_x + geometry.path_width + (geometry.stroke_width / 2)
        if visible_left < geometry.outer_x - TOLERANCE or visible_right > geometry.outer_right + TOLERANCE:
            self.violations.append(f"{name} stroke exceeds its allocated frame")
            self.overflow_count += 1
        if abs(geometry.label_to_divider_gap - geometry.divider_to_body_gap) > TOLERANCE:
            self.violations.append(f"{name} has inconsistent text-to-graphic spacing")

    def add_vertical_gap(self, name: str, upper_bottom: float, lower_top: float, expected: float) -> None:
        actual = upper_bottom - lower_top
        self.gaps.append({"name": name, "actual": actual, "expected": expected})
        if abs(actual - expected) > TOLERANCE:
            self.violations.append(f"{name} gap is {actual:.2f}pt instead of {expected:.2f}pt")

    def add_edge_alignment(self, name: str, actual: float, expected: float) -> None:
        self.alignments.append({"name": name, "actual": actual, "expected": expected})
        if abs(actual - expected) > TOLERANCE:
            self.violations.append(f"{name} is misaligned by {actual - expected:.2f}pt")

    def report(self) -> dict[str, Any]:
        return {
            "spacing_unit_pt": self.spacing_unit,
            "frames": self.frames,
            "elements": self.elements,
            "gaps": self.gaps,
            "alignments": self.alignments,
            "violations": self.violations,
            "overflow_count": self.overflow_count,
        }
