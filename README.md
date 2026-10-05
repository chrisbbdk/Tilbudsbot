# tilbudsbot

Henter danske tilbudsaviser (føtex, Bilka, Netto, REMA 1000, Lidl og Coop 365), finder de bedste basisvarer og skriver en kort madplan.

Fetches Danish grocery offers, ranks staple foods, and writes a short meal plan.

Priser kommer kun fra en tilbudsavis: live fra det offentlige Tjek/etilbudsavis-API, eller fra `fixtures/sample_offers.json` ved `--dry-run`.

## Krav / Requirements

Python 3.10 eller nyere. Projektet bruger kun standardbiblioteket, så der er ingen `pip install`.

## Kør / Run

```bash
git clone https://github.com/chrisbbdk/tilbudsbot
cd tilbudsbot
python3 -m tilbudsbot --dry-run
```

`--dry-run` bruger fixture-filen og rører ikke netværket. Brug `python` i stedet for `python3`, hvis den kommando peger på Python 3.10+.

Uden `--dry-run` hentes aktuelle aviser. Cache ligger i `~/.cache/tilbudsbot` (6 timer). Valgfrie overrides kan sættes i miljøvariabler eller en `.env` i repo-roden (`TILBUDSBOT_LAT`, `TILBUDSBOT_LNG`, `TILBUDSBOT_API_BASE` og lignende). Der er ingen API-nøgle.

```bash
python -m tilbudsbot
python -m tilbudsbot --days 4 --people 3
python -m tilbudsbot --chains netto,rema,lidl
python -m tilbudsbot --json
./scripts/tilbud --dry-run
```

`--days` er 4 eller 5. `--people` er 1–8. Kædenøgler: `foetex`, `bilka`, `netto`, `rema`, `lidl`, `coop365`.
