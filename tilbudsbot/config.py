"""Kæder, standardindstillinger og læsning af en valgfri .env-fil."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "fixtures" / "sample_offers.json"

# Dealer-id'er slået op 2026-10-05 via
# GET https://api.etilbudsavis.dk/v2/dealers/search?query=<kæde>
# Coop 365 hedder 365discount hos Tjek/etilbudsavis.
DEFAULT_API_BASE = "https://api.etilbudsavis.dk/v2"
DEFAULT_API_FALLBACK = "https://squid-api.tjek.com/v2"

# København. Katalogerne er kædernes tilbudsaviser, ikke en enkelt butiks hylde.
# Koordinaterne bruges kun i søge-fallback, som er geografisk.
DEFAULT_LAT = 55.6761
DEFAULT_LNG = 12.5683
DEFAULT_RADIUS_M = 20_000


@dataclass(frozen=True)
class Chain:
    """En dagligvarekæde vi henter avis for."""

    key: str
    name: str
    dealer_id: str
    search_name: str
    aliases: tuple[str, ...]


CHAINS: tuple[Chain, ...] = (
    Chain("foetex", "føtex", "bdf5A", "føtex", ("føtex", "fotex", "foetex")),
    Chain("bilka", "Bilka", "93f13", "Bilka", ("bilka",)),
    Chain("netto", "Netto", "9ba51", "Netto", ("netto",)),
    Chain("rema", "REMA 1000", "11deC", "REMA 1000", ("rema", "rema1000", "rema 1000")),
    Chain("lidl", "Lidl", "71c90", "Lidl", ("lidl",)),
    Chain(
        "coop365",
        "Coop 365",
        "DWZE1w",
        "365discount",
        ("coop365", "coop 365", "365discount", "365", "coop"),
    ),
)


def resolve_chains(raw: str | None) -> tuple[Chain, ...]:
    """Returner de valgte kæder. Tom streng betyder alle seks."""

    if raw is None or not raw.strip():
        return CHAINS
    wanted = [part.strip().lower() for part in raw.split(",") if part.strip()]
    if not wanted:
        return CHAINS
    chosen: list[Chain] = []
    unknown: list[str] = []
    for token in wanted:
        match = next((chain for chain in CHAINS if token == chain.key or token in chain.aliases), None)
        if match is None:
            unknown.append(token)
        elif match not in chosen:
            chosen.append(match)
    if unknown:
        known = ", ".join(chain.key for chain in CHAINS)
        raise ValueError(f"Ukendt kæde: {', '.join(unknown)}. Brug: {known}")
    return tuple(chosen)


@dataclass(frozen=True)
class Settings:
    """Kørselsindstillinger. Miljøvariabler overskriver standarderne."""

    api_base: str = DEFAULT_API_BASE
    api_base_fallback: str = DEFAULT_API_FALLBACK
    lat: float = DEFAULT_LAT
    lng: float = DEFAULT_LNG
    radius_m: int = DEFAULT_RADIUS_M
    timeout_s: float = 25.0
    pause_s: float = 0.12
    cache_hours: float = 6.0
    cache_dir: Path = Path.home() / ".cache" / "tilbudsbot"

    @classmethod
    def from_env(cls) -> Settings:
        defaults = cls()
        return cls(
            api_base=_env_str("TILBUDSBOT_API_BASE", defaults.api_base).rstrip("/"),
            api_base_fallback=_env_str("TILBUDSBOT_API_BASE_FALLBACK", defaults.api_base_fallback).rstrip("/"),
            lat=_env_float("TILBUDSBOT_LAT", defaults.lat),
            lng=_env_float("TILBUDSBOT_LNG", defaults.lng),
            radius_m=_env_int("TILBUDSBOT_RADIUS_M", defaults.radius_m),
            timeout_s=_env_float("TILBUDSBOT_TIMEOUT", defaults.timeout_s),
            pause_s=_env_float("TILBUDSBOT_PAUSE_S", defaults.pause_s),
            cache_hours=_env_float("TILBUDSBOT_CACHE_HOURS", defaults.cache_hours),
            cache_dir=Path(_env_str("TILBUDSBOT_CACHE_DIR", str(defaults.cache_dir))).expanduser(),
        )


def load_dotenv(path: Path) -> None:
    """Læs KEY=VALUE ind i os.environ uden at overskrive eksisterende variabler.

    Der er ingen API-nøgle. Filen er kun til valgfrie overrides.
    """

    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def _env_str(name: str, default: str) -> str:
    value = os.environ.get(name)
    return default if value is None or value.strip() == "" else value.strip()


def _env_float(name: str, default: float) -> float:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return float(value)


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return int(value)
