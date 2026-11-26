"""Catálogos de OddsPapi (mercados y equipos) cacheados en disco: 1 petición cada uno por semana."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

from bot_apuestas.oddspapi import OddsPapiClient

MAX_AGE_S = 7 * 24 * 3600
FOOTBALL = 10


@dataclass(frozen=True)
class MarketInfo:
    market_id: int
    name: str
    handicap: float
    n_outcomes: int
    outcome_names: dict[int, str]


def _cached(path: Path, fetch) -> object:
    if path.exists() and time.time() - path.stat().st_mtime < MAX_AGE_S:
        return json.loads(path.read_text("utf-8"))
    data = fetch()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return data


def load_markets(client: OddsPapiClient, cache_dir: Path) -> dict[int, MarketInfo]:
    raw = _cached(cache_dir / "markets_football.json",
                  lambda: client.get("markets", sportId=FOOTBALL))
    return {
        m["marketId"]: MarketInfo(
            market_id=m["marketId"],
            name=m["marketName"],
            handicap=m["handicap"],
            n_outcomes=m["marketLength"],
            outcome_names={o["outcomeId"]: o["outcomeName"] for o in m["outcomes"]},
        )
        for m in raw
    }


def load_participants(client: OddsPapiClient, cache_dir: Path) -> dict[int, str]:
    raw = _cached(cache_dir / "participants_football.json",
                  lambda: client.get("participants", sportId=FOOTBALL))
    return {int(k): v for k, v in raw.items()}


def is_target_market(m: MarketInfo) -> bool:
    """Mercados con CLV positivo en el estudio: Ambos marcan y Más/Menos con línea .5."""
    if m.market_id == 104:
        return True
    return m.name == "Over Under Full Time" and m.handicap % 1 == 0.5


def is_surebet_market(m: MarketInfo) -> bool:
    """Para surebets también vale el 1X2: no depende de la referencia de Pinnacle."""
    return m.market_id == 101 or is_target_market(m)


def selection_label(m: MarketInfo, outcome_id: int, home: str = "local", away: str = "visitante") -> str:
    out = m.outcome_names.get(outcome_id, str(outcome_id))
    if m.market_id == 101:
        return {"1": f"Gana {home}", "X": "Empate", "2": f"Gana {away}"}.get(out, out)
    if m.market_id == 104:
        return f"Ambos marcan: {'Sí' if out == 'Yes' else 'No'}"
    if m.name == "Over Under Full Time":
        return f"{'Más' if out == 'Over' else 'Menos'} de {m.handicap:g} goles"
    return f"{m.name}: {out}"
