"""Indlæs det tjekkede eksempeludsnit, når live-hentning ikke kan bruges."""

from __future__ import annotations

import json

from tilbudsbot.config import FIXTURE_PATH
from tilbudsbot.models import CatalogNote, Offer, Report


def load_fixture(path=FIXTURE_PATH) -> tuple[list[Offer], Report]:
    if not path.is_file():
        raise FileNotFoundError(f"Mangler fixture: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    offers = [Offer.from_dict(item) for item in payload.get("offers") or []]
    for offer in offers:
        if offer.currency != "DKK":
            raise ValueError(f"Fixture-tilbud {offer.id} er ikke i DKK.")
    report = Report(
        mode="fixture",
        fetched_at=str(payload.get("captured_at") or ""),
        api_base=payload.get("api_base"),
        disclaimer=str(payload.get("disclaimer") or "EKSEMPELDATA — ikke live priser."),
        catalogs=[CatalogNote.from_dict(item) for item in payload.get("catalogs") or []],
        errors=[],
        scanned=int(payload.get("scanned") or len(offers)),
        kept=len(offers),
        fallback_reason=None,
    )
    return offers, report
