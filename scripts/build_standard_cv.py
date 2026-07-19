"""Build the public, two-page standard CV from validated knowledge only."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image
from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader


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


def load_json(root: Path, relative_path: str) -> dict[str, Any]:
    return json.loads((root / relative_path).read_text(encoding="utf-8"))


def value(document: dict[str, Any], path: str) -> Any:
    current: Any = document["fields"]
    for part in path.split("."):
        current = current[part]
        if isinstance(current, dict) and "value" in current:
            current = current["value"]
    return current


def french_date(raw: str) -> str:
    parts = raw.split("-")
    if len(parts) == 1:
        return parts[0]
    return f"{parts[1]}/{parts[0]}"


def line_wrap(text: str, font: str, size: float, width: float) -> list[str]:
    words = text.split()
    lines: list[str] = []
    line = ""
    for word in words:
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
    return y - 29


def signature_quote(pdf: canvas.Canvas, text: str, y: float) -> float:
    lines = line_wrap(text, "Times-Italic", 12.2, CONTENT_WIDTH - 24)
    block_height = max(31, len(lines) * 15 + 12)
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, y - block_height + 8, 3, block_height, 1.5, fill=1, stroke=0)
    pdf.setFillColor(NAVY)
    pdf.setFont("Times-Italic", 12.2)
    line_y = y
    for line in lines:
        pdf.drawString(LEFT + 18, line_y, line)
        line_y -= 15
    return y - block_height - 4


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
    item: dict[str, Any],
    y: float,
    width: float,
    bullet_limit: int,
) -> float:
    top_y = y + 14
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica-Bold", 7.8)
    pdf.drawString(LEFT + 11, y + 9, item["period"].upper())
    y -= 8
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 10.4)
    for line in line_wrap(item["heading"], "Helvetica-Bold", 10.4, width - 11):
        pdf.drawString(LEFT + 11, y + 4, line)
        y -= 12.5
    y = draw_wrapped(pdf, item["mission"], LEFT + 11, y - 2, width - 11, "Helvetica", 9.1, 13.0, INK)
    bullets = item.get("responsibilities", [])[:bullet_limit]
    for bullet in bullets:
        pdf.setFillColor(CHAMPAGNE)
        pdf.circle(LEFT + 15, y + 2.6, 1.4, fill=1, stroke=0)
        y = draw_wrapped(pdf, bullet, LEFT + 23, y, width - 23, "Helvetica", 8.5, 12.2, MUTED)
    pdf.setFillColor(CHAMPAGNE)
    pdf.roundRect(LEFT, y + 3, 3, max(28, top_y - y - 3), 1.5, fill=1, stroke=0)
    return y - 16


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
        temporary = photo.with_suffix(".cv-photo.jpg")
        image.save(temporary, "JPEG", quality=95)
    try:
        centre_x, centre_y, radius = 522, 778, 46
        pdf.saveState()
        circle = pdf.beginPath()
        circle.circle(centre_x, centre_y, radius)
        pdf.clipPath(circle, stroke=0, fill=0)
        pdf.drawImage(ImageReader(str(temporary)), centre_x - radius, centre_y - radius, radius * 2, radius * 2)
        pdf.restoreState()
        pdf.setStrokeColor(CHAMPAGNE)
        pdf.setLineWidth(2)
        pdf.circle(centre_x, centre_y, radius, fill=0, stroke=1)
    finally:
        temporary.unlink(missing_ok=True)


def header(pdf: canvas.Canvas, name: str, email: str, phone: str, photo: Path, page: int) -> float:
    pdf.setFillColor(NAVY_DEEP)
    pdf.rect(0, PAGE_HEIGHT - 113, PAGE_WIDTH, 113, fill=1, stroke=0)
    pdf.setFillColor(CHAMPAGNE)
    pdf.rect(0, PAGE_HEIGHT - 113, PAGE_WIDTH, 4, fill=1, stroke=0)
    pdf.setFillColor(PAPER)
    pdf.setFont("Times-Bold", 24 if page == 1 else 18)
    pdf.drawString(LEFT, PAGE_HEIGHT - 58, name.upper())
    pdf.setFont("Helvetica-Bold", 8.4)
    pdf.setFillColor(CHAMPAGNE)
    pdf.drawString(LEFT, PAGE_HEIGHT - 77, "CONSEIL  •  COMMERCE  •  GESTION DE PROJET")
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


def read_experiences(root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    paths = {
        "bleu": "data/knowledge/entities/experience/bleu-rossignol-founder.json",
        "raison": "data/knowledge/entities/experience/raison-home-franchisee.json",
        "cuisinella": "data/knowledge/entities/experience/cuisinella-sainte-eulalie.json",
        "promod": "data/knowledge/entities/experience/promod-bordeaux.json",
        "era": "data/knowledge/entities/experience/era-entre-deux-mers.json",
        "maison": "data/knowledge/entities/experience/restaurant-la-maison.json",
        "manoir": "data/knowledge/entities/experience/restaurant-le-manoir.json",
        "sergio": "data/knowledge/entities/experience/sergio-rossi-paris.json",
        "loreal": "data/knowledge/entities/experience/loreal-luxury-products.json",
        "prada": "data/knowledge/entities/experience/prada-paris.json",
    }
    documents = {key: load_json(root, path) for key, path in paths.items()}
    records["bleu"] = {
        "period": "01/2024 - 07/2026",
        "heading": "Fondatrice & conceptrice-agenceuse · BLEU ROSSIGNOL",
        "mission": value(documents["bleu"], "mission"),
        "responsibilities": value(documents["bleu"], "responsibilities"),
    }
    records["raison"] = {
        "period": "08/2020 - 12/2023",
        "heading": "Franchisée · Raison Home",
        "mission": value(documents["raison"], "mission"),
        "responsibilities": value(documents["raison"], "responsibilities"),
    }
    records["cuisinella"] = {
        "period": "03/2019 - 07/2020",
        "heading": "Concepteur-vendeur · Cuisinella Sainte-Eulalie",
        "mission": value(documents["cuisinella"], "mission"),
        "responsibilities": value(documents["cuisinella"], "responsibilities"),
    }
    records["promod"] = {
        "period": "06/2018 - 02/2019",
        "heading": "Responsable adjointe de magasin · Promod, Bordeaux",
        "mission": value(documents["promod"], "mission"),
        "responsibilities": value(documents["promod"], "responsibilities"),
    }
    records["era"] = {
        "period": "01/2018 - 05/2018",
        "heading": "Agent immobilier · ERA Entre Deux Mers",
        "mission": value(documents["era"], "mission"),
        "responsibilities": value(documents["era"], "responsibilities"),
    }
    records["maison"] = {
        "period": "11/2012 - 12/2018",
        "heading": "Associée-propriétaire · La Maison, Bordeaux",
        "mission": value(documents["maison"], "mission"),
        "responsibilities": value(documents["maison"], "details.responsibilities"),
    }
    records["manoir"] = {
        "period": "10/2008 - 09/2012",
        "heading": "Location-gérance · Le Manoir, Paris",
        "mission": value(documents["manoir"], "mission"),
        "responsibilities": value(documents["manoir"], "responsibilities"),
    }
    records["sergio"] = {
        "period": "11/2006 - 09/2008",
        "heading": "Première vendeuse puis responsable de corner · SERGIO ROSSI",
        "mission": value(documents["sergio"], "mission"),
        "responsibilities": value(documents["sergio"], "details.responsibilities"),
    }
    records["loreal"] = {
        "period": "2004 - 2006",
        "heading": "Assistante décor · L'Oréal",
        "mission": value(documents["loreal"], "mission"),
        "responsibilities": value(documents["loreal"], "responsibilities"),
    }
    records["prada"] = {
        "period": "2003 - 2004",
        "heading": "Vente au détail · Prada, Paris",
        "mission": value(documents["prada"], "mission"),
        "responsibilities": value(documents["prada"], "responsibilities"),
    }
    return records


def build(root: Path, output: Path) -> None:
    person = load_json(root, "data/knowledge/entities/person/delia-rossignol.json")
    style = load_json(root, "data/style/delia.json")
    contact = load_json(root, "data/knowledge/entities/contact-point/delia-application-email.json")
    phone_contact = load_json(root, "data/knowledge/entities/contact-point/delia-personal-phone.json")
    english = load_json(root, "data/knowledge/entities/language-proficiency/delia-english.json")
    credential = load_json(root, "data/knowledge/entities/credential/esgci-marketing-commerce-2003.json")
    home_design = load_json(root, "data/knowledge/entities/education/raison-home-design-2020.json")
    birkbeck = load_json(root, "data/knowledge/entities/education/birkbeck-semester-2002.json")
    experiences = read_experiences(root)
    name = value(person, "professional_name")
    email = value(contact, "details")['value']
    phone = value(phone_contact, "details")['value']
    strengths = value(person, "signature_strengths")
    profile_signature = next(
        item["text"]
        for item in style["profile_signatures"]
        if item["status"] == "validated" and "cv-standard" in item["uses"]
    )
    english_details = value(english, "details")
    credential_details = value(credential, "details")
    home_design_details = value(home_design, "details")
    birkbeck_details = value(birkbeck, "details")
    photo = root / "site/assets/delia-rossignol.avif"

    output.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(output), pagesize=A4, pageCompression=1)
    pdf.setTitle("CV - Délia Rossignol")
    pdf.setAuthor("Délia Rossignol")
    pdf.setSubject("CV standard - Signature éditoriale")

    y = header(pdf, name, email, phone, photo, page=1)
    y = section_title(pdf, "Profil", y)
    y = signature_quote(pdf, profile_signature, y)
    profile = (
        "Expérience en conseil, commerce, gestion d'activité et conduite de projets sur mesure. "
        "Parcours associant entrepreneuriat, management d'équipe et relation client."
    )
    y = draw_wrapped(pdf, profile, LEFT, y, CONTENT_WIDTH, "Helvetica", 9.4, 13.5, INK) - 13
    y = section_title(pdf, "Compétences clés", y)
    x = LEFT
    for label in [
        "Conseil client", "Vente & négociation", "Agencement sur mesure", "Gestion de projet",
        "Management d'équipe", "Gestion d'activité", "Conception 3D", "Anglais courant",
        *strengths,
    ]:
        x, y = pill(pdf, label, x, y, RIGHT)
    y -= 19
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.2)
    pdf.drawString(LEFT, y, "Outils : Winner, Gesteos, InSitu - niveau expert")
    y -= 21
    y = section_title(pdf, "Expériences récentes", y)
    for key, limit in [("bleu", 2), ("raison", 0), ("cuisinella", 1), ("promod", 1), ("era", 1)]:
        y = draw_experience(pdf, experiences[key], y, CONTENT_WIDTH, limit)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "CV standard · Signature éditoriale · 1 / 2")
    pdf.showPage()

    y = header(pdf, name, email, phone, photo, page=2)
    y = section_title(pdf, "Expériences complémentaires", y)
    for key, limit in [("maison", 1), ("manoir", 1), ("sergio", 0), ("loreal", 1), ("prada", 0)]:
        y = draw_experience(pdf, experiences[key], y, CONTENT_WIDTH, limit)
    y = section_title(pdf, "Formation", y)
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 9)
    pdf.drawString(LEFT, y, f"{credential_details['awarded_year']} · {credential_details['name']} · {credential_details['level']}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.5)
    pdf.drawString(LEFT, y - 12, credential_details["issuer"])
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 8.6)
    pdf.drawString(LEFT, y - 27, f"2020 · {home_design_details['program']}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.2)
    pdf.drawString(LEFT, y - 38, home_design_details["institution"])
    pdf.setFillColor(NAVY)
    pdf.setFont("Helvetica-Bold", 8.6)
    pdf.drawString(LEFT, y - 53, f"{birkbeck_details['year']} · {birkbeck_details['program_stage'].capitalize()}")
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 8.2)
    pdf.drawString(LEFT, y - 64, birkbeck_details["institution"])
    y -= 84
    y = section_title(pdf, "Langues & centres d'intérêt", y)
    language = (
        f"Anglais · oral et lecture : {english_details['speaking_level']} · "
        f"écrit : {english_details['writing_level']} · Chant · Voyages"
    )
    draw_wrapped(pdf, language, LEFT, y, CONTENT_WIDTH, "Helvetica", 8.6, 11.5, INK)
    pdf.setFillColor(MUTED)
    pdf.setFont("Helvetica", 7.4)
    pdf.drawRightString(RIGHT, 24, "CV standard · Signature éditoriale · 2 / 2")
    pdf.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="output/pdf/cv-delia-rossignol-signature.pdf")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = root / args.output
    build(root, output)
    public_asset = root / "site/assets/downloads/cv-delia-rossignol-signature.pdf"
    public_asset.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(output, public_asset)
    print(f"Built {output.relative_to(root)} and {public_asset.relative_to(root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
