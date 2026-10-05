"""En madplan på 4–5 dage ud fra de billigste egnede tilbud.

Gramtal er et husholdningsskøn. Kroner kommer kun fra pakkepriser i avisen,
ganget med det antal pakker skønnet kræver. Mangler vægten, udelades linjen
fra totalen i stedet for at få et gættet beløb.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from tilbudsbot.models import Offer
from tilbudsbot.staples import Classified, best_piece_veg, best_protein, best_side, covers_day
from tilbudsbot.text import COPENHAGEN, role_name

# Protein pr. person pr. middag, i gram.
PROTEIN_GRAMS = {"hakket_okse": 110, "kylling": 160, "gris": 150}
SIDE_GRAMS = {"pasta": 90, "ris": 75, "kartoffel": 220}
VEG_GRAMS = {
    "gulerod": 70,
    "løg": 40,
    "peberfrugt": 70,
    "broccoli": 80,
    "tomat": 80,
    "salat": 40,
    "porre": 40,
    "squash": 80,
    "kål": 80,
    "hvidløg": 10,
    "blomkål": 100,
    "agurk": 50,
}


@dataclass(frozen=True)
class Template:
    category: str
    title: str
    side: str | None
    veg_types: tuple[str, ...]
    note: str


TEMPLATES: dict[str, tuple[Template, ...]] = {
    "hakket_okse": (
        Template(
            "hakket_okse",
            "Spaghetti med kødsovs",
            "pasta",
            ("gulerod", "løg"),
            "Krydderier og hakkede tomater er ikke prissat, medmindre de står i grøntlisten.",
        ),
        Template(
            "hakket_okse",
            "Hakkebøffer med bløde løg",
            "kartoffel",
            ("løg",),
            "Brun sovs er ikke prissat. Den stod ikke som en vare i planen.",
        ),
        Template(
            "hakket_okse",
            "Lasagne",
            "pasta",
            ("gulerod", "løg"),
            "Bechamel og lasagneplader er kun med, hvis pasta-tilbuddet dækker det.",
        ),
    ),
    "kylling": (
        Template(
            "kylling",
            "Kylling i karry med ris",
            "ris",
            ("løg", "peberfrugt"),
            "Karry og mælk er ikke prissat.",
        ),
        Template(
            "kylling",
            "Kylling i ovn med kartofler",
            "kartoffel",
            ("løg",),
            "Brug samme pakke igen, hvis én kylling dækker mere end én dag.",
        ),
        Template(
            "kylling",
            "Kyllingewok",
            "ris",
            ("broccoli", "gulerod"),
            "Soya og olie er ikke prissat.",
        ),
    ),
    "gris": (
        Template(
            "gris",
            "Gris med kartofler",
            "kartoffel",
            ("løg",),
            "Retten følger det konkrete tilbud: frikadeller, medister, kotelet eller flæsk.",
        ),
        Template(
            "gris",
            "Resten af grisen med kartofler",
            "kartoffel",
            ("løg",),
            "Samme pakke som den anden grisdag, hvis vægten rækker.",
        ),
    ),
}


@dataclass(frozen=True)
class Use:
    offer_id: str
    role: str
    grams: float | None
    pieces: int | None


@dataclass(frozen=True)
class Meal:
    day_label: str
    title: str
    note: str
    missing: tuple[str, ...]
    uses: tuple[Use, ...]


@dataclass(frozen=True)
class ShoppingLine:
    offer_id: str
    chain: str
    heading: str
    packs: int | None
    unit_price: float
    line_price: float | None
    detail: str


@dataclass(frozen=True)
class Plan:
    days: int
    people: int
    meals: tuple[Meal, ...]
    shopping: tuple[ShoppingLine, ...]
    total: float | None
    total_partial: bool
    missing_proteins: tuple[str, ...]


def build_plan(
    staples: dict[str, list[Classified]],
    *,
    days: int,
    people: int,
    today: date | None = None,
) -> Plan:
    if days not in {4, 5}:
        raise ValueError("Madplanen er sat op til 4 eller 5 dage.")
    if people < 1 or people > 8:
        raise ValueError("Antal personer skal være mellem 1 og 8.")
    start = today or datetime.now(COPENHAGEN).date()
    end = start + timedelta(days=days - 1)
    offers = _offers_by_id(staples)
    proteins = {
        key: best_protein(staples.get(key) or [], start=start, end=end)
        for key in ("hakket_okse", "kylling", "gris")
    }
    chosen = {key: item for key, item in proteins.items() if item is not None}
    missing = tuple(
        name
        for key, name in (
            ("hakket_okse", "hakket oksekød"),
            ("kylling", "kylling"),
            ("gris", "gris"),
        )
        if key not in chosen
    )
    sequence = _sequence(list(chosen.values()), days)
    seen: dict[str, int] = {}
    meals_list = []
    for index, item in enumerate(sequence):
        occurrence = seen.get(item.category, 0)
        meals_list.append(_meal(index, occurrence, item, staples, people, start, end))
        seen[item.category] = occurrence + 1
    meals = tuple(meals_list)
    shopping, total, partial = _shopping(meals, offers)
    return Plan(
        days=days,
        people=people,
        meals=meals,
        shopping=shopping,
        total=total,
        total_partial=partial,
        missing_proteins=missing,
    )


def _meal(
    index: int,
    occurrence: int,
    protein: Classified,
    staples: dict[str, list[Classified]],
    people: int,
    start: date,
    end: date,
) -> Meal:
    from tilbudsbot.text import weekday_label

    template = _template_for(protein, staples, occurrence, start, end)
    title = template.title
    if protein.category == "gris" and template.title == "Gris med kartofler":
        title = _pork_title(protein.offer.heading)
    if _whole_chicken(protein.offer.heading):
        has_potatoes = _side_offer("kartoffel", staples, start, end) is not None
        if occurrence == 0:
            title = "Hel kylling i ovn med kartofler" if has_potatoes else "Hel kylling i ovn"
        else:
            title = "Resten af kyllingen med kartofler" if has_potatoes else "Resten af kyllingen"
        side = "kartoffel" if has_potatoes else "ris"
        template = Template(
            "kylling",
            title,
            side,
            ("løg",),
            "Én hel kylling rækker ofte til mere end én middag. Pakketallet følger vægten.",
        )
    uses: list[Use] = [
        Use(
            offer_id=protein.offer.id,
            role="kød",
            grams=PROTEIN_GRAMS[protein.category] * people,
            pieces=None,
        )
    ]
    missing: list[str] = []
    side_name = {"pasta": "pasta", "ris": "ris", "kartoffel": "kartofler"}.get(template.side or "", "")
    side = _side_offer(template.side, staples, start, end)
    if template.side and side is None:
        missing.append(side_name)
    elif side is not None and template.side is not None:
        uses.append(
            Use(
                offer_id=side.offer.id,
                role=template.side,
                grams=SIDE_GRAMS[template.side] * people,
                pieces=None,
            )
        )
    for veg_type in template.veg_types:
        if veg_type == template.side:
            continue
        veg, pieces = _veg_offer(staples.get("gront") or [], veg_type, people, start, end)
        if veg is None:
            continue
        uses.append(Use(offer_id=veg.offer.id, role=veg_type, grams=None if pieces else VEG_GRAMS.get(veg_type, 60) * people, pieces=pieces))
    note = template.note
    meal_day = start + timedelta(days=index)
    if not covers_day(protein.offer, meal_day):
        note = "Kødtilbuddet gælder ikke denne dato. Køb det på en dag, det dækker, eller vælg en anden ret. " + note
    if protein.tier > 0:
        note = "Tilbuddet er en blanding eller flere varianter. " + note
    return Meal(
        day_label=weekday_label(index, start),
        title=title,
        note=note,
        missing=tuple(missing),
        uses=tuple(uses),
    )


def _template_for(
    protein: Classified,
    staples: dict[str, list[Classified]],
    occurrence: int,
    start: date,
    end: date,
) -> Template:
    options = list(TEMPLATES[protein.category])
    ready = [item for item in options if _side_offer(item.side, staples, start, end) is not None or item.side is None]
    pool = ready or options
    return pool[occurrence % len(pool)]


def _side_offer(
    kind: str | None,
    staples: dict[str, list[Classified]],
    start: date,
    end: date,
) -> Classified | None:
    if kind == "pasta":
        return best_side(staples.get("pasta") or [], start=start, end=end)
    if kind == "ris":
        return best_side(staples.get("ris") or [], start=start, end=end)
    if kind == "kartoffel":
        return best_side(staples.get("gront") or [], veg_type="kartoffel", start=start, end=end)
    return None


def _veg_offer(
    items: list[Classified],
    veg_type: str,
    people: int,
    start: date,
    end: date,
) -> tuple[Classified | None, int | None]:
    by_weight = best_side(items, veg_type=veg_type, start=start, end=end)
    if by_weight is not None:
        return by_weight, None
    by_piece = best_piece_veg(items, veg_type, start=start, end=end)
    if by_piece is None:
        return None, None
    if veg_type == "hvidløg":
        pieces = 1
    else:
        pieces = max(1, math.ceil(people / 2))
    return by_piece, pieces


def _shopping(
    meals: tuple[Meal, ...],
    offers: dict[str, Offer],
) -> tuple[tuple[ShoppingLine, ...], float | None, bool]:
    grams: dict[str, float] = {}
    pieces: dict[str, int] = {}
    roles: dict[str, set[str]] = {}
    for meal in meals:
        for use in meal.uses:
            roles.setdefault(use.offer_id, set()).add(use.role)
            if use.grams:
                grams[use.offer_id] = grams.get(use.offer_id, 0.0) + use.grams
            if use.pieces:
                pieces[use.offer_id] = pieces.get(use.offer_id, 0) + use.pieces
    lines: list[ShoppingLine] = []
    partial = False
    total = 0.0
    any_price = False
    for offer_id in _shopping_order(grams, pieces, offers):
        offer = offers[offer_id]
        need_grams = grams.get(offer_id)
        need_pieces = pieces.get(offer_id)
        packs, detail = _packs(offer, need_grams, need_pieces)
        line_price = None if packs is None else round(packs * offer.price, 2)
        if line_price is None:
            partial = True
        else:
            total += line_price
            any_price = True
        role_text = ", ".join(role_name(role) for role in sorted(roles.get(offer_id) or []))
        lines.append(
            ShoppingLine(
                offer_id=offer.id,
                chain=offer.chain,
                heading=offer.heading,
                packs=packs,
                unit_price=offer.price,
                line_price=line_price,
                detail=f"{role_text}. {detail}".strip(),
            )
        )
    if not any_price:
        return tuple(lines), None, True
    return tuple(lines), round(total, 2), partial


def _packs(offer: Offer, need_grams: float | None, need_pieces: int | None) -> tuple[int | None, str]:
    if need_grams:
        mass = offer.min_mass_kg()
        if mass is None or mass <= 0:
            return None, "Pakkestørrelse i kg mangler, så antal og sum er udeladt."
        packs = math.ceil(need_grams / (mass * 1000) - 1e-9)
        packs = max(packs, 1)
        basis = "mindste oplyste vægt" if offer.size_ratio() > 1.001 else "oplyst vægt"
        extra = ""
        if need_grams < mass * 1000 * 0.75:
            extra = " Pakken rækker til mere end de dage, den er sat på."
        return packs, f"Ca. {int(round(need_grams))} g i planen, {packs} pk. ud fra {basis}.{extra}"
    if need_pieces:
        if offer.si_symbol != "pcs" or offer.pieces is None or offer.size_from is None:
            return None, "Stykprisen kan ikke omregnes til pakker uden at gætte."
        per_pack = offer.size_from * offer.pieces
        if per_pack <= 0:
            return None, "Stykprisen kan ikke omregnes til pakker uden at gætte."
        packs = max(1, math.ceil(need_pieces / per_pack - 1e-9))
        return packs, f"Ca. {need_pieces} stk. i planen, {packs} pk."
    return None, "Ingen mængde at regne på."


def _shopping_order(grams: dict[str, float], pieces: dict[str, int], offers: dict[str, Offer]) -> list[str]:
    ids = list(grams) + [offer_id for offer_id in pieces if offer_id not in grams]
    return sorted(ids, key=lambda offer_id: (offers[offer_id].chain, offers[offer_id].heading, offer_id))


def _offers_by_id(staples: dict[str, list[Classified]]) -> dict[str, Offer]:
    found: dict[str, Offer] = {}
    for items in staples.values():
        for item in items:
            found[item.offer.id] = item.offer
    return found


def _sequence(proteins: list[Classified], days: int) -> list[Classified]:
    if not proteins:
        return []
    ranked = sorted(proteins, key=lambda item: (item.kr_high or 10**12, item.offer.chain, item.offer.id))
    count = min(3, len(ranked))
    pattern = {
        (5, 1): ["P"],
        (5, 2): ["P", "S", "P", "S", "P"],
        (5, 3): ["P", "S", "P", "T", "P"],
        (4, 1): ["P"],
        (4, 2): ["P", "S", "P", "S"],
        (4, 3): ["P", "S", "P", "T"],
    }[(days, count)]
    mapping = {"P": ranked[0], "S": ranked[min(1, len(ranked) - 1)], "T": ranked[min(2, len(ranked) - 1)]}
    if count == 1:
        return [ranked[0]] * days
    return [mapping[slot] for slot in pattern]


def _whole_chicken(heading: str) -> bool:
    text = heading.lower()
    return "kylling" in text and re.search(r"(?<!\w)hel(?!\w)", text) is not None


def _pork_title(heading: str) -> str:
    text = heading.lower()
    has_mince = "hakket" in text
    has_medister = "medister" in text
    if has_mince and has_medister:
        return "Frikadeller eller medister med kartofler"
    if has_medister:
        return "Medister med kartofler"
    if "kotelet" in text:
        return "Koteletter med kartofler"
    if has_mince:
        return "Frikadeller med kartofler"
    if "mørbrad" in text:
        return "Mørbrad af gris med kartofler"
    if "flæskesteg" in text:
        return "Flæskesteg med kartofler"
    if "flæsk" in text:
        return "Flæsk i ovn med kartofler"
    return "Gris med kartofler"
