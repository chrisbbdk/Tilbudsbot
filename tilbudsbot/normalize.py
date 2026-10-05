"""Oversæt Tjek/etilbudsavis-JSON til :class:`Offer`."""

from __future__ import annotations

from typing import Any

from tilbudsbot.config import Chain
from tilbudsbot.models import Offer


def offer_from_hotspot(
    hotspot: dict[str, Any],
    chain: Chain,
    *,
    catalog_id: str | None,
    catalog_label: str | None,
    dealer_slug: str | None,
    source: str,
) -> Offer | None:
    raw = hotspot.get("offer") or hotspot
    if not isinstance(raw, dict):
        return None
    return _build_offer(
        raw,
        chain=chain,
        description=str(hotspot.get("description") or raw.get("description") or ""),
        valid_from=raw.get("run_from") or hotspot.get("run_from"),
        valid_to=raw.get("run_till") or hotspot.get("run_till"),
        catalog_id=catalog_id,
        catalog_label=catalog_label,
        dealer_slug=dealer_slug,
        source=source,
    )


def offer_from_search(raw: dict[str, Any], chain: Chain, *, source: str) -> Offer | None:
    dealer = raw.get("dealer") or {}
    return _build_offer(
        raw,
        chain=chain,
        description=str(raw.get("description") or ""),
        valid_from=raw.get("run_from"),
        valid_to=raw.get("run_till"),
        catalog_id=raw.get("catalog_id"),
        catalog_label=None,
        dealer_slug=_slug(dealer),
        source=source,
    )


def dealer_slug_from_catalog(catalog: dict[str, Any]) -> str | None:
    dealer = catalog.get("dealer") or {}
    return _slug(dealer)


def _slug(dealer: dict[str, Any]) -> str | None:
    markets = dealer.get("markets") or []
    for market in markets:
        if market.get("country_code") == "DK" and market.get("slug"):
            return str(market["slug"])
    for market in markets:
        if market.get("slug"):
            return str(market["slug"])
    return None


def _build_offer(
    raw: dict[str, Any],
    *,
    chain: Chain,
    description: str,
    valid_from: Any,
    valid_to: Any,
    catalog_id: str | None,
    catalog_label: str | None,
    dealer_slug: str | None,
    source: str,
) -> Offer | None:
    heading = " ".join(str(raw.get("heading") or "").split())
    offer_id = str(raw.get("id") or "").strip()
    pricing = raw.get("pricing") or {}
    price = pricing.get("price")
    if not heading or not offer_id or price is None:
        return None
    try:
        price_value = float(price)
    except (TypeError, ValueError):
        return None
    if price_value <= 0:
        return None
    currency = str(pricing.get("currency") or "DKK")
    pre_price = pricing.get("pre_price")
    try:
        pre_value = None if pre_price is None else float(pre_price)
    except (TypeError, ValueError):
        pre_value = None
    quantity = _quantity(raw.get("quantity"))
    if not valid_from or not valid_to:
        return None
    return Offer(
        id=offer_id,
        heading=heading,
        description=" ".join(description.split()),
        chain_id=chain.dealer_id,
        chain=chain.name,
        price=price_value,
        currency=currency,
        pre_price=pre_value,
        size_from=quantity["size_from"],
        size_to=quantity["size_to"],
        unit_symbol=quantity["unit_symbol"],
        si_symbol=quantity["si_symbol"],
        si_factor=quantity["si_factor"],
        pieces=quantity["pieces"],
        valid_from=str(valid_from),
        valid_to=str(valid_to),
        catalog_id=catalog_id,
        catalog_label=catalog_label,
        dealer_slug=dealer_slug,
        source=source,
    )


def _quantity(raw: Any) -> dict[str, Any]:
    quantity = raw or {}
    unit = quantity.get("unit") or {}
    si = unit.get("si") or {}
    size = quantity.get("size") or {}
    pieces = quantity.get("pieces") or {}
    size_from = _float_or_none(size.get("from"))
    size_to = _float_or_none(size.get("to"))
    if size_to is None:
        size_to = size_from
    factor = _float_or_none(si.get("factor"))
    symbol = unit.get("symbol")
    si_symbol = si.get("symbol") or symbol
    piece_from = pieces.get("from")
    piece_to = pieces.get("to")
    piece_count: int | None
    if piece_from is None and piece_to is None:
        # Tjek udelader sjældent feltet. 1 stk er deres normale salgsenhed.
        piece_count = 1
    elif piece_to is None or piece_to == piece_from:
        try:
            piece_count = int(piece_from)
        except (TypeError, ValueError):
            piece_count = None
    else:
        # Spænd i antal stk. Så kan vi ikke dele prisen uden at gætte.
        piece_count = None
    return {
        "size_from": size_from,
        "size_to": size_to,
        "unit_symbol": None if symbol is None else str(symbol),
        "si_symbol": None if si_symbol is None else str(si_symbol),
        "si_factor": factor,
        "pieces": piece_count,
    }


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
