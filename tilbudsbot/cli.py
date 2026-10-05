"""Kommandolinje: ``python -m tilbudsbot``."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from typing import Any

from tilbudsbot import __version__
from tilbudsbot.config import ROOT, Settings, load_dotenv, resolve_chains
from tilbudsbot.fetch import FetchError, fetch_live, load_cache, save_cache
from tilbudsbot.fixture import load_fixture
from tilbudsbot.models import Offer, Report
from tilbudsbot.planner import build_plan
from tilbudsbot.staples import rank_staples
from tilbudsbot.summary import render_summary


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="tilbudsbot",
        description="Hent danske tilbudsaviser, find de bedste staples og skriv en madplan.",
        epilog=(
            "eksempler:\n"
            "  python -m tilbudsbot\n"
            "  python -m tilbudsbot --dry-run\n"
            "  python -m tilbudsbot --days 4 --people 3\n"
            "  python -m tilbudsbot --chains netto,rema,lidl\n"
            "  python -m tilbudsbot --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true", help="Brug fixtures/sample_offers.json og rør ikke netværket.")
    parser.add_argument("--days", type=int, default=5, choices=(4, 5), help="Dage i madplanen (4 eller 5).")
    parser.add_argument("--people", type=int, default=2, help="Personer i husholdningen (1–8).")
    parser.add_argument("--chains", default="", help="Komma-separeret: foetex,bilka,netto,rema,lidl,coop365.")
    parser.add_argument("--refresh", action="store_true", help="Ignorér frisk cache og hent igen.")
    parser.add_argument("--no-cache", action="store_true", help="Læs og skriv ikke cachen.")
    parser.add_argument("--json", action="store_true", help="Skriv maskinlæsbar JSON til stdout.")
    parser.add_argument("--quiet", action="store_true", help="Skjul fremdrift på stderr. Advarsler vises stadig.")
    parser.add_argument("--version", action="version", version=f"tilbudsbot {__version__}")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    load_dotenv(ROOT / ".env")
    try:
        args = parse_args(argv)
        chains = resolve_chains(args.chains)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.people < 1 or args.people > 8:
        print("Antal personer skal være mellem 1 og 8.", file=sys.stderr)
        return 1
    settings = Settings.from_env()
    try:
        loaded, code = _load(args, chains, settings)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    offers, report = loaded
    staples = rank_staples(offers)
    plan = build_plan(staples, days=args.days, people=args.people)
    text = render_summary(staples, plan, report)
    if args.json:
        json.dump(_payload(offers, staples, plan, report, text), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
    else:
        sys.stdout.write(text)
    return code


def _load(args: argparse.Namespace, chains, settings: Settings) -> tuple[tuple[list[Offer], Report], int]:
    if args.dry_run:
        _warn("Dry-run: bruger fixtures/sample_offers.json. Ingen live-priser.")
        return load_fixture(), 0

    def log(message: str) -> None:
        if not args.quiet:
            print(message, file=sys.stderr)

    if not args.no_cache and not args.refresh:
        cached = load_cache(settings, max_age=timedelta(hours=settings.cache_hours))
        if cached is not None:
            offers, report = cached
            report.mode = "cache"
            log(f"Bruger cache fra {report.fetched_at}. --refresh henter igen.")
            return (offers, report), 0
    try:
        offers, report = fetch_live(chains, settings, log=log)
    except FetchError as exc:
        _warn(str(exc))
        if not args.no_cache:
            stale = load_cache(settings, max_age=None)
            if stale is not None:
                offers, report = stale
                report.mode = "stale-cache"
                report.fallback_reason = str(exc)
                report.errors = list(report.errors) + list(exc.errors)
                _warn("Viser seneste cache. Priserne er ikke hentet i dag.")
                return (offers, report), 0
        offers, report = load_fixture()
        report.fallback_reason = str(exc)
        report.errors = list(exc.errors)
        _warn("Viser EKSEMPELDATA fra fixture. Priserne er ikke aktuelle.")
        return (offers, report), 2
    if not args.no_cache:
        save_cache(settings, offers, report)
    return (offers, report), 0


def _warn(message: str) -> None:
    print(message, file=sys.stderr)


def _payload(offers, staples, plan, report: Report, text: str) -> dict[str, Any]:
    return {
        "report": report.to_dict(),
        "offer_count": len(offers),
        "staples": {
            key: [_classified_dict(item) for item in items]
            for key, items in staples.items()
        },
        "plan": {
            "days": plan.days,
            "people": plan.people,
            "missing_proteins": list(plan.missing_proteins),
            "total": plan.total,
            "total_partial": plan.total_partial,
            "meals": [
                {
                    "day": meal.day_label,
                    "title": meal.title,
                    "note": meal.note,
                    "missing": list(meal.missing),
                    "uses": [
                        {
                            "offer_id": use.offer_id,
                            "role": use.role,
                            "grams": use.grams,
                            "pieces": use.pieces,
                        }
                        for use in meal.uses
                    ],
                }
                for meal in plan.meals
            ],
            "shopping": [
                {
                    "offer_id": line.offer_id,
                    "chain": line.chain,
                    "heading": line.heading,
                    "packs": line.packs,
                    "unit_price": line.unit_price,
                    "line_price": line.line_price,
                    "detail": line.detail,
                }
                for line in plan.shopping
            ],
        },
        "summary_da": text,
    }


def _classified_dict(item) -> dict[str, Any]:
    payload = item.offer.to_dict()
    payload.update(
        {
            "category": item.category,
            "tier": item.tier,
            "veg_type": item.veg_type,
            "comparable": item.comparable,
            "kr_low": item.kr_low,
            "kr_high": item.kr_high,
            "unit_label": item.unit_label,
            "url": item.offer.web_url(),
        }
    )
    return payload
