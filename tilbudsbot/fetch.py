"""Hent aktuelle tilbudsaviser fra Tjek/etilbudsavis.

Primær kilde er det offentlige JSON-API, som etilbudsavis.dk selv bruger.
Vi skraber ikke HTML og forsøger ikke at omgå en blokering. Hvis værten
svarer med fejl, prøver vi den anden offentlige vært, derefter seneste cache,
og til sidst det indlagte fixture.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from tilbudsbot.config import Chain, Settings
from tilbudsbot.models import CatalogNote, Offer, Report
from tilbudsbot.normalize import dealer_slug_from_catalog, offer_from_hotspot, offer_from_search

USER_AGENT = "tilbudsbot/0.1 (personlig madplan; offentlig tilbudsavis)"
Log = Callable[[str], None]

# Søgeord bruges kun, når en kædes katalog-hotspots ikke kan læses.
SEARCH_QUERIES = (
    "hakket oksekød",
    "kylling",
    "hakket gris",
    "kotelet",
    "flæsk",
    "pasta",
    "basmatiris",
    "skæreost",
    "kartofler",
    "gulerødder",
    "løg",
    "broccoli",
)

_SKIP_LABEL = ("nonfood", "elektronik", "prosonic", "tekstil", "ud af huset")


class FetchError(RuntimeError):
    def __init__(self, message: str, errors: list[str]):
        super().__init__(message)
        self.errors = errors


def fetch_live(
    chains: tuple[Chain, ...],
    settings: Settings,
    *,
    log: Log = lambda _message: None,
    now: datetime | None = None,
) -> tuple[list[Offer], Report]:
    """Hent tilbud. Kaster :class:`FetchError`, hvis ingen vært gav et eneste tilbud."""

    moment = now or datetime.now(timezone.utc)
    errors: list[str] = []
    bases = [settings.api_base]
    if settings.api_base_fallback and settings.api_base_fallback != settings.api_base:
        bases.append(settings.api_base_fallback)

    for base in bases:
        log(f"Henter kataloger fra {base}")
        try:
            offers, notes, base_errors, scanned = _fetch_from_base(base, chains, settings, moment, log)
        except FetchError as exc:
            errors.extend(exc.errors)
            log(f"Vært fejlede: {exc}")
            continue
        errors.extend(base_errors)
        if offers:
            report = Report(
                mode="live",
                fetched_at=moment.isoformat(),
                api_base=base,
                disclaimer=None,
                catalogs=notes,
                errors=errors,
                scanned=scanned,
                kept=len(offers),
            )
            return _dedupe(offers), report
    raise FetchError("Ingen tilbud hentet fra de offentlige Tjek-værter.", errors)


def catalog_is_useful(catalog: dict[str, Any], now: datetime) -> bool:
    """Behold aktuelle madkataloger med strukturerede tilbud."""

    try:
        offer_count = int(catalog.get("offer_count") or 0)
    except (TypeError, ValueError):
        offer_count = 0
    if offer_count <= 0:
        return False
    label = str(catalog.get("label") or "").lower()
    if any(token in label for token in _SKIP_LABEL):
        return False
    try:
        start = _parse_dt(str(catalog.get("run_from") or ""))
        end = _parse_dt(str(catalog.get("run_till") or ""))
    except ValueError:
        return False
    if end < now:
        return False
    if start > now + timedelta(hours=36):
        return False
    return True


def load_cache(settings: Settings, *, max_age: timedelta | None) -> tuple[list[Offer], Report] | None:
    path = settings.cache_dir / "offers.json"
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        fetched_at = _parse_dt(payload["fetched_at"])
    except (OSError, json.JSONDecodeError, KeyError, ValueError):
        return None
    if max_age is not None and datetime.now(timezone.utc) - fetched_at > max_age:
        return None
    offers = [Offer.from_dict(item) for item in payload.get("offers") or []]
    report = Report(
        mode=payload.get("mode") or "cache",
        fetched_at=payload["fetched_at"],
        api_base=payload.get("api_base"),
        disclaimer=payload.get("disclaimer"),
        catalogs=[CatalogNote.from_dict(item) for item in payload.get("catalogs") or []],
        errors=list(payload.get("errors") or []),
        scanned=int(payload.get("scanned") or len(offers)),
        kept=len(offers),
        fallback_reason=payload.get("fallback_reason"),
    )
    return offers, report


def save_cache(settings: Settings, offers: list[Offer], report: Report) -> None:
    settings.cache_dir.mkdir(parents=True, exist_ok=True)
    payload = report.to_dict()
    payload["offers"] = [offer.to_dict() for offer in offers]
    path = settings.cache_dir / "offers.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _fetch_from_base(
    base: str,
    chains: tuple[Chain, ...],
    settings: Settings,
    now: datetime,
    log: Log,
) -> tuple[list[Offer], list[CatalogNote], list[str], int]:
    offers: list[Offer] = []
    notes: list[CatalogNote] = []
    errors: list[str] = []
    scanned = 0
    for chain in chains:
        try:
            catalogs = _get_json(f"{base}/catalogs?dealer_id={urllib.parse.quote(chain.dealer_id)}", settings)
            _pause(settings)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            if _host_is_blocked(exc) and not offers:
                raise FetchError(f"{base} svarede ikke for {chain.name}: {_short_error(exc)}", [str(exc)]) from exc
            resolved = _resolve_dealer(base, chain, settings, errors)
            if resolved is None:
                errors.append(f"{chain.name}: kataloger kunne ikke hentes ({_short_error(exc)}).")
                offers.extend(_search_chain(base, chain, settings, errors, log))
                continue
            chain = resolved
            try:
                catalogs = _get_json(
                    f"{base}/catalogs?dealer_id={urllib.parse.quote(chain.dealer_id)}",
                    settings,
                )
                _pause(settings)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as retry_exc:
                errors.append(f"{chain.name}: kataloger kunne ikke hentes ({_short_error(retry_exc)}).")
                offers.extend(_search_chain(base, chain, settings, errors, log))
                continue
        if not isinstance(catalogs, list):
            errors.append(f"{chain.name}: uventet katalogsvar.")
            continue
        useful = [catalog for catalog in catalogs if isinstance(catalog, dict) and catalog_is_useful(catalog, now)]
        if not useful:
            errors.append(f"{chain.name}: ingen aktuel madavis med strukturerede tilbud.")
            offers.extend(_search_chain(base, chain, settings, errors, log))
            continue
        chain_offers = 0
        for catalog in useful:
            catalog_id = str(catalog.get("id") or "")
            label = str(catalog.get("label") or "")
            try:
                hotspots = _get_json(f"{base}/catalogs/{urllib.parse.quote(catalog_id)}/hotspots", settings)
                _pause(settings)
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
                errors.append(f"{chain.name} / {label}: hotspots fejlede ({_short_error(exc)}).")
                continue
            if not isinstance(hotspots, list):
                errors.append(f"{chain.name} / {label}: uventet hotspots-svar.")
                continue
            slug = dealer_slug_from_catalog(catalog)
            scanned += len(hotspots)
            for hotspot in hotspots:
                if not isinstance(hotspot, dict):
                    continue
                offer = offer_from_hotspot(
                    hotspot,
                    chain,
                    catalog_id=catalog_id,
                    catalog_label=label,
                    dealer_slug=slug,
                    source="live",
                )
                if offer is None:
                    continue
                offers.append(offer)
                chain_offers += 1
            notes.append(
                CatalogNote(
                    chain=chain.name,
                    label=label,
                    valid_from=str(catalog.get("run_from") or ""),
                    valid_to=str(catalog.get("run_till") or ""),
                    offer_count=int(catalog.get("offer_count") or 0),
                )
            )
            log(f"{chain.name}: {label} ({chain_offers} tilbud indtil videre)")
        if chain_offers == 0:
            offers.extend(_search_chain(base, chain, settings, errors, log))
    return offers, notes, errors, scanned


def _search_chain(
    base: str,
    chain: Chain,
    settings: Settings,
    errors: list[str],
    log: Log,
) -> list[Offer]:
    """Fallback: søg staples hos kæden, hvis hele avisen ikke kunne læses."""

    found: list[Offer] = []
    log(f"{chain.name}: søger staples, fordi avis-hotspots manglede")
    for query in SEARCH_QUERIES:
        params = urllib.parse.urlencode(
            {
                "query": query,
                "dealer_id": chain.dealer_id,
                "limit": 24,
                "offset": 0,
                "r_locale": "da_DK",
                "r_lat": settings.lat,
                "r_lng": settings.lng,
                "r_radius": settings.radius_m,
            }
        )
        try:
            payload = _get_json(f"{base}/offers/search?{params}", settings)
            _pause(settings)
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            errors.append(f"{chain.name}: søgning '{query}' fejlede ({_short_error(exc)}).")
            if _host_is_blocked(exc):
                break
            continue
        if not isinstance(payload, list):
            continue
        for raw in payload:
            if isinstance(raw, dict):
                offer = offer_from_search(raw, chain, source="live-search")
                if offer is not None:
                    found.append(offer)
    if not found:
        errors.append(f"{chain.name}: hverken avis eller søgning gav tilbud.")
    return found


def _resolve_dealer(base: str, chain: Chain, settings: Settings, errors: list[str]) -> Chain | None:
    params = urllib.parse.urlencode({"query": chain.search_name})
    try:
        payload = _get_json(f"{base}/dealers/search?{params}", settings)
        _pause(settings)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
        errors.append(f"{chain.name}: dealer-opslag fejlede ({_short_error(exc)}).")
        return None
    if not isinstance(payload, list):
        return None
    for dealer in payload:
        if not isinstance(dealer, dict):
            continue
        country = dealer.get("country") or {}
        country_id = country.get("id") if isinstance(country, dict) else None
        if country_id not in (None, "DK"):
            continue
        dealer_id = str(dealer.get("id") or "")
        if not dealer_id:
            continue
        from dataclasses import replace

        return replace(chain, dealer_id=dealer_id)
    return None


def _get_json(url: str, settings: Settings) -> Any:
    delay = 1.2
    last_error: Exception | None = None
    for attempt in range(2):
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
        try:
            with urllib.request.urlopen(request, timeout=settings.timeout_s) as response:
                body = response.read()
            return json.loads(body.decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code in {429, 500, 502, 503, 504} and attempt == 0:
                time.sleep(delay)
                continue
            raise
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError) as exc:
            last_error = exc
            if attempt == 0 and not isinstance(exc, json.JSONDecodeError):
                time.sleep(delay)
                continue
            raise
    if last_error:
        raise last_error
    raise RuntimeError(f"Tomt svar fra {url}")


def _host_is_blocked(exc: Exception) -> bool:
    if isinstance(exc, urllib.error.HTTPError) and exc.code in {401, 403, 429}:
        return True
    if isinstance(exc, urllib.error.URLError) and not isinstance(exc, urllib.error.HTTPError):
        return True
    return isinstance(exc, TimeoutError)


def _short_error(exc: Exception) -> str:
    text = str(exc).strip().splitlines()[0] if str(exc).strip() else exc.__class__.__name__
    return text[:180]


def _pause(settings: Settings) -> None:
    if settings.pause_s > 0:
        time.sleep(settings.pause_s)


def _parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _dedupe(offers: list[Offer]) -> list[Offer]:
    seen: set[tuple[str, str]] = set()
    unique: list[Offer] = []
    for offer in offers:
        key = (offer.chain_id, offer.id)
        if key in seen:
            continue
        seen.add(key)
        unique.append(offer)
    return unique
