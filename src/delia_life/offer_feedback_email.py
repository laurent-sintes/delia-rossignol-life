from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from email.message import EmailMessage
from email.policy import SMTP
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .core import sha256_file
from .storage import atomic_write_bytes_group

MAX_OFFERS_PER_EMAIL = 50
DEFAULT_FEEDBACK_BCC = "laurent.sintes74@gmail.com"
SECTION_DEFINITIONS = (
    ("priority", "Il faut répondre, ça matche et tu as des chances d’un retour positif"),
    ("possible", "Tu peux répondre, on ne sait jamais"),
    ("informational", "Je te les mets pour info, mais il y a peu de chances"),
)
SECTION_ORDER = {identifier: index for index, (identifier, _) in enumerate(SECTION_DEFINITIONS)}


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _safe_http_url(value: Any) -> str | None:
    candidate = _text(value)
    parts = urlsplit(candidate)
    if parts.scheme.casefold() not in {"http", "https"} or not parts.netloc:
        return None
    return candidate


def _visited_sources(report: dict[str, Any], offers: list[dict[str, Any]]) -> list[str]:
    values = report.get("visited_sources")
    candidates = list(values) if isinstance(values, list) else []
    if not candidates:
        candidates = [offer.get("source_url") for offer in offers]
    sources: dict[str, str] = {}
    for candidate in candidates:
        url = _safe_http_url(candidate)
        if url is None:
            continue
        parts = urlsplit(url)
        origin = f"{parts.scheme.casefold()}://{parts.netloc.casefold()}"
        sources.setdefault(origin, origin)
    return list(sources.values())


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
    bounded_score = min(100.0, max(0.0, float(score)))
    if bounded_score.is_integer():
        return f"{int(bounded_score)}/100"
    return f"{bounded_score:.1f}".replace(".", ",") + "/100"


def _offer_lines(offer: dict[str, Any]) -> tuple[str, str]:
    assessment = offer.get("assessment", {}) if isinstance(offer.get("assessment"), dict) else {}
    reasons = assessment.get("reasons", []) if isinstance(assessment.get("reasons"), list) else []
    reasons_text = "; ".join(_text(reason) for reason in reasons[:3] if _text(reason)) or "à examiner ensemble"
    title = _text(offer.get("title")) or "Offre sans intitulé"
    employer = _text(offer.get("employer")) or "employeur non précisé"
    contract = _text(offer.get("contract_type")) or "contrat à confirmer"
    location = _text(offer.get("location_label")) or "lieu à confirmer"
    link = _safe_http_url(offer.get("source_url"))
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
    vigilance = "; ".join(dict.fromkeys(vigilance_items))
    prerequisite_alerts = (
        assessment.get("prerequisite_alerts", [])
        if isinstance(assessment.get("prerequisite_alerts"), list)
        else []
    )
    if not prerequisite_alerts and offer.get("conditions", {}).get("insurance_experience_required") is True:
        prerequisite_alerts = [
            {
                "description": "Expérience préalable dans le domaine assurantiel",
                "message": "non démontré dans les connaissances validées",
            }
        ]
    prerequisite_items = [
        f"{_text(item.get('description'))} ({_text(item.get('message'))})"
        for item in prerequisite_alerts
        if isinstance(item, dict) and _text(item.get("description"))
    ]
    prerequisite_text = "; ".join(dict.fromkeys(prerequisite_items))
    if not vigilance:
        vigilance = (
            "aucun autre point de vigilance identifié dans l’annonce"
            if prerequisite_text
            else "aucun point bloquant identifié dans l’annonce"
        )
    text_prerequisite = f"\n⚠ PRÉREQUIS : {prerequisite_text}" if prerequisite_text else ""
    text_line = (
        f"Secteur d’activité : {sector}\n"
        f"Mission / poste : {title} — {employer}\n"
        f"Salaire proposé : {compensation}\n"
        f"Pertinence : {relevance}\n"
        f"Contrat et lieu : {contract}, {location}\n"
        f"{link or 'Lien de l’annonce non disponible'}\nPourquoi : {reasons_text}"
        f"{text_prerequisite}\nPoint de vigilance : {vigilance}"
    )
    html_link = (
        f'<a href="{html.escape(link, quote=True)}">Voir l’annonce</a>'
        if link is not None
        else "Lien de l’annonce non disponible"
    )
    html_prerequisite = (
        f'<span style="color: #b42318;"><strong>⚠ Prérequis :</strong> '
        f"{html.escape(prerequisite_text)}</span><br>"
        if prerequisite_text
        else ""
    )
    html_line = (
        f"<strong>Secteur d’activité :</strong> {html.escape(sector)}<br>"
        f"<strong>Mission / poste :</strong> {html.escape(title)} — {html.escape(employer)}<br>"
        f"<strong>Salaire proposé :</strong> {html.escape(compensation)}<br>"
        f"<strong>Pertinence :</strong> {html.escape(relevance)}<br>"
        f"<strong>Contrat et lieu :</strong> {html.escape(contract)}, {html.escape(location)}<br>"
        f"{html_link}<br>"
        f"Pourquoi : {html.escape(reasons_text)}<br>"
        f"{html_prerequisite}"
        f'<span style="color: #b85c20;"><strong>Point de vigilance :</strong> {html.escape(vigilance)}</span>'
    )
    return text_line, html_line


def _validate_email_address(address: str, label: str) -> str:
    value = address.strip()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError(f"A valid {label} email address is required")
    return value


def _offer_band(offer: dict[str, Any]) -> str:
    assessment = offer.get("assessment")
    declared = offer.get("recommendation_band")
    if not isinstance(declared, str) and isinstance(assessment, dict):
        declared = assessment.get("recommendation_band")
    if declared in SECTION_ORDER:
        return str(declared)
    score = assessment.get("score") if isinstance(assessment, dict) else 0
    numeric_score = float(score) if isinstance(score, (int, float)) else 0.0
    if numeric_score >= 75:
        return "priority"
    if numeric_score >= 50:
        return "possible"
    return "informational"


def _offer_relevance_key(offer: dict[str, Any]) -> tuple[int, float, int, str]:
    assessment = offer.get("assessment")
    score = assessment.get("score") if isinstance(assessment, dict) else 0
    numeric_score = float(score) if isinstance(score, (int, float)) else 0.0
    rank = offer.get("rank")
    numeric_rank = rank if isinstance(rank, int) else 2**31 - 1
    return (SECTION_ORDER[_offer_band(offer)], -numeric_score, numeric_rank, _text(offer.get("id")))


@dataclass(frozen=True)
class FeedbackEmailRequest:
    report: dict[str, Any]
    recipient: str
    bcc: str
    site_url: str
    cv_pdf: Path
    output_dir: Path
    limit: int
    offer_ids: tuple[str, ...] | None


@dataclass(frozen=True)
class FeedbackEmailSelection:
    recipient: str
    bcc: str
    site_url: str
    cv_pdf: Path
    output_dir: Path
    offers: tuple[dict[str, Any], ...]
    visited_sources: tuple[str, ...]


@dataclass(frozen=True)
class FeedbackEmailContent:
    subject: str
    text_body: str
    html_body: str


def _normalize_site_url(site_url: str) -> str:
    normalized = site_url.strip()
    if not normalized.startswith(("https://", "http://")):
        raise ValueError("site_url must be an absolute HTTP(S) URL")
    return normalized


def _usable_offers(report: dict[str, Any]) -> list[dict[str, Any]]:
    offers = report.get("offers")
    if not isinstance(offers, list) or not offers:
        raise ValueError("report must contain at least one ranked offer")
    return [offer for offer in offers if isinstance(offer, dict)]


def _select_offers(
    offers: list[dict[str, Any]],
    limit: int,
    offer_ids: tuple[str, ...] | None,
) -> tuple[dict[str, Any], ...]:
    if not 1 <= limit <= MAX_OFFERS_PER_EMAIL:
        raise ValueError(f"limit must be between 1 and {MAX_OFFERS_PER_EMAIL}")
    if offer_ids:
        if len(offer_ids) > MAX_OFFERS_PER_EMAIL:
            raise ValueError(f"at most {MAX_OFFERS_PER_EMAIL} offers can be included in one email")
        offers_by_id = {_text(offer.get("id")): offer for offer in offers}
        missing = [identifier for identifier in offer_ids if identifier not in offers_by_id]
        if missing:
            raise ValueError("report does not contain selected offer ids: " + ", ".join(missing))
        editorial_selection = [offers_by_id[identifier] for identifier in offer_ids]
        selected = tuple(sorted(editorial_selection, key=_offer_relevance_key))
    else:
        selected = tuple(sorted(offers, key=_offer_relevance_key)[:limit])
    if not selected:
        raise ValueError("report does not contain usable offers")
    return selected


def _prepare_selection(request: FeedbackEmailRequest) -> FeedbackEmailSelection:
    recipient = _validate_email_address(request.recipient, "recipient")
    bcc = _validate_email_address(request.bcc, "BCC")
    site_url = _normalize_site_url(request.site_url)
    if not request.cv_pdf.is_file() or request.cv_pdf.suffix.casefold() != ".pdf":
        raise ValueError("cv_pdf must be an existing PDF file")
    usable_offers = _usable_offers(request.report)
    selected_offers = _select_offers(usable_offers, request.limit, request.offer_ids)
    return FeedbackEmailSelection(
        recipient=recipient,
        bcc=bcc,
        site_url=site_url,
        cv_pdf=request.cv_pdf,
        output_dir=request.output_dir,
        offers=selected_offers,
        visited_sources=tuple(_visited_sources(request.report, usable_offers)),
    )


def _visited_source_notes(visited_sources: tuple[str, ...]) -> tuple[str, str]:
    text_note = "Pour information, sites consultés pour cette recherche :\n" + "\n".join(
        f"- {source}" for source in visited_sources
    )
    html_note = (
        "<p><strong>Pour information, sites consultés pour cette recherche :</strong></p><ul>"
        + "".join(
            f'<li><a href="{html.escape(source, quote=True)}">{html.escape(urlsplit(source).netloc)}</a></li>'
            for source in visited_sources
        )
        + "</ul>"
    )
    return text_note, html_note


def _render_email_content(selection: FeedbackEmailSelection) -> FeedbackEmailContent:
    rendered_offers = [
        (index, offer, *_offer_lines(offer))
        for index, offer in enumerate(selection.offers, start=1)
    ]
    text_sections: list[str] = []
    html_sections: list[str] = []
    for band, title in SECTION_DEFINITIONS:
        section_offers = [item for item in rendered_offers if _offer_band(item[1]) == band]
        if not section_offers:
            continue
        text_sections.append(
            title + "\n\n" + "\n\n".join(f"{index}. {text_line}" for index, _, text_line, _ in section_offers)
        )
        first_index = section_offers[0][0]
        html_sections.append(
            f'<section data-recommendation-band="{band}"><h2>{html.escape(title)}</h2>'
            f'<ol start="{first_index}">'
            + "".join(
                f'<li style="margin: 0 0 18px 0; padding: 0;">{html_line}</li>'
                for _, _, _, html_line in section_offers
            )
            + "</ol></section>"
        )
    visited_sources_text, visited_sources_html = _visited_source_notes(selection.visited_sources)
    offer_word = "offre" if len(selection.offers) == 1 else "offres"
    subject = f"Sélection de {len(selection.offers)} {offer_word} — ton avis"
    feedback_prompt = "Réponds simplement avec le numéro, 👍 / 🤔 / 👎 et une courte raison."
    text_body = "\n\n".join(
        [
            "Bonjour Délia,",
            "Voici une sélection d’offres préparée pour toi. Le classement est une aide à la décision : ton regard reste déterminant.",
            "Tu peux retrouver ton dossier professionnel ici : " + selection.site_url,
            "Ton CV actuel est joint à ce message.",
            feedback_prompt,
            "\n\n".join(text_sections),
            visited_sources_text,
            "À bientôt,",
        ]
    )
    html_body = "<html><body>" + "".join(
        [
            "<p>Bonjour Délia,</p>",
            "<p>Voici une sélection d’offres préparée pour toi. Le classement est une aide à la décision : ton regard reste déterminant.</p>",
            f'<p>Tu peux retrouver ton dossier professionnel ici : <a href="{html.escape(selection.site_url, quote=True)}">{html.escape(selection.site_url)}</a>.</p>',
            "<p>Ton CV actuel est joint à ce message.</p>",
            f"<p>{html.escape(feedback_prompt)}</p>",
            "".join(html_sections),
            visited_sources_html,
            "<p>À bientôt,</p>",
        ]
    ) + "</body></html>"
    return FeedbackEmailContent(subject=subject, text_body=text_body, html_body=html_body)


def _build_message(selection: FeedbackEmailSelection, content: FeedbackEmailContent) -> EmailMessage:
    message = EmailMessage(policy=SMTP)
    message["To"] = selection.recipient
    message["Bcc"] = selection.bcc
    message["Subject"] = content.subject
    message.set_content(content.text_body)
    message.add_alternative(content.html_body, subtype="html")
    message.add_attachment(
        selection.cv_pdf.read_bytes(),
        maintype="application",
        subtype="pdf",
        filename=selection.cv_pdf.name,
    )
    return message


def _build_manifest(selection: FeedbackEmailSelection, content: FeedbackEmailContent) -> dict[str, Any]:
    return {
        "status": "draft_prepared",
        "prepared_at": datetime.now(UTC).isoformat(),
        "recipient": selection.recipient,
        "bcc": selection.bcc,
        "subject": content.subject,
        "site_url": selection.site_url,
        "offer_count": len(selection.offers),
        "offer_ids": [_text(offer.get("id")) for offer in selection.offers],
        "section_counts": {
            band: sum(_offer_band(offer) == band for offer in selection.offers)
            for band, _ in SECTION_DEFINITIONS
        },
        "visited_sources": list(selection.visited_sources),
        "attachment": {"path": str(selection.cv_pdf), "sha256": sha256_file(selection.cv_pdf)},
        "send_authorization": "required",
    }


def _write_email_package(
    selection: FeedbackEmailSelection,
    content: FeedbackEmailContent,
    message: EmailMessage,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    selection.output_dir.mkdir(parents=True, exist_ok=True)
    files = {
        selection.output_dir / "offer-selection.txt": content.text_body.encode("utf-8"),
        selection.output_dir / "offer-selection.html": content.html_body.encode("utf-8"),
        selection.output_dir / "offer-selection.eml": message.as_bytes(),
        selection.output_dir / "manifest.json": (
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        ).encode("utf-8"),
    }
    atomic_write_bytes_group(files)
    return {
        **manifest,
        "output_dir": str(selection.output_dir),
        "files": [str(path) for path in files],
    }


def prepare_offer_feedback_email(
    report: dict[str, Any],
    recipient: str,
    site_url: str,
    cv_pdf: Path,
    output_dir: Path,
    limit: int = MAX_OFFERS_PER_EMAIL,
    offer_ids: list[str] | None = None,
    bcc: str = DEFAULT_FEEDBACK_BCC,
) -> dict[str, Any]:
    """Render a review email package without contacting a mail service."""
    request = FeedbackEmailRequest(
        report=report,
        recipient=recipient,
        bcc=bcc,
        site_url=site_url,
        cv_pdf=cv_pdf,
        output_dir=output_dir,
        limit=limit,
        offer_ids=tuple(offer_ids) if offer_ids is not None else None,
    )
    selection = _prepare_selection(request)
    content = _render_email_content(selection)
    message = _build_message(selection, content)
    manifest = _build_manifest(selection, content)
    return _write_email_package(selection, content, message, manifest)
