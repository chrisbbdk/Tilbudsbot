"""Tilbud som vi tør regne på, og den rapport der følger med et kald."""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any


@dataclass(frozen=True)
class Offer:
    """Ét tilbud fra en tilbudsavis.

    ``price`` er avisens pakkepris i ``currency``. Kilopris beregnes kun, når
    mængden er entydig nok. Den opfindes ikke ud fra overskriften.
    """

    id: str
    heading: str
    description: str
    chain_id: str
    chain: str
    price: float
    currency: str
    pre_price: float | None
    size_from: float | None
    size_to: float | None
    unit_symbol: str | None
    si_symbol: str | None
    si_factor: float | None
    pieces: int | None
    valid_from: str
    valid_to: str
    catalog_id: str | None
    catalog_label: str | None
    dealer_slug: str | None
    source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Offer:
        known = {item.name for item in fields(cls)}
        missing = known - data.keys()
        if missing:
            raise ValueError(f"Tilbud mangler felter: {', '.join(sorted(missing))}")
        payload = {key: data[key] for key in known}
        payload["price"] = float(payload["price"])
        payload["pre_price"] = _maybe_float(payload["pre_price"])
        payload["size_from"] = _maybe_float(payload["size_from"])
        payload["size_to"] = _maybe_float(payload["size_to"])
        payload["si_factor"] = _maybe_float(payload["si_factor"])
        pieces = payload["pieces"]
        payload["pieces"] = None if pieces is None else int(pieces)
        return cls(**payload)

    def amount_bounds(self) -> tuple[float, float] | None:
        """Mængde i SI-enheden (kg, l eller stk). (mindste, største)."""

        if (
            self.size_from is None
            or self.si_factor is None
            or self.pieces is None
            or self.size_from <= 0
            or self.si_factor <= 0
            or self.pieces <= 0
        ):
            return None
        high_size = self.size_from if self.size_to is None else self.size_to
        if high_size <= 0:
            return None
        low = self.size_from * self.si_factor * self.pieces
        high = high_size * self.si_factor * self.pieces
        if low <= 0 or high < low:
            return None
        return low, high

    def unit_prices(self) -> tuple[float, float] | None:
        """(laveste, højeste) pris pr. SI-enhed.

        Højeste tal er den konservative pris: pakkeprisen delt med den mindste
        oplyste vægt. Det svarer til avisens "pr. kg max".
        """

        bounds = self.amount_bounds()
        if bounds is None or self.price <= 0:
            return None
        low_amount, high_amount = bounds
        return self.price / high_amount, self.price / low_amount

    def size_ratio(self) -> float:
        if not self.size_from or not self.size_to or self.size_from <= 0:
            return 1.0
        return self.size_to / self.size_from

    def comparable(self) -> bool:
        """Om enhedsprisen er sikker nok til at sortere 'billigst' på.

        Et stort vægtspænd på et "eller"-tilbud (fx gochujang eller ris) dækker
        to forskellige varer. Så udelader vi kg-prisen i stedet for at gætte.
        """

        if self.si_symbol not in {"kg", "l", "pcs"} or self.unit_prices() is None:
            return False
        ratio = self.size_ratio()
        if ratio > 3:
            return False
        if " eller " in self.heading.lower() and ratio > 1.8:
            return False
        return True

    def min_mass_kg(self) -> float | None:
        if self.si_symbol != "kg":
            return None
        bounds = self.amount_bounds()
        if bounds is None:
            return None
        return bounds[0]

    def web_url(self) -> str | None:
        if not self.id:
            return None
        if self.dealer_slug and self.catalog_id:
            return (
                f"https://etilbudsavis.dk/{self.dealer_slug}"
                f"?publication={self.catalog_id}&offer={self.id}"
            )
        return f"https://etilbudsavis.dk/offers/{self.id}"


def _maybe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


@dataclass(frozen=True)
class CatalogNote:
    chain: str
    label: str
    valid_from: str
    valid_to: str
    offer_count: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CatalogNote:
        return cls(
            chain=str(data["chain"]),
            label=str(data.get("label") or ""),
            valid_from=str(data.get("valid_from") or ""),
            valid_to=str(data.get("valid_to") or ""),
            offer_count=int(data.get("offer_count") or 0),
        )


@dataclass
class Report:
    """Hvor tallene kommer fra. Skal kunne læses i toppen af resumeet."""

    mode: str
    fetched_at: str
    api_base: str | None
    disclaimer: str | None
    catalogs: list[CatalogNote]
    errors: list[str]
    scanned: int
    kept: int
    fallback_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "fetched_at": self.fetched_at,
            "api_base": self.api_base,
            "disclaimer": self.disclaimer,
            "catalogs": [catalog.to_dict() for catalog in self.catalogs],
            "errors": list(self.errors),
            "scanned": self.scanned,
            "kept": self.kept,
            "fallback_reason": self.fallback_reason,
        }
