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


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def _offer_lines(offer: dict[str, Any]) -> tuple[str, str]:
    assessment = offer.get("assessment", {}) if isinstance(offer.get("assessment"), dict) else {}
    reasons = assessment.get("reasons", []) if isinstance(assessment.get("reasons"), list) else []
    reasons_text = "; ".join(_text(reason) for reason in reasons[:3] if _text(reason)) or "à examiner ensemble"
    title = _text(offer.get("title")) or "Offre sans intitulé"
    employer = _text(offer.get("employer")) or "employeur non précisé"
    contract = _text(offer.get("contract_type")) or "contrat à confirmer"
    location = _text(offer.get("location_label")) or "lieu à confirmer"
    link = _text(offer.get("source_url"))
    text_line = f"{title} — {employer} ({contract}, {location})\n{link}\nPourquoi : {reasons_text}"
    html_line = (
        f"<strong>{html.escape(title)}</strong> — {html.escape(employer)} "
        f"({html.escape(contract)}, {html.escape(location)})<br>"
        f'<a href="{html.escape(link, quote=True)}">Voir l’annonce</a><br>'
        f"Pourquoi : {html.escape(reasons_text)}"
    )
    return text_line, html_line


def _validate_recipient(recipient: str) -> str:
    value = recipient.strip()
    if "@" not in value or value.startswith("@") or value.endswith("@"):
        raise ValueError("A valid recipient email address is required")
    return value


def prepare_offer_feedback_email(
    report: dict[str, Any],
    recipient: str,
    site_url: str,
    cv_pdf: Path,
    output_dir: Path,
    limit: int = 10,
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
    if offer_ids:
        offers_by_id = {_text(offer.get("id")): offer for offer in usable_offers}
        missing = [identifier for identifier in offer_ids if identifier not in offers_by_id]
        if missing:
            raise ValueError("report does not contain selected offer ids: " + ", ".join(missing))
        selected = [offers_by_id[identifier] for identifier in offer_ids]
    else:
        selected = usable_offers[:limit]
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
            "".join(f"<li>{line}</li>" for line in html_offers),
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
