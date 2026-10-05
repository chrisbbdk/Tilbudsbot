"""Kort dansk resumé til Telegram eller mail."""

from __future__ import annotations

from tilbudsbot.models import Offer, Report
from tilbudsbot.planner import Plan
from tilbudsbot.staples import CATEGORY_TITLES, Classified, beef_sections, highlights
from tilbudsbot.text import format_clock, format_kr, format_period, format_size, format_unit_price, role_name, short_heading

_MODE_LINE = {
    "live": "Kilde: live tilbudsavis via Tjek/etilbudsavis",
    "cache": "Kilde: lokal cache af seneste live-hentning",
    "stale-cache": "Kilde: forældet cache. Live-hentning fejlede, så tallene kan være gamle",
    "fixture": "Kilde: fixtures/sample_offers.json",
}


def render_summary(
    staples: dict[str, list[Classified]],
    plan: Plan,
    report: Report,
) -> str:
    offers = _index(staples)
    lines: list[str] = ["TILBUDSBOT", _MODE_LINE.get(report.mode, report.mode)]
    if report.mode == "fixture":
        lines.append(report.disclaimer or "Tallene er et fastfrosset udsnit, ikke dagens avis.")
        if report.fallback_reason:
            lines.append(f"Live-hentning fejlede: {report.fallback_reason}")
    elif report.mode == "stale-cache" and report.fallback_reason:
        lines.append(f"Live-hentning fejlede: {report.fallback_reason}")
    if report.fetched_at:
        lines.append(f"Hentet: {format_clock(report.fetched_at)} (dansk tid)")
    if report.api_base and report.mode != "fixture":
        lines.append(f"API: {report.api_base}")
    if report.catalogs:
        lines.append("Aviser:")
        for catalog in report.catalogs:
            period = format_period(catalog.valid_from, catalog.valid_to)
            label = catalog.label or "avis"
            extra = f" — {period}" if period else ""
            lines.append(f"  • {catalog.chain}: {label}{extra}")
    lines.append(
        "Aviser er kædens katalog, ikke lagerstatus i en bestemt butik. "
        f"Læst {report.scanned} tilbud, {report.kept} unikke i grundlaget."
    )
    lines.append("")
    lines.extend(_beef_block(staples.get("hakket_okse") or [], offers))
    for key in ("kylling", "gris", "pasta", "ris", "ost"):
        lines.extend(_category_block(key, staples.get(key) or []))
    lines.extend(_veg_block(staples.get("gront") or []))
    lines.append("")
    lines.extend(_plan_block(plan, offers))
    lines.append("")
    lines.extend(_shop_block(plan))
    if report.errors:
        lines.append("")
        lines.append("Bemærkninger fra hentningen:")
        for error in report.errors[:8]:
            lines.append(f"  • {error}")
        if len(report.errors) > 8:
            lines.append(f"  • … og {len(report.errors) - 8} mere")
    lines.append("")
    lines.append(
        "Kun priser fra tilbudsavis. Ingen hyldepriser er gættet. "
        "Tjek dato og den enkelte butik før du handler."
    )
    return "\n".join(lines).rstrip() + "\n"


def _beef_block(items: list[Classified], _offers: dict[str, Offer]) -> list[str]:
    pure, mixed = beef_sections(items)
    lines = ["HAKKET OKSEKØD"]
    if not pure and not mixed:
        lines.append("Ingen hakket oksekød i de læste aviser.")
        lines.append("")
        return lines
    if pure:
        lines.append("Rent hakket oksekød, laveste sikre kg-pris først:")
        lines.extend(_offer_lines(pure))
    else:
        lines.append("Ingen rent hakket oksekød med sikker kg-pris.")
    if mixed and pure:
        lines.append("Blandet alternativ, kun vist fordi kg-prisen er lavere end den rene vare:")
        lines.extend(_offer_lines(mixed))
    elif mixed:
        lines.append("Kun blandede varianter i avisen:")
        lines.extend(_offer_lines(mixed))
    lines.append("")
    return lines


def _category_block(key: str, items: list[Classified]) -> list[str]:
    title = CATEGORY_TITLES[key].upper()
    picked = highlights(items, limit=2)
    lines = [title]
    if not picked:
        lines.append("Ingen tilbud i de læste aviser.")
    else:
        lines.extend(_offer_lines(picked))
    lines.append("")
    return lines


def _veg_block(items: list[Classified]) -> list[str]:
    lines = ["GRØNT"]
    order = (
        "kartoffel",
        "løg",
        "gulerod",
        "broccoli",
        "peberfrugt",
        "tomat",
        "salat",
        "blomkål",
        "porre",
        "squash",
        "agurk",
        "kål",
        "hvidløg",
    )
    shown = 0
    seen_types: set[str] = set()
    for veg_type in order:
        pool = [item for item in items if item.veg_type == veg_type]
        picked = highlights(pool, limit=1)
        if not picked:
            continue
        seen_types.add(veg_type)
        lines.extend(_offer_lines(picked))
        shown += 1
        if shown >= 5:
            break
    if shown == 0:
        lines.append("Ingen kartofler, løg eller andet basalt grønt i de læste aviser.")
    lines.append("")
    return lines


def _offer_lines(items: list[Classified]) -> list[str]:
    lines: list[str] = []
    for item in items:
        offer = item.offer
        bits = [f"{offer.chain} — {short_heading(offer.chain, offer.heading)} — {format_kr(offer.price)}"]
        size = format_size(offer)
        if size:
            bits.append(size)
        unit = format_unit_price(offer)
        if unit:
            bits.append(unit)
        if item.tier > 0:
            bits.append("flere varianter")
        lines.append("• " + " — ".join(bits))
        period = format_period(offer.valid_from, offer.valid_to)
        meta = []
        if period:
            meta.append(f"Gyldig {period}")
        if offer.catalog_label:
            meta.append(offer.catalog_label)
        if meta:
            lines.append("  " + " · ".join(meta))
        url = offer.web_url()
        if url:
            lines.append(f"  {url}")
    return lines


def _plan_block(plan: Plan, offers: dict[str, Offer]) -> list[str]:
    lines = [f"MADPLAN · {plan.days} dage · {plan.people} personer"]
    if not plan.meals:
        lines.append("Ingen egnet kødtilbud med sikker kg-pris. Madplanen udelades, så der ikke opfindes en pris.")
        if plan.missing_proteins:
            lines.append("Mangler: " + ", ".join(plan.missing_proteins) + ".")
        return lines
    lines.append(
        "Bygget på det billigste egnede kød, der gælder alle dagene, når sådan et tilbud findes. "
        "Ren vare beholdes, medmindre en blanding er mindst 20 % billigere pr. kg. "
        "Gram er et skøn pr. person. Kroner er pakkepriser fra avisen."
    )
    if plan.missing_proteins:
        lines.append("Ikke brugt, fordi der ikke var et egnet tilbud: " + ", ".join(plan.missing_proteins) + ".")
    for meal in plan.meals:
        lines.append("")
        lines.append(f"{meal.day_label} — {meal.title}")
        for use in meal.uses:
            offer = offers.get(use.offer_id)
            if offer is None:
                continue
            unit = format_unit_price(offer)
            size = format_size(offer)
            price = format_kr(offer.price)
            detail = price if not size else f"{price} / {size}"
            if unit:
                detail = f"{detail} — {unit}"
            amount = ""
            if use.grams:
                amount = f"ca. {int(round(use.grams))} g"
            elif use.pieces:
                amount = f"ca. {use.pieces} stk"
            suffix = f" ({amount})" if amount else ""
            lines.append(
                f"  {role_name(use.role)}: {offer.chain} {short_heading(offer.chain, offer.heading)} — {detail}{suffix}"
            )
        if meal.missing:
            lines.append("  Ingen tilbudsavispris på: " + ", ".join(meal.missing) + ". Ikke talt med.")
        if meal.note:
            lines.append(f"  {meal.note}")
    return lines


def _shop_block(plan: Plan) -> list[str]:
    lines = ["INDKØB (kun varer med en avispris i planen)"]
    if not plan.shopping:
        lines.append("Ingen varer at købe ud fra planen.")
        return lines
    current = None
    for line in plan.shopping:
        if line.chain != current:
            current = line.chain
            lines.append(current)
        if line.packs is None or line.line_price is None:
            lines.append(
                f"  • {short_heading(line.chain, line.heading)} — {format_kr(line.unit_price)} — antal ikke beregnet"
            )
        else:
            lines.append(
                "  • "
                f"{line.packs} pk. {short_heading(line.chain, line.heading)} — "
                f"{format_kr(line.unit_price)} — {format_kr(line.line_price)}"
            )
        if line.detail:
            lines.append(f"    {line.detail}")
    if plan.total is None:
        lines.append("Sum udeladt: ingen linje havde både pris og pakkestørrelse.")
    elif plan.total_partial:
        lines.append(f"Delvis sum (linjer uden pakkestørrelse er ikke med): {format_kr(plan.total)}")
    else:
        lines.append(f"I alt: {format_kr(plan.total)}")
    return lines


def _index(staples: dict[str, list[Classified]]) -> dict[str, Offer]:
    found: dict[str, Offer] = {}
    for items in staples.values():
        for item in items:
            found[item.offer.id] = item.offer
    return found
