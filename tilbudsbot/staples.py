"""Find hakket oksekød og de andre faste varer i en bunke tilbud.

Klassifikationen er bevidst streng. "Løgismose" er ikke løg, "tørkost" er ikke
ost, og et "eller"-tilbud med tre kødtyper er ikke en oksekødspris.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from tilbudsbot.models import Offer

CATEGORIES = (
    "hakket_okse",
    "kylling",
    "gris",
    "pasta",
    "ris",
    "ost",
    "gront",
)

CATEGORY_TITLES = {
    "hakket_okse": "Hakket oksekød",
    "kylling": "Kylling",
    "gris": "Gris",
    "pasta": "Pasta",
    "ris": "Ris",
    "ost": "Ost",
    "gront": "Grønt",
}

# Ren vare vinder over en lidt billigere blanding. Blandingen skal være
# mindst 20 % billigere pr. kg, før madplanen bruger den som kød.
PURE_PRICE_MARGIN = 0.80
MIN_PLAN_KG = 0.15
MAX_PLAN_KG = 3.0

_DENY = re.compile(
    r"tørkost|dyremad|hundefoder|kattemad|kattefoder|whiskas|"
    r"(?<!\w)(hunde|hund|hvalp|kattefoder|kat)(?!\w)|"
    r"shampoo|tandpasta|vaskepulver|opvasketabs|(?<!\w)bleer(?!\w)|"
    r"(?<!\w)(øl|vin|vodka|whisky|hvidvin|rødvin|cigaretter)(?!\w)",
    re.IGNORECASE,
)
_SPECIES = (
    ("okse", re.compile(r"okse", re.IGNORECASE)),
    ("gris", re.compile(r"gris|svine|flæsk|medister", re.IGNORECASE)),
    ("kalv", re.compile(r"kalv", re.IGNORECASE)),
    ("kylling", re.compile(r"kylling", re.IGNORECASE)),
    ("lam", re.compile(r"(?<!\w)lam(?!\w)|lamme", re.IGNORECASE)),
)
_MINCED_BEEF = re.compile(r"hakket", re.IGNORECASE)
_BEEF_WORD = re.compile(r"okse", re.IGNORECASE)
_CHICKEN = re.compile(r"kylling", re.IGNORECASE)
_CHICKEN_WEAK = re.compile(
    r"nugget|burger|pålæg|sandwich|pizza|wrap|(?<!\w)salat(?!\w)|suppe|fond|bouillon|krymmel|paneret",
    re.IGNORECASE,
)
_PORK = re.compile(
    r"hakket\s+gris|hakket\s+svine|grisekød|svinekød|medister|kotelet|"
    r"flæsk|nakkefilet|mørbrad|svinekam|(?<!\w)ribben(?!\w)",
    re.IGNORECASE,
)
_PORK_EXCLUDE = re.compile(r"flæskesvær|leverpostej|spegepølse|pålæg", re.IGNORECASE)
_PORK_WEAK = re.compile(r"bacon|(?<!\w)pølse(?!\w)|pepperoni", re.IGNORECASE)
_PASTA = re.compile(
    r"(?<!\w)(pasta|spaghetti|penne|fusilli|makaroni|lasagneplader|tortellini|gnocchi)(?!\w)",
    re.IGNORECASE,
)
_PASTA_EXCLUDE = re.compile(r"pastasauce|pastasalat|sauce", re.IGNORECASE)
_RICE = re.compile(
    r"(?<!\w)(jasminris|basmatiris|grødris|fuldkornsris|parboiled(?:\s*ris)?|ris)(?!\w)",
    re.IGNORECASE,
)
_RICE_WEAK = re.compile(r"risalamande|risengrød|risret|budding", re.IGNORECASE)
_CHEESE = re.compile(
    r"(?<!\w)(skæreost|skiveost|dessertost|flødeost|mozzarella|danbo|havarti|"
    r"cheddar|gauda|gouda|parmesan|feta|brie|camembert|ost)(?!\w)",
    re.IGNORECASE,
)
_CHEESE_EXCLUDE = re.compile(
    r"ostekage|ostehaps|ostekiks|kiks|chips|kage|yoghurt|skyr|fraiche|kvark|(?<!\w)ymer(?!\w)",
    re.IGNORECASE,
)
_VEG_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    # Også sammensatte navne som lammefjordskartofler. Forarbejdet kartoffelmad
    # sorteres fra i _VEG_EXCLUDE.
    ("kartoffel", re.compile(r"kartofler|kartoffel", re.IGNORECASE)),
    ("gulerod", re.compile(r"(?<!\w)(gulerødder|gulerod)(?!\w)", re.IGNORECASE)),
    ("hvidløg", re.compile(r"(?<!\w)hvidløg(?!\w)", re.IGNORECASE)),
    ("løg", re.compile(r"(?<!\w)(rødløg|forårsløg|bananløg|salatløg|løg)(?!\w)", re.IGNORECASE)),
    ("broccoli", re.compile(r"(?<!\w)broccoli(?!\w)", re.IGNORECASE)),
    ("blomkål", re.compile(r"(?<!\w)blomkål(?!\w)", re.IGNORECASE)),
    ("peberfrugt", re.compile(r"peberfrugt|snackpeber", re.IGNORECASE)),
    ("tomat", re.compile(r"(?<!\w)(hakkede\s+tomater|tomater|tomat)(?!\w)", re.IGNORECASE)),
    ("agurk", re.compile(r"(?<!\w)agurk(?!\w)", re.IGNORECASE)),
    ("salat", re.compile(r"(?<!\w)(icebergsalat|hjertesalat|romainesalat|salatmix|salat)(?!\w)", re.IGNORECASE)),
    ("porre", re.compile(r"(?<!\w)porre(?!\w)", re.IGNORECASE)),
    ("squash", re.compile(r"(?<!\w)squash(?!\w)", re.IGNORECASE)),
    ("kål", re.compile(r"(?<!\w)(spidskål|hvidkål|rødkål)(?!\w)", re.IGNORECASE)),
)
_VEG_EXCLUDE = re.compile(
    r"chips|pommes|pomfrit|kroket|fritter|gratin|røsti|kartoffelmel|"
    r"ketchup|juice|(?<!\w)saft(?!\w)|(?<!\w)suppe(?!\w)|"
    r"kyllingesalat|pastasalat|rejesalat|kartoffelsalat|pizza|burger",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Classified:
    offer: Offer
    category: str
    tier: int
    veg_type: str | None
    comparable: bool
    kr_low: float | None
    kr_high: float | None
    unit_label: str | None

    def sort_key(self) -> tuple:
        unit_rank = 0 if self.comparable and self.unit_label == "kr/kg" else 1
        price = self.kr_high if self.kr_high is not None else 10**12
        return (
            self.tier,
            unit_rank,
            price,
            self.offer.price,
            self.offer.chain,
            self.offer.heading,
            self.offer.id,
        )


def classify(offer: Offer) -> Classified | None:
    if offer.currency != "DKK" or offer.price <= 0:
        return None
    text = f"{offer.heading} {offer.description}".strip()
    if _DENY.search(text):
        return None
    category, tier, veg_type = _category(text)
    if category is None or tier is None:
        return None
    unit_label = _unit_label(offer)
    low = high = None
    prices = offer.unit_prices()
    comparable = bool(offer.comparable() and unit_label)
    if comparable and prices is not None:
        low, high = prices
    return Classified(
        offer=offer,
        category=category,
        tier=tier,
        veg_type=veg_type,
        comparable=comparable,
        kr_low=low,
        kr_high=high,
        unit_label=unit_label if comparable else None,
    )


def rank_staples(offers: list[Offer]) -> dict[str, list[Classified]]:
    grouped: dict[str, list[Classified]] = {key: [] for key in CATEGORIES}
    seen: set[tuple[str, str]] = set()
    for offer in offers:
        identity = (offer.chain_id, offer.id)
        if identity in seen:
            continue
        seen.add(identity)
        item = classify(offer)
        if item is None:
            continue
        grouped[item.category].append(item)
    for items in grouped.values():
        items.sort(key=lambda item: item.sort_key())
    return grouped


def highlights(items: list[Classified], limit: int = 2) -> list[Classified]:
    """De tilbud vi viser. Samme vare to gange i avisen tælles én gang."""

    picked: list[Classified] = []
    seen: set[tuple[str, str, float]] = set()
    for item in items:
        if item.offer.min_mass_kg() is not None and item.offer.min_mass_kg() > MAX_PLAN_KG:
            continue
        key = (item.offer.chain_id, item.offer.heading.lower(), round(item.offer.price, 2))
        if key in seen:
            continue
        seen.add(key)
        picked.append(item)
        if len(picked) >= limit:
            break
    return picked


def beef_sections(items: list[Classified]) -> tuple[list[Classified], list[Classified]]:
    """Rene hakket-okse-tilbud, plus ét blandet hvis det faktisk er billigere."""

    pure = highlights([item for item in items if item.tier == 0], limit=2)
    mixed_pool = [item for item in items if item.tier >= 1]
    mixed = highlights(mixed_pool, limit=1)
    if pure and mixed:
        pure_price = pure[0].kr_high
        mixed_price = mixed[0].kr_high
        if pure_price is not None and mixed_price is not None and mixed_price >= pure_price:
            mixed = []
    if not pure and not mixed:
        mixed = highlights(items, limit=1)
    return pure, mixed


def best_protein(
    items: list[Classified],
    *,
    start: date | None = None,
    end: date | None = None,
) -> Classified | None:
    """Billigste egnede kød, med forkærlighed for den rene vare.

    Når ``start`` og ``end`` er sat, foretrækkes et tilbud, der gælder alle
    dagene. Et billigere tilbud, der kun gælder en enkelt dag, vinder ikke
    madplanen, hvis et dyrere tilbud dækker hele ugen.
    """

    pure = _best_usable(items, tier=0, start=start, end=end)
    mixed = _best_usable(items, tier=1, start=start, end=end)
    weak = _best_usable(items, tier=2, start=start, end=end)
    if pure and mixed and mixed.kr_high is not None and pure.kr_high is not None:
        if mixed.kr_high < pure.kr_high * PURE_PRICE_MARGIN:
            return mixed
        return pure
    return pure or mixed or weak


def best_side(
    items: list[Classified],
    *,
    veg_type: str | None = None,
    start: date | None = None,
    end: date | None = None,
) -> Classified | None:
    pool = items
    if veg_type is not None:
        pool = [item for item in items if item.veg_type == veg_type]
    usable = [item for item in pool if _usable_mass(item)]
    usable = _prefer_full_coverage(usable, start, end)
    if not usable:
        return None
    pure = [item for item in usable if item.tier == 0]
    mixed = [item for item in usable if item.tier <= 1]
    chosen = pure or mixed or usable
    return min(chosen, key=lambda item: (item.kr_high or 10**12, item.tier, item.offer.price, item.offer.id))


def best_piece_veg(
    items: list[Classified],
    veg_type: str,
    *,
    start: date | None = None,
    end: date | None = None,
) -> Classified | None:
    pool = [
        item
        for item in items
        if item.veg_type == veg_type and item.comparable and item.unit_label == "kr/stk"
    ]
    pool = _prefer_full_coverage(pool, start, end)
    if not pool:
        return None
    return min(pool, key=lambda item: (item.kr_high or 10**12, item.offer.price, item.offer.id))


def _best_usable(
    items: list[Classified],
    *,
    tier: int,
    start: date | None = None,
    end: date | None = None,
) -> Classified | None:
    pool = [item for item in items if item.tier == tier and _usable_mass(item)]
    pool = _prefer_full_coverage(pool, start, end)
    if not pool:
        return None
    return min(pool, key=lambda item: (item.kr_high or 10**12, item.offer.price, item.offer.chain, item.offer.id))


def covers_day(offer: Offer, day: date) -> bool:
    opened, closed = _validity(offer)
    return opened <= day <= closed


def covers_window(offer: Offer, start: date, end: date) -> bool:
    opened, closed = _validity(offer)
    return opened <= start and closed >= end


def _prefer_full_coverage(
    items: list[Classified],
    start: date | None,
    end: date | None,
) -> list[Classified]:
    if start is None or end is None or not items:
        return items
    full = [item for item in items if covers_window(item.offer, start, end)]
    return full or items


def _validity(offer: Offer) -> tuple[date, date]:
    from tilbudsbot.text import to_copenhagen

    return to_copenhagen(offer.valid_from).date(), to_copenhagen(offer.valid_to).date()


def _usable_mass(item: Classified) -> bool:
    if not item.comparable or item.unit_label != "kr/kg" or item.kr_high is None:
        return False
    mass = item.offer.min_mass_kg()
    if mass is None:
        return False
    return MIN_PLAN_KG <= mass <= MAX_PLAN_KG


def _unit_label(offer: Offer) -> str | None:
    return {"kg": "kr/kg", "l": "kr/l", "pcs": "kr/stk"}.get(offer.si_symbol or "")


def _category(text: str) -> tuple[str | None, int | None, str | None]:
    if _is_minced_beef(text):
        return "hakket_okse", _beef_tier(text), None
    if _CHICKEN.search(text):
        tier = _chicken_tier(text)
        if tier is None:
            return None, None, None
        return "kylling", tier, None
    if _PORK.search(text) and not _PORK_EXCLUDE.search(text):
        tier = 2 if _PORK_WEAK.search(text) else _species_tier(text, default=0)
        return "gris", tier, None
    if _PASTA.search(text) and not _PASTA_EXCLUDE.search(text):
        tier = 1 if " eller " in text.lower() else 0
        return "pasta", tier, None
    if _RICE.search(text):
        tier = 2 if _RICE_WEAK.search(text) else _species_tier(text, default=0)
        if re.search(r"kiks|kage|(?<!\w)vin(?!\w)|øl", text, re.IGNORECASE):
            return None, None, None
        return "ris", tier, None
    if _CHEESE.search(text) and not _CHEESE_EXCLUDE.search(text):
        tier = 1 if " eller " in text.lower() else 0
        return "ost", tier, None
    veg = _veg_type(text)
    if veg is not None:
        tier = 1 if " eller " in text.lower() else 0
        return "gront", tier, veg
    return None, None, None


def _is_minced_beef(text: str) -> bool:
    return bool(_MINCED_BEEF.search(text) and _BEEF_WORD.search(text))


def _beef_tier(text: str) -> int:
    if re.search(r"kødpakke|blandingskasse", text, re.IGNORECASE):
        return 2
    species = _species(text)
    # Grønt i farsen er stadig oksekød, men det er ikke rent kød.
    if re.search(r"grønt|grøntsager", text, re.IGNORECASE):
        return 1 if len(species) <= 2 else 2
    if len(species) >= 3:
        return 2
    if len(species) == 2:
        return 1
    return 0


def _chicken_tier(text: str) -> int | None:
    if _CHICKEN_WEAK.search(text):
        if re.search(r"nugget|burger|pålæg|paneret|krymmel", text, re.IGNORECASE):
            return 2
        return None
    return _species_tier(text, default=0)


def _species_tier(text: str, *, default: int) -> int:
    species = _species(text)
    if len(species) >= 3:
        return 2
    if len(species) == 2 or " eller " in text.lower():
        return max(default, 1)
    return default


def _species(text: str) -> list[str]:
    return [name for name, pattern in _SPECIES if pattern.search(text)]


def _veg_type(text: str) -> str | None:
    if _VEG_EXCLUDE.search(text):
        return None
    if re.search(r"kylling|skinke|reje|tun\b", text, re.IGNORECASE):
        return None
    matches = [name for name, pattern in _VEG_RULES if pattern.search(text)]
    # "Løg eller kartofler" er ikke en kartoffelpris.
    if len(matches) == 1:
        return matches[0]
    return None
