"""Dansk formatering af tal, datoer og mængder. Ingen priser opfindes her."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from tilbudsbot.models import Offer

COPENHAGEN = ZoneInfo("Europe/Copenhagen")
MONTHS = (
    "jan.",
    "feb.",
    "mar.",
    "apr.",
    "maj",
    "jun.",
    "jul.",
    "aug.",
    "sep.",
    "okt.",
    "nov.",
    "dec.",
)
WEEKDAYS = (
    "mandag",
    "tirsdag",
    "onsdag",
    "torsdag",
    "fredag",
    "lørdag",
    "søndag",
)


def parse_dt(value: str) -> datetime:
    text = value.strip().replace("Z", "+00:00")
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=COPENHAGEN)
    return parsed


def to_copenhagen(value: str) -> datetime:
    return parse_dt(value).astimezone(COPENHAGEN)


def format_date(value: str) -> str:
    stamp = to_copenhagen(value)
    return f"{stamp.day}. {MONTHS[stamp.month - 1]} {stamp.year}"


def format_period(start: str, end: str) -> str:
    if not start or not end:
        return ""
    opened = to_copenhagen(start)
    closed = to_copenhagen(end)
    if opened.date() == closed.date():
        return format_date(start)
    if opened.year == closed.year and opened.month == closed.month:
        return f"{opened.day}.–{closed.day}. {MONTHS[opened.month - 1]} {opened.year}"
    if opened.year == closed.year:
        return (
            f"{opened.day}. {MONTHS[opened.month - 1]} – "
            f"{closed.day}. {MONTHS[closed.month - 1]} {opened.year}"
        )
    return f"{format_date(start)} – {format_date(end)}"


def format_clock(value: str) -> str:
    stamp = to_copenhagen(value)
    return (
        f"{stamp.day}. {MONTHS[stamp.month - 1]} {stamp.year} "
        f"kl. {stamp.strftime('%H:%M')}"
    )


def format_number(value: float, digits: int = 2) -> str:
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    text = f"{value:.{digits}f}".rstrip("0").rstrip(".")
    return text.replace(".", ",")


def format_kr(value: float) -> str:
    """Pakkepris. Hele kroner uden decimaler, ellers to decimaler."""

    if abs(value - round(value)) < 0.001:
        return f"{int(round(value))} kr"
    return f"{value:.2f}".replace(".", ",") + " kr"


def format_unit_amount(value: float) -> str:
    return f"{value:.2f}".replace(".", ",")


def format_size(offer: Offer) -> str:
    if offer.size_from is None or not offer.unit_symbol:
        return ""
    unit = "stk" if offer.unit_symbol == "pcs" else offer.unit_symbol
    if offer.size_to is not None and abs(offer.size_to - offer.size_from) > 1e-6:
        size = f"{format_number(offer.size_from)}–{format_number(offer.size_to)} {unit}"
    else:
        size = f"{format_number(offer.size_from)} {unit}"
    if offer.pieces and offer.pieces > 1:
        return f"{offer.pieces} × {size}"
    return size


def format_unit_price(offer: Offer) -> str | None:
    """Enhedspris kun når ``Offer.comparable`` siger, at spændet er til at stole på."""

    if not offer.comparable() or offer.si_symbol not in {"kg", "l", "pcs"}:
        return None
    prices = offer.unit_prices()
    if prices is None:
        return None
    low, high = prices
    label = {"kg": "kr/kg", "l": "kr/l", "pcs": "kr/stk"}[offer.si_symbol]
    if abs(high - low) < 0.05:
        return f"{format_unit_amount(high)} {label}"
    return f"{format_unit_amount(low)}–{format_unit_amount(high)} {label}"


def role_name(role: str) -> str:
    names = {
        "kød": "Kød",
        "pasta": "Pasta",
        "ris": "Ris",
        "kartoffel": "Kartofler",
        "løg": "Løg",
        "gulerod": "Gulerødder",
        "peberfrugt": "Peberfrugt",
        "broccoli": "Broccoli",
        "tomat": "Tomater",
        "salat": "Salat",
        "porre": "Porre",
        "squash": "Squash",
        "kål": "Kål",
        "hvidløg": "Hvidløg",
        "blomkål": "Blomkål",
        "agurk": "Agurk",
    }
    return names.get(role, role[:1].upper() + role[1:] if role else role)


def short_heading(chain: str, heading: str) -> str:
    """Fjern kædenavnet foran varenavnet, så linjen ikke siger Netto to gange."""

    text = " ".join(heading.split())
    prefix = chain.strip()
    if prefix and text.lower().startswith(prefix.lower()):
        trimmed = text[len(prefix) :].lstrip(" -–:")
        if trimmed:
            return trimmed
    return text


def weekday_label(day_index_from_today: int, today) -> str:
    stamp = today.fromordinal(today.toordinal() + day_index_from_today)
    name = WEEKDAYS[stamp.weekday()].capitalize()
    return f"{name} {stamp.day}. {MONTHS[stamp.month - 1]}"
