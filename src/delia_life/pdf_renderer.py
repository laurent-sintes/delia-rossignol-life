"""Build the public, two-page standard CV from validated knowledge only."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas

from .cv_model import CVExperience, CVViewModel
from .errors import ValidationError

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


def line_wrap(text: str, font: str, size: float, width: float) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [text]:
        line = ""
        for word in paragraph.split():
            candidate = f"{line} {word}".strip()
            if line and stringWidth(candidate, font, size) > width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
    return lines


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
    pdf.setFillColor(color)
    pdf.setFont(font, size)
    for line in line_wrap(text, font, size, width):
        pdf.drawString(x, y, line)
        y -= leading
    return y


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


def draw_experience(
    pdf: canvas.Canvas,
    item: CVExperience,
    y: float,
    width: float,
) -> float:
    top_y = y + 14
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.8)
    pdf.drawString(LEFT + 11, y + 9, item.period.upper())
    y -= 8
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10.4)
    for line in line_wrap(item.heading, "Helvetica-Bold", 10.4, width - 11):
        pdf.drawString(LEFT + 11, y + 4, line)
        y -= 13.5
    y = draw_wrapped(pdf, item.mission, LEFT + 11, y - 3, width - 11, "Helvetica", 9.1, 14.0, INK)
    bullets = item.responsibilities[: item.bullet_limit]
    for bullet in bullets:
        pdf.setFillColor(CHAMPAGNE)
        pdf.circle(LEFT + 15, y + 2.6, 1.4, fill=1, stroke=0)
        y = draw_wrapped(pdf, bullet, LEFT + 23, y, width - 23, "Helvetica", 8.5, 13.0, MUTED)
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, y + 3, 3, max(28, top_y - y - 3), 1.5, fill=1, stroke=0)
    return y - 24


def draw_photo(pdf: canvas.Canvas, photo: Path) -> None:
    with Image.open(photo) as original:
        image = original.convert("RGB")
        ratio = image.width / image.height
        target_ratio = 1.0
        if ratio > target_ratio:
            crop = int(image.height * target_ratio)
            left = (image.width - crop) // 2
            image = image.crop((left, 0, left + crop, image.height))
        else:
            crop = int(image.width / target_ratio)
            top = int(image.height * 0.04)
            image = image.crop((0, top, image.width, min(image.height, top + crop)))
        encoded = BytesIO()
        image.save(encoded, "JPEG", quality=95)
        encoded.seek(0)
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


def render_standard_cv(view: CVViewModel, output: Path) -> dict[str, float]:
    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=A4, pageCompression=1, invariant=1)
    pdf.setTitle("CV - Délia Rossignol")
    pdf.setAuthor("Délia Rossignol")
    pdf.setSubject("CV standard - Signature éditoriale")

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
    for experience in view.recent_experiences:
        y = draw_experience(pdf, experience, y, CONTENT_WIDTH)
        minimum_y = min(minimum_y, y)
    if y < 45:
        raise ValidationError(f"Recent experiences overflow page 1 at y={y:.1f}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "CV standard · Signature éditoriale · 1 / 2")
    pdf.showPage()

    y = header(pdf, view.name, view.email, view.phone, view.tagline, view.photo, page=2)
    y = section_title(pdf, "Expériences complémentaires", y)
    for experience in view.complementary_experiences:
        y = draw_experience(pdf, experience, y, CONTENT_WIDTH)
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
    if y < 40:
        raise ValidationError(f"Education and languages overflow page 2 at y={y:.1f}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "CV standard · Signature éditoriale · 2 / 2")
    pdf.save()
    return {"minimum_y": minimum_y}
