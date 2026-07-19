from __future__ import annotations

import html
import json
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Any

from .core import sha256_file
from .storage import atomic_write_bytes_group

MAX_OFFERS_PER_EMAIL = 50


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _compensation_label(offer: dict[str, Any]) -> str:
    compensation = offer.get("compensation")
    if not isinstance(compensation, dict):
        return "non communiquée"
    minimum = compensation.get("minimum")
    maximum = compensation.get("maximum")
    if not isinstance(minimum, (int, float)) and not isinstance(maximum, (int, float)):
        return "non communiquée"
    currency = _text(compensation.get("currency")) or "EUR"
    currency_label = "€" if currency == "EUR" else currency
    period_labels = {"year": "brut/an", "month": "brut/mois", "hour": "brut/heure"}
    period = period_labels.get(_text(compensation.get("period")), "brut")

    def amount(value: int | float) -> str:
        return f"{value:,.0f}".replace(",", "\u202f")

    if isinstance(minimum, (int, float)) and isinstance(maximum, (int, float)):
        return f"{amount(minimum)} – {amount(maximum)} {currency_label} {period}"
    if isinstance(minimum, (int, float)):
        return f"à partir de {amount(minimum)} {currency_label} {period}"
    if isinstance(maximum, (int, float)):
        return f"jusqu’à {amount(maximum)} {currency_label} {period}"
    return "non communiquée"


def _relevance_label(assessment: dict[str, Any]) -> str:
    score = assessment.get("score")
    if not isinstance(score, (int, float)):
        return "non calculée"
    if float(score).is_integer():
        return f"{int(score)}/100"
    return f"{score:.1f}".replace(".", ",") + "/100"


def _offer_lines(offer: dict[str, Any]) -> tuple[str, str]:
    assessment = offer.get("assessment", {}) if isinstance(offer.get("assessment"), dict) else {}
    reasons = assessment.get("reasons", []) if isinstance(assessment.get("reasons"), list) else []
    reasons_text = "; ".join(_text(reason) for reason in reasons[:3] if _text(reason)) or "à examiner ensemble"
    title = _text(offer.get("title")) or "Offre sans intitulé"
    employer = _text(offer.get("employer")) or "employeur non précisé"
    contract = _text(offer.get("contract_type")) or "contrat à confirmer"
    location = _text(offer.get("location_label")) or "lieu à confirmer"
    link = _text(offer.get("source_url"))
    sectors = offer.get("sector_labels")
    sector = " / ".join(_text(label) for label in sectors if _text(label)) if isinstance(sectors, list) else ""
    sector = sector or "à confirmer"
    compensation = _compensation_label(offer)
    relevance = _relevance_label(assessment)
    gaps = assessment.get("gaps", []) if isinstance(assessment.get("gaps"), list) else []
    unknowns = assessment.get("unknowns", []) if isinstance(assessment.get("unknowns"), list) else []
    vigilance_items = [_text(item) for item in [*gaps, *unknowns] if _text(item)]
    if compensation != "non communiquée":
        vigilance_items = [item for item in vigilance_items if item != "rémunération non précisée"]
    if offer.get("full_time") is True:
        vigilance_items = [item for item in vigilance_items if item != "temps plein à confirmer"]
    if offer.get("conditions", {}).get("insurance_experience_required") is True:
        vigilance_items.insert(0, "expérience assurantielle demandée")
    vigilance = "; ".join(dict.fromkeys(vigilance_items)) or "aucun point bloquant identifié dans l’annonce"
    text_line = (
        f"Secteur d’activité : {sector}\n"
        f"Mission / poste : {title} — {employer}\n"
        f"Salaire proposé : {compensation}\n"
        f"Pertinence : {relevance}\n"
        f"Contrat et lieu : {contract}, {location}\n"
        f"{link}\nPourquoi : {reasons_text}\nPoint de vigilance : {vigilance}"
    )
    html_line = (
        f"<strong>Secteur d’activité :</strong> {html.escape(sector)}<br>"
        f"<strong>Mission / poste :</strong> {html.escape(title)} — {html.escape(employer)}<br>"
        f"<strong>Salaire proposé :</strong> {html.escape(compensation)}<br>"
        f"<strong>Pertinence :</strong> {html.escape(relevance)}<br>"
        f"<strong>Contrat et lieu :</strong> {html.escape(contract)}, {html.escape(location)}<br>"
        f'<a href="{html.escape(link, quote=True)}">Voir l’annonce</a><br>'
        f"Pourquoi : {html.escape(reasons_text)}<br>"
        f'<span style="color: #b85c20;"><strong>Point de vigilance :</strong> {html.escape(vigilance)}</span>'
    )
    return text_line, html_line


def _validate_recipient(recipient: str) -> str:
    value = recipient.strip()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("A valid recipient email address is required")
    return value


def _offer_relevance_key(offer: dict[str, Any]) -> tuple[float, int, str]:
    assessment = offer.get("assessment")
    score = assessment.get("score") if isinstance(assessment, dict) else 0
    numeric_score = float(score) if isinstance(score, (int, float)) else 0.0
    rank = offer.get("rank")
    numeric_rank = rank if isinstance(rank, int) else 2**31 - 1
    return (-numeric_score, numeric_rank, _text(offer.get("id")))


def prepare_offer_feedback_email(
    report: dict[str, Any],
    recipient: str,
    site_url: str,
    cv_pdf: Path,
    output_dir: Path,
    limit: int = MAX_OFFERS_PER_EMAIL,
    offer_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Render a review email package without contacting a mail service."""
    recipient = _validate_recipient(recipient)
    normalized_site_url = site_url.strip()
    if not normalized_site_url.startswith(("https://", "http://")):
        raise ValueError("site_url must be an absolute HTTP(S) URL")
    if not cv_pdf.is_file() or cv_pdf.suffix.casefold() != ".pdf":
        raise ValueError("cv_pdf must be an existing PDF file")
    offers = report.get("offers")
    if not isinstance(offers, list) or not offers:
        raise ValueError("report must contain at least one ranked offer")
    usable_offers = [offer for offer in offers if isinstance(offer, dict)]
    if not 1 <= limit <= MAX_OFFERS_PER_EMAIL:
        raise ValueError(f"limit must be between 1 and {MAX_OFFERS_PER_EMAIL}")
    if offer_ids:
        if len(offer_ids) > MAX_OFFERS_PER_EMAIL:
            raise ValueError(f"at most {MAX_OFFERS_PER_EMAIL} offers can be included in one email")
        offers_by_id = {_text(offer.get("id")): offer for offer in usable_offers}
        missing = [identifier for identifier in offer_ids if identifier not in offers_by_id]
        if missing:
            raise ValueError("report does not contain selected offer ids: " + ", ".join(missing))
        selected = [offers_by_id[identifier] for identifier in offer_ids]
    else:
        selected = sorted(usable_offers, key=_offer_relevance_key)[:limit]
    if not selected:
        raise ValueError("report does not contain usable offers")

    text_offers, html_offers = zip(*(_offer_lines(offer) for offer in selected), strict=True)
    subject = f"Sélection de {len(selected)} offres — ton avis"
    feedback_prompt = "Réponds simplement avec le numéro, 👍 / 🤔 / 👎 et une courte raison."
    text_body = "\n\n".join(
        [
            "Bonjour Délia,",
            "Voici une sélection d’offres préparée pour toi. Le classement est une aide à la décision : ton regard reste déterminant.",
            "Tu peux retrouver ton dossier professionnel ici : " + normalized_site_url,
            "Ton CV actuel est joint à ce message.",
            feedback_prompt,
            "\n\n".join(f"{index}. {line}" for index, line in enumerate(text_offers, start=1)),
            "À bientôt,",
        ]
    )
    html_body = "<html><body>" + "".join(
        [
            "<p>Bonjour Délia,</p>",
            "<p>Voici une sélection d’offres préparée pour toi. Le classement est une aide à la décision : ton regard reste déterminant.</p>",
            f'<p>Tu peux retrouver ton dossier professionnel ici : <a href="{html.escape(normalized_site_url, quote=True)}">{html.escape(normalized_site_url)}</a>.</p>',
            "<p>Ton CV actuel est joint à ce message.</p>",
            f"<p>{html.escape(feedback_prompt)}</p><ol>",
            # Gmail supports list-item margins: the gap makes each opportunity
            # readable without turning the email into a set of heavy cards.
            "".join(f'<li style="margin: 0 0 18px 0; padding: 0;">{line}</li>' for line in html_offers),
            "</ol><p>À bientôt,</p>",
        ]
    ) + "</body></html>"

    message = EmailMessage(policy=SMTP)
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(text_body)
    message.add_alternative(html_body, subtype="html")
    message.add_attachment(cv_pdf.read_bytes(), maintype="application", subtype="pdf", filename=cv_pdf.name)

    manifest = {
        "status": "draft_prepared",
        "prepared_at": datetime.now(UTC).isoformat(),
        "recipient": recipient,
        "subject": subject,
        "site_url": normalized_site_url,
        "offer_count": len(selected),
        "offer_ids": [_text(offer.get("id")) for offer in selected],
        "attachment": {"path": str(cv_pdf), "sha256": sha256_file(cv_pdf)},
        "send_authorization": "required",
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        output_dir / "offer-selection.txt": text_body.encode("utf-8"),
        output_dir / "offer-selection.html": html_body.encode("utf-8"),
        output_dir / "offer-selection.eml": message.as_bytes(),
        output_dir / "manifest.json": (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    }
    atomic_write_bytes_group(files)
    return {**manifest, "output_dir": str(output_dir), "files": [str(path) for path in files]}
