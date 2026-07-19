from __future__ import annotations

from typing import Any

from .core import stable_id, utc_now

EVENT_TYPES = {
    "drafted",
    "submitted",
    "acknowledged",
    "interview",
    "rejected",
    "offer_received",
    "withdrawn",
    "feedback",
}


def append_event(application: dict[str, Any], event_type: str, details: dict[str, Any]) -> dict[str, Any]:
    if event_type not in EVENT_TYPES:
        raise ValueError(f"Unsupported event type: {event_type}")
    result = dict(application)
    events = list(result.get("events", []))
    event_details = dict(details)
    occurred_at = event_details.pop("occurred_at", utc_now())
    event = {
        "id": stable_id("evt", str(result.get("id", "application")), event_type, occurred_at, str(len(events))),
        "type": event_type,
        "occurred_at": occurred_at,
        "details": event_details,
    }
    events.append(event)
    result["events"] = events
    result["updated_at"] = utc_now()
    return result
