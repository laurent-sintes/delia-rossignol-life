"""Build the public, two-page standard CV from validated knowledge only."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import getAscent, getDescent, stringWidth
from reportlab.pdfgen import canvas

from .cv_model import CVContinuityGroup, CVExperience, CVHighlight, CVSequenceStep, CVViewModel
from .errors import ValidationError
from .pdf_layout import CVLayoutRules, LayoutAudit, LayoutBox, calculate_card_geometry

NAVY = HexColor("#0d2f5a")
NAVY_DEEP = HexColor("#092442")
INK = HexColor("#162a3e")
MUTED = HexColor("#66717d")
IVORY = HexColor("#f9f5f3")
PAPER = HexColor("#fffdfb")
CHAMPAGNE = HexColor("#d8b9a1")
CHAMPAGNE_SOFT = HexColor("#f0dfd2")

PAGE_WIDTH, PAGE_HEIGHT = A4
LEFT = 42
RIGHT = PAGE_WIDTH - 42
CONTENT_WIDTH = RIGHT - LEFT


@dataclass(frozen=True)
class RenderContext:
    pdf: canvas.Canvas
    rules: CVLayoutRules
    audit: LayoutAudit
    page: int


def _split_long_word(word: str, font: str, size: float, width: float) -> list[str]:
    chunks: list[str] = []
    chunk = ""
    for character in word:
        candidate = chunk + character
        if chunk and stringWidth(candidate, font, size) > width:
            chunks.append(chunk)
            chunk = character
        elif not chunk and stringWidth(character, font, size) > width:
            raise ValidationError(f"Character cannot fit in a {width:.1f}pt text area")
        else:
            chunk = candidate
    if chunk:
        chunks.append(chunk)
    return chunks


def line_wrap(text: str, font: str, size: float, width: float) -> list[str]:
    if width <= 0:
        raise ValidationError("Text area width must be positive")
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        line = ""
        for word in paragraph.split():
            if stringWidth(word, font, size) > width:
                if line:
                    lines.append(line)
                    line = ""
                chunks = _split_long_word(word, font, size, width)
                lines.extend(chunks[:-1])
                line = chunks[-1]
                continue
            candidate = f"{line} {word}".strip()
            if line and stringWidth(candidate, font, size) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
    return lines


@dataclass(frozen=True, slots=True)
class DrawnTextBlock:
    next_y: float
    top: float
    bottom: float


def draw_wrapped_block(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font: str = "Helvetica",
    size: float = 8.8,
    leading: float = 12.2,
    color: Any = INK,
) -> DrawnTextBlock:
    lines = line_wrap(text, font, size, width)
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    line_y = y
    for line in lines:
        pdf.drawString(x, line_y, line)
        line_y -= leading
    if not lines:
        return DrawnTextBlock(next_y=y, top=y, bottom=y)
    last_baseline = y - ((len(lines) - 1) * leading)
    return DrawnTextBlock(
        next_y=line_y,
        top=y + getAscent(font, size),
        bottom=last_baseline + getDescent(font, size),
    )


def draw_wrapped(
    pdf: canvas.Canvas,
    text: str,
    x: float,
    y: float,
    width: float,
    font: str = "Helvetica",
    size: float = 8.8,
    leading: float = 12.2,
    color: Any = INK,
) -> float:
    return draw_wrapped_block(pdf, text, x, y, width, font, size, leading, color).next_y


def section_title(pdf: canvas.Canvas, title: str, y: float) -> float:
    pdf.setStrokeColor(CHAMPAGNE)
    pdf.setLineWidth(1.3)
    pdf.line(LEFT, y + 4, LEFT + 26, y + 4)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 8.5)
    pdf.drawString(LEFT + 34, y, title.upper())
    return y - 33


def signature_quote(pdf: canvas.Canvas, text: str, y: float) -> float:
    font_size = 12.4
    line_height = 17
    lines = line_wrap(text, "Times-Italic", font_size, CONTENT_WIDTH - 28)
    bar_top = y + 5
    bar_bottom = y - ((len(lines) - 1) * line_height) - 5
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, bar_bottom, 3, bar_top - bar_bottom, 1.5, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Times-Italic", font_size)
    line_y = y
    for line in lines:
        pdf.drawString(LEFT + 18, line_y, line)
        line_y -= line_height
    return bar_bottom - 17


def pill(pdf: canvas.Canvas, label: str, x: float, y: float, maximum_x: float) -> tuple[float, float]:
    size = 7.2
    padding_x = 7
    width = stringWidth(label.upper(), "Helvetica-Bold", size) + (padding_x * 2)
    if x + width > maximum_x:
        x = LEFT
        y -= 19
    pdf.setFillColor(CHAMPAGNE_SOFT)
    pdf.roundRect(x, y - 10, width, 15, 7.5, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", size)
    pdf.drawCentredString(x + width / 2, y - 5.2, label.upper())
    return x + width + 5, y


def draw_responsibility_sequence(
    pdf: canvas.Canvas,
    steps: tuple[CVSequenceStep, ...],
    x: float,
    top: float,
    width: float,
    rules: CVLayoutRules,
    audit: LayoutAudit,
    page: int,
    name_prefix: str,
) -> float:
    gap = rules.component_gap_pt
    box_width = (width - (gap * (len(steps) - 1))) / len(steps)
    label_size = 7.0
    label_leading = 8.0
    body_size = 6.5
    body_leading = 8.0
    wrapped_steps = [
        line_wrap(", ".join(step.responsibilities), "Helvetica", body_size, box_width - (rules.card_padding_pt * 2))
        for step in steps
    ]
    maximum_lines = max(len(lines) for lines in wrapped_steps)
    bottom = top

    for index, (step, lines) in enumerate(zip(steps, wrapped_steps, strict=True)):
        box_x = x + (index * (box_width + gap))
        geometry = calculate_card_geometry(
            x=box_x,
            top=top,
            width=box_width,
            line_count=maximum_lines,
            label_size=label_size,
            label_leading=label_leading,
            body_size=body_size,
            body_leading=body_leading,
            rules=rules,
            minimum_height=56.0,
        )
        audit.add_card(f"{name_prefix}:{step.label}", page, geometry)
        pdf.setFillColor(IVORY)
        pdf.setStrokeColor(CHAMPAGNE)
        pdf.setLineWidth(geometry.stroke_width)
        pdf.roundRect(
            geometry.path_x,
            geometry.path_bottom,
            geometry.path_width,
            geometry.path_height,
            4,
            fill=1,
            stroke=1,
        )
        pdf.setFillColor(NAVY)
        pdf.setFont("Helvetica-Bold", label_size)
        pdf.drawString(box_x + rules.card_padding_pt, geometry.label_baseline, step.label.upper())
        pdf.setStrokeColor(CHAMPAGNE)
        pdf.setLineWidth(0.6)
        pdf.line(
            box_x + rules.card_padding_pt,
            geometry.divider_y,
            box_x + box_width - rules.card_padding_pt,
            geometry.divider_y,
        )
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", body_size)
        for line, line_y in zip(lines, geometry.body_baselines, strict=False):
            pdf.drawString(box_x + rules.card_padding_pt, line_y, line)
        bottom = geometry.outer_bottom
    return bottom


def draw_highlight(
    pdf: canvas.Canvas,
    highlight: CVHighlight,
    x: float,
    top: float,
    width: float,
    rules: CVLayoutRules,
    audit: LayoutAudit,
    page: int,
) -> float:
    label_size = 7.0
    label_leading = 8.0
    body_size = 6.9
    body_leading = 8.0
    lines = line_wrap(", ".join(highlight.items), "Helvetica", body_size, width - 2 * rules.card_padding_pt)
    geometry = calculate_card_geometry(
        x=x,
        top=top,
        width=width,
        line_count=len(lines),
        label_size=label_size,
        label_leading=label_leading,
        body_size=body_size,
        body_leading=body_leading,
        rules=rules,
        minimum_height=40.0,
    )
    audit.add_card(f"highlight:{highlight.label}", page, geometry)

    pdf.setFillColor(IVORY)
    pdf.setStrokeColor(CHAMPAGNE_SOFT)
    pdf.setLineWidth(geometry.stroke_width)
    pdf.roundRect(
        geometry.path_x,
        geometry.path_bottom,
        geometry.path_width,
        geometry.path_height,
        4,
        fill=1,
        stroke=1,
    )

    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", label_size)
    pdf.drawString(x + rules.card_padding_pt, geometry.label_baseline, highlight.label.upper())
    pdf.setStrokeColor(CHAMPAGNE_SOFT)
    pdf.setLineWidth(0.5)
    pdf.line(
        x + rules.card_padding_pt,
        geometry.divider_y,
        x + width - rules.card_padding_pt,
        geometry.divider_y,
    )

    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", body_size)
    for line, line_y in zip(lines, geometry.body_baselines, strict=True):
        pdf.drawString(x + rules.card_padding_pt, line_y, line)
    return geometry.outer_bottom


def _draw_continuity_experience(
    context: RenderContext,
    experience: CVExperience,
    top: float,
    x: float,
    width: float,
) -> float:
    pdf = context.pdf
    rules = context.rules
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 9.8)
    company_baseline = top - getAscent("Helvetica-Bold", 9.8)
    pdf.drawString(x, company_baseline, experience.organization_name or experience.heading)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.4)
    pdf.drawRightString(RIGHT, company_baseline, experience.period.upper())
    content_top = company_baseline + getDescent("Helvetica-Bold", 9.8) - rules.text_gap_pt
    if experience.organization_tagline:
        pdf.setFillColor(CHAMPAGNE)
        pdf.setFont("Helvetica-Bold", 6.9)
        tagline_baseline = content_top - getAscent("Helvetica-Bold", 6.9)
        pdf.drawString(x, tagline_baseline, experience.organization_tagline.upper())
        content_top = tagline_baseline + getDescent("Helvetica-Bold", 6.9) - rules.text_gap_pt
    detail = experience.heading
    if experience.context_label:
        detail += f" · {experience.context_label}"
    pdf.setFillColor(INK)
    pdf.setFont("Helvetica", 8.1)
    detail_baseline = content_top - getAscent("Helvetica", 8.1)
    pdf.drawString(x, detail_baseline, detail)
    detail_bottom = detail_baseline + getDescent("Helvetica", 8.1)
    if not experience.highlight:
        return detail_bottom
    highlight_top = detail_bottom - rules.component_gap_pt
    context.audit.add_vertical_gap(
        f"{experience.entity_id}:text-to-highlight",
        detail_bottom,
        highlight_top,
        rules.component_gap_pt,
    )
    return draw_highlight(
        pdf,
        experience.highlight,
        x,
        highlight_top,
        width,
        rules,
        context.audit,
        context.page,
    )


def draw_continuity_group(context: RenderContext, group: CVContinuityGroup, y: float, width: float) -> float:
    pdf = context.pdf
    rules = context.rules
    audit = context.audit
    content_x = LEFT + 11
    content_width = width - 11
    child_x = content_x + 12
    child_width = content_width - 12
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 11.2)
    group_baseline = y + 8
    group_top = group_baseline + getAscent("Helvetica-Bold", 11.2)
    pdf.drawString(content_x, group_baseline, group.label.upper())
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.6)
    pdf.drawRightString(RIGHT, group_baseline, group.period.upper())
    group_bottom = group_baseline + getDescent("Helvetica-Bold", 11.2)
    context_top = group_bottom - rules.text_gap_pt
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Oblique", 7.5)
    context_baseline = context_top - getAscent("Helvetica-Oblique", 7.5)
    pdf.drawString(content_x, context_baseline, group.context_label)
    context_bottom = context_baseline + getDescent("Helvetica-Oblique", 7.5)
    company_top = context_bottom - rules.component_gap_pt
    socle_top = company_top

    for index, experience in enumerate(group.experiences):
        experience_bottom = _draw_continuity_experience(context, experience, company_top, child_x, child_width)

        if index + 1 < len(group.experiences):
            next_company_top = experience_bottom - rules.component_gap_pt
            audit.add_vertical_gap(
                f"{experience.entity_id}:to-next-experience",
                experience_bottom,
                next_company_top,
                rules.component_gap_pt,
            )
            company_top = next_company_top
        else:
            socle_top = experience_bottom - rules.component_gap_pt
            audit.add_vertical_gap(
                f"{experience.entity_id}:to-common-foundation",
                experience_bottom,
                socle_top,
                rules.component_gap_pt,
            )

    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 6.8)
    socle_baseline = socle_top - getAscent("Helvetica-Bold", 6.8)
    pdf.drawString(child_x, socle_baseline, "SOCLE MÉTIER COMMUN")
    socle_bottom = socle_baseline + getDescent("Helvetica-Bold", 6.8)
    cards_top = socle_bottom - rules.component_gap_pt
    audit.add_vertical_gap("common-foundation:text-to-cards", socle_bottom, cards_top, rules.component_gap_pt)
    y = draw_responsibility_sequence(
        pdf,
        group.responsibility_sequence,
        child_x,
        cards_top,
        child_width,
        rules,
        audit,
        context.page,
        "common-foundation",
    )
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, y, 3, group_top - y, 1.5, fill=1, stroke=0)
    audit.add_box(
        LayoutBox(
            name=f"{group.group_id}:content",
            page=context.page,
            kind="content-group",
            left=content_x,
            right=RIGHT,
            top=group_top,
            bottom=y,
        )
    )
    audit.add_box(
        LayoutBox(
            name=f"{group.group_id}:bar",
            page=context.page,
            kind="vertical-bar",
            left=LEFT,
            right=LEFT + 3,
            top=group_top,
            bottom=y,
        )
    )
    audit.add_edge_alignment(f"{group.group_id}:bar-top", group_top, group_top)
    audit.add_edge_alignment(f"{group.group_id}:bar-bottom", y, y)
    return y


def draw_experience(
    context: RenderContext,
    item: CVExperience,
    y: float,
    width: float,
) -> float:
    pdf = context.pdf
    rules = context.rules
    audit = context.audit
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.8)
    date_baseline = y + 9
    content_top = date_baseline + getAscent("Helvetica-Bold", 7.8)
    pdf.drawString(LEFT + 11, date_baseline, item.period.upper())
    y -= 8
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10.4)
    for line in line_wrap(item.heading, "Helvetica-Bold", 10.4, width - 11):
        pdf.drawString(LEFT + 11, y + 4, line)
        y -= 13.5
    mission = draw_wrapped_block(pdf, item.mission, LEFT + 11, y - 3, width - 11, "Helvetica", 9.1, 14.0, INK)
    y = mission.next_y
    content_bottom = mission.bottom
    if item.responsibility_sequence:
        y = draw_responsibility_sequence(
            pdf,
            item.responsibility_sequence,
            LEFT + 11,
            y - rules.component_gap_pt,
            width - 11,
            rules,
            audit,
            context.page,
            f"experience:{item.entity_id}",
        )
        content_bottom = y
    bullets = item.responsibilities[: item.bullet_limit]
    for bullet in bullets:
        pdf.setFillColor(CHAMPAGNE)
        pdf.circle(LEFT + 15, y + 2.6, 1.4, fill=1, stroke=0)
        bullet_block = draw_wrapped_block(pdf, bullet, LEFT + 23, y, width - 23, "Helvetica", 8.5, 13.0, MUTED)
        y = bullet_block.next_y
        content_bottom = bullet_block.bottom
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, content_bottom, 3, content_top - content_bottom, 1.5, fill=1, stroke=0)
    audit.add_box(
        LayoutBox(
            name=f"{item.entity_id}:content",
            page=context.page,
            kind="experience",
            left=LEFT + 11,
            right=RIGHT,
            top=content_top,
            bottom=content_bottom,
        )
    )
    audit.add_box(
        LayoutBox(
            name=f"{item.entity_id}:bar",
            page=context.page,
            kind="vertical-bar",
            left=LEFT,
            right=LEFT + 3,
            top=content_top,
            bottom=content_bottom,
        )
    )
    audit.add_edge_alignment(f"{item.entity_id}:bar-top", content_top, content_top)
    audit.add_edge_alignment(f"{item.entity_id}:bar-bottom", content_bottom, content_bottom)
    return y - rules.experience_gap_pt


def composite_photo_background(image: Image.Image) -> Image.Image:
    """Composite a potentially transparent portrait on the CV's warm ivory."""
    foreground = image.convert("RGBA")
    background = Image.new("RGBA", foreground.size, "#f9f5f3")
    background.alpha_composite(foreground)
    return background.convert("RGB")


@lru_cache(maxsize=8)
def _prepared_photo_jpeg(photo_path: str, modified_ns: int) -> bytes:
    del modified_ns  # Included in the cache key to invalidate changed source files.
    with Image.open(photo_path) as original:
        image = original.convert("RGBA")
        ratio = image.width / image.height
        target_ratio = 1.0
        if ratio > target_ratio:
            crop = int(image.height * target_ratio)
            left = (image.width - crop) // 2
            image = image.crop((left, 0, left + crop, image.height))
        else:
            crop = int(image.width / target_ratio)
            top = min(int(image.height * 0.04), image.height - crop)
            image = image.crop((0, top, image.width, top + crop))
        image = composite_photo_background(image)
        if image.width > 256:
            image = image.resize((256, 256), Image.Resampling.LANCZOS)
        encoded = BytesIO()
        image.save(encoded, "JPEG", quality=95)
        return encoded.getvalue()


def draw_photo(pdf: canvas.Canvas, photo: Path) -> None:
    encoded = BytesIO(_prepared_photo_jpeg(str(photo.resolve()), photo.stat().st_mtime_ns))
    centre_x, centre_y, radius = 522, 778, 46
    pdf.saveState()
    circle = pdf.beginPath()
    circle.circle(centre_x, centre_y, radius)
    pdf.clipPath(circle, stroke=0, fill=0)
    pdf.drawImage(ImageReader(encoded), centre_x - radius, centre_y - radius, radius * 2, radius * 2)
    pdf.restoreState()
    pdf.setStrokeColor(CHAMPAGNE)
    pdf.setLineWidth(2)
    pdf.circle(centre_x, centre_y, radius, fill=0, stroke=1)


def header(pdf: canvas.Canvas, name: str, email: str, phone: str, tagline: str, photo: Path, page: int) -> float:
    pdf.setFillColor(NAVY_DEEP)
    pdf.rect(0, PAGE_HEIGHT - 113, PAGE_WIDTH, 113, fill=1, stroke=0)
    pdf.setFillColor(CHAMPAGNE)
    pdf.rect(0, PAGE_HEIGHT - 113, PAGE_WIDTH, 4, fill=1, stroke=0)
    pdf.setFillColor(PAPER)
    pdf.setFont("Times-Bold", 24 if page == 1 else 18)
    pdf.drawString(LEFT, PAGE_HEIGHT - 58, name.upper())
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.setFillColor(CHAMPAGNE)
    pdf.drawString(LEFT, PAGE_HEIGHT - 77, tagline.upper().replace("·", " • "))
    if page == 1:
        pdf.setFillColor(PAPER)
        pdf.setFont("Helvetica", 8.2)
        pdf.drawString(LEFT, PAGE_HEIGHT - 95, f"{email}  ·  {phone}")
    if page == 1:
        draw_photo(pdf, photo)
    else:
        pdf.setFillColor(PAPER)
        pdf.setFont("Helvetica", 8)
        pdf.drawRightString(RIGHT, PAGE_HEIGHT - 74, "PARCOURS PROFESSIONNEL")
    return PAGE_HEIGHT - 140


def _render_first_page(view: CVViewModel, context: RenderContext) -> float:
    pdf = context.pdf
    rules = context.rules
    minimum_y = PAGE_HEIGHT
    y = header(pdf, view.name, view.email, view.phone, view.tagline, view.photo, page=1)
    y = section_title(pdf, "Profil", y)
    y = signature_quote(pdf, view.signature, y)
    y = draw_wrapped(pdf, view.profile_summary, LEFT, y, CONTENT_WIDTH, "Helvetica", 9.4, 14.2, INK) - 18
    y = section_title(pdf, "Compétences clés", y)
    x: float = LEFT
    for label in view.key_skills:
        x, y = pill(pdf, label, x, y, RIGHT)
    y -= 22
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.2)
    pdf.drawString(LEFT, y, view.tools_line)
    y -= 27
    y = section_title(pdf, "Expériences récentes", y)
    for index, group in enumerate(view.recent_continuity_groups):
        group_bottom = draw_continuity_group(context, group, y, CONTENT_WIDTH)
        minimum_y = min(minimum_y, group_bottom)
        next_top = group_bottom - rules.component_gap_pt
        if index + 1 < len(view.recent_continuity_groups):
            context.audit.add_vertical_gap(
                f"{group.group_id}:to-next-continuity-group",
                group_bottom,
                next_top,
                rules.component_gap_pt,
            )
            y = next_top - getAscent("Helvetica-Bold", 11.2) - 8
        elif view.recent_experiences:
            context.audit.add_vertical_gap(
                f"{group.group_id}:to-next-experience",
                group_bottom,
                next_top,
                rules.component_gap_pt,
            )
            y = next_top - getAscent("Helvetica-Bold", 7.8) - 9
        else:
            y = group_bottom
    for experience in view.recent_experiences:
        y = draw_experience(context, experience, y, CONTENT_WIDTH)
        minimum_y = min(minimum_y, y)
    if y < rules.safe_bottom_pt:
        raise ValidationError(f"Recent experiences overflow page 1 at y={y:.1f}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "1 / 2")
    pdf.showPage()
    return minimum_y


def _render_second_page(view: CVViewModel, context: RenderContext) -> float:
    pdf = context.pdf
    rules = context.rules
    minimum_y = PAGE_HEIGHT
    y = header(pdf, view.name, view.email, view.phone, view.tagline, view.photo, page=2)
    y = section_title(pdf, "Expériences complémentaires", y)
    for experience in view.complementary_experiences:
        y = draw_experience(context, experience, y, CONTENT_WIDTH)
        minimum_y = min(minimum_y, y)
    y = section_title(pdf, "Formation", y)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 9)
    for education in view.education:
        pdf.setFillColor(NAVY)
        pdf.setFont("Helvetica-Bold", 8.8)
        pdf.drawString(LEFT, y, education.primary)
        pdf.setFillColor(MUTED)
        pdf.setFont("Helvetica", 8.3)
        pdf.drawString(LEFT, y - 12, education.secondary)
        y -= 33
    y -= 6
    y = section_title(pdf, "Langues & centres d'intérêt", y)
    y = draw_wrapped(pdf, view.language_and_interests, LEFT, y, CONTENT_WIDTH, "Helvetica", 8.6, 11.5, INK)
    minimum_y = min(minimum_y, y)
    if y < rules.safe_bottom_pt:
        raise ValidationError(f"Education and languages overflow page 2 at y={y:.1f}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "2 / 2")
    return minimum_y


def _render_standard_cv(view: CVViewModel, output: Path) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=A4, pageCompression=1, invariant=1)
    pdf.setTitle("CV - Délia Rossignol")
    pdf.setAuthor("Délia Rossignol")
    pdf.setSubject("CV standard - Signature éditoriale")

    rules = view.layout_rules
    audit = LayoutAudit(
        safe_left=LEFT,
        safe_right=RIGHT,
        safe_top=PAGE_HEIGHT,
        safe_bottom=rules.safe_bottom_pt,
        spacing_unit=rules.spacing_unit_pt,
    )
    minimum_y = min(
        _render_first_page(view, RenderContext(pdf=pdf, rules=rules, audit=audit, page=1)),
        _render_second_page(view, RenderContext(pdf=pdf, rules=rules, audit=audit, page=2)),
    )
    audit_report = audit.report()
    if audit_report["violations"]:
        raise ValidationError("PDF layout audit failed: " + "; ".join(audit_report["violations"]))
    pdf.save()
    return {"minimum_y": minimum_y, "audit": audit_report}


def render_standard_cv(view: CVViewModel, output: Path) -> dict[str, Any]:
    """Render and atomically replace the requested PDF only after layout validation."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        result = _render_standard_cv(view, temporary)
        os.replace(temporary, output)
        return result
    finally:
        temporary.unlink(missing_ok=True)
