"""Fase 0: descarga de prueba de cuotas para evaluar la cobertura de cada fuente.

Guarda la respuesta cruda en data/raw/ e imprime un resumen. No es código de producción:
sirve para decidir fuentes antes de la Fase 1.

Uso:
    python scripts/fase0_descarga.py theoddsapi
    python scripts/fase0_descarga.py oddspapi --casas pinnacle bet365.es codere.es winamax.es
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean

import httpx
from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
DATA_RAW = RAIZ / "data" / "raw"

THE_ODDS_API_URL = "https://api.the-odds-api.com/v4"
THE_ODDS_API_SPORTS = ["soccer_spain_la_liga", "soccer_epl"]

ODDSPAPI_URL = "https://api.oddspapi.io/v4"
# IDs de torneo en OddsPapi: 8 = LaLiga, 17 = Premier League (según su documentación).
ODDSPAPI_TOURNAMENTS = "8,17"
ODDSPAPI_PAUSE_S = 2.0


# ---------------------------------------------------------------------------
# Cálculos (independientes de la red, cubiertos por tests)
# ---------------------------------------------------------------------------


def margin(prices: list[float]) -> float:
    """Margen de la casa en un mercado completo: sum(1/cuota) - 1."""
    return sum(1 / p for p in prices) - 1


def _market_prices(market: dict, totals_point: float | None = None) -> list[float] | None:
    outcomes = market.get("outcomes", [])
    if totals_point is not None:
        outcomes = [o for o in outcomes if o.get("point") == totals_point]
    prices = [o["price"] for o in outcomes if o.get("price", 0) > 1]
    return prices if len(prices) >= 2 else None


def summarize_the_odds_api(events: list[dict]) -> dict[str, dict]:
    """Resumen por casa: nº de eventos cubiertos y margen medio en 1X2 y Más/Menos 2.5."""
    stats: dict[str, dict] = defaultdict(lambda: {"events": 0, "h2h": [], "totals_2_5": []})
    for event in events:
        for book in event.get("bookmakers", []):
            s = stats[book["key"]]
            s["events"] += 1
            for market in book.get("markets", []):
                if market["key"] == "h2h":
                    prices = _market_prices(market)
                    if prices:
                        s["h2h"].append(margin(prices))
                elif market["key"] == "totals":
                    prices = _market_prices(market, totals_point=2.5)
                    if prices:
                        s["totals_2_5"].append(margin(prices))
    return {
        key: {
            "events": s["events"],
            "h2h_margin": mean(s["h2h"]) if s["h2h"] else None,
            "totals_2_5_margin": mean(s["totals_2_5"]) if s["totals_2_5"] else None,
        }
        for key, s in stats.items()
    }


def find_h2h_surebets(events: list[dict]) -> list[dict]:
    """Comprobación rápida: mejor cuota de cada resultado 1X2 entre casas; surebet si sum(1/best) < 1."""
    found = []
    for event in events:
        best: dict[str, tuple[float, str]] = {}
        for book in event.get("bookmakers", []):
            for market in book.get("markets", []):
                if market["key"] != "h2h":
                    continue
                for o in market.get("outcomes", []):
                    if o["name"] not in best or o["price"] > best[o["name"]][0]:
                        best[o["name"]] = (o["price"], book["key"])
        if len(best) < 3:  # fútbol: 1, X y 2
            continue
        total = sum(1 / price for price, _ in best.values())
        if total < 1:
            found.append(
                {
                    "event": f"{event.get('home_team')} - {event.get('away_team')}",
                    "commence_time": event.get("commence_time"),
                    "profit_pct": round((1 / total - 1) * 100, 2),
                    "legs": {name: {"price": p, "book": b} for name, (p, b) in best.items()},
                }
            )
    return found


# ---------------------------------------------------------------------------
# Descarga
# ---------------------------------------------------------------------------


def _save(name: str, payload: object) -> Path:
    DATA_RAW.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    path = DATA_RAW / f"{name}_{stamp}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return path


def _require_key(var: str) -> str:
    key = os.getenv(var)
    if not key:
        sys.exit(f"Falta {var} en .env (copia .env.example y rellénalo).")
    return key


def run_the_odds_api(regions: str) -> None:
    key = _require_key("ODDS_API_KEY")
    all_events: list[dict] = []
    with httpx.Client(timeout=30) as client:
        for sport in THE_ODDS_API_SPORTS:
            r = client.get(
                f"{THE_ODDS_API_URL}/sports/{sport}/odds",
                params={
                    "apiKey": key,
                    "regions": regions,
                    "markets": "h2h,totals",
                    "oddsFormat": "decimal",
                },
            )
            r.raise_for_status()
            events = r.json()
            path = _save(f"theoddsapi_{sport}", events)
            print(
                f"{sport}: {len(events)} eventos -> {path.relative_to(RAIZ)} "
                f"(créditos usados en la llamada: {r.headers.get('x-requests-last')}, "
                f"restantes: {r.headers.get('x-requests-remaining')})"
            )
            all_events.extend(events)

    print("\nCobertura y margen medio por casa:")
    print(f"{'casa':<22}{'eventos':>8}{'margen 1X2':>12}{'margen O/U2.5':>15}")
    summary = summarize_the_odds_api(all_events)
    for book, s in sorted(summary.items(), key=lambda kv: (kv[1]["h2h_margin"] or 9)):
        h2h = f"{s['h2h_margin'] * 100:.2f}%" if s["h2h_margin"] is not None else "-"
        tot = f"{s['totals_2_5_margin'] * 100:.2f}%" if s["totals_2_5_margin"] is not None else "-"
        print(f"{book:<22}{s['events']:>8}{h2h:>12}{tot:>15}")

    surebets = find_h2h_surebets(all_events)
    print(f"\nSurebets 1X2 aparentes en esta foto: {len(surebets)}")
    for sb in surebets:
        print(f"  {sb['event']}  +{sb['profit_pct']}%  {sb['legs']}")


def run_oddspapi(casas: list[str]) -> None:
    key = _require_key("ODDSPAPI_KEY")
    with httpx.Client(timeout=60) as client:
        r = client.get(f"{ODDSPAPI_URL}/bookmakers", params={"apiKey": key})
        r.raise_for_status()
        bookmakers = r.json()
        path = _save("oddspapi_bookmakers", bookmakers)
        print(f"Catálogo de casas -> {path.relative_to(RAIZ)}")
        es = sorted({s for s in _strings(bookmakers) if s.endswith(".es")})
        print(f"Slugs .es en el catálogo ({len(es)}): {', '.join(es) or 'ninguno detectado'}")

        for casa in casas:
            params = {"apiKey": key, "bookmaker": casa, "tournamentIds": ODDSPAPI_TOURNAMENTS}
            for _ in range(3):
                time.sleep(ODDSPAPI_PAUSE_S)  # la API limita peticiones por segundo (HTTP 429)
                r = client.get(f"{ODDSPAPI_URL}/odds-by-tournaments", params=params)
                if r.status_code != 429:
                    break
            if r.status_code != 200:
                print(f"{casa}: HTTP {r.status_code} {r.text[:200]}")
                continue
            path = _save(f"oddspapi_{casa.replace('.', '_')}", r.json())
            print(f"{casa}: OK -> {path.relative_to(RAIZ)} ({len(r.content) // 1024} KB)")
    print("\nEl formato de OddsPapi se analiza a mano con estos JSON antes de la Fase 1.")


def _strings(obj: object):
    """Todas las cadenas de un JSON anidado (para buscar slugs sin conocer el esquema)."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _strings(v)


def main() -> None:
    load_dotenv(RAIZ / ".env")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="fuente", required=True)

    p1 = sub.add_parser("theoddsapi", help="The Odds API (coste: 2 créditos por liga y región)")
    p1.add_argument("--regions", default="eu", help="eu, uk... (cada región multiplica el coste)")

    p2 = sub.add_parser("oddspapi", help="OddsPapi (1 petición por casa + 1 del catálogo)")
    p2.add_argument(
        "--casas",
        nargs="+",
        default=["pinnacle", "bet365.es", "codere.es", "winamax.es"],
        help="slugs de casa a descargar",
    )

    args = parser.parse_args()
    if args.fuente == "theoddsapi":
        run_the_odds_api(args.regions)
    else:
        run_oddspapi(args.casas)


if __name__ == "__main__":
    main()
