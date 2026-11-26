"""CLV de las alertas ya jugadas: cuota avisada frente a la cuota justa de cierre de Pinnacle.

Usa /historical-odds, que no consume cupo.
"""

from __future__ import annotations

from datetime import datetime

from bot_apuestas.devig import edge, fair_prices_multiplicative, fair_prices_power
from bot_apuestas.estudio import MIN_VALID_PRICE, to_epoch


def closing_prices(history_market: dict, kickoff: float) -> dict[int, float]:
    """Última cuota activa de cada outcome antes del inicio."""
    out = {}
    for oid, odata in (history_market.get("outcomes") or {}).items():
        last = None
        for entry in (odata.get("players") or {}).get("0", []):
            if to_epoch(entry["createdAt"]) >= kickoff:
                continue
            if last is None or entry["createdAt"] > last["createdAt"]:
                last = entry
        if last and last.get("active") and (last.get("price") or 0) >= MIN_VALID_PRICE:
            out[int(oid)] = last["price"]
    return out


def compute_clv(price: float, outcome_id: int, closing: dict[int, float], n_outcomes: int):
    """(closing_fair, closing_fair_power, clv, clv_power) o Nones si el cierre está incompleto."""
    if len(closing) != n_outcomes or outcome_id not in closing:
        return None, None, None, None
    ids = list(closing)
    prices = [closing[i] for i in ids]
    i = ids.index(outcome_id)
    fm = fair_prices_multiplicative(prices)[i]
    fp = fair_prices_power(prices)[i]
    return fm, fp, edge(price, fm), edge(price, fp)


def update_clv(store, client, markets, reference: str, now: datetime, max_fixtures: int = 20) -> int:
    """Calcula el CLV de las alertas cuyo partido ya empezó. Devuelve cuántas se actualizaron."""
    pending = store.alerts_pending_clv(now)
    by_fixture: dict[str, list] = {}
    for a in pending:
        by_fixture.setdefault(a["fixture_id"], []).append(a)
    updated = 0
    for fid, alerts in list(by_fixture.items())[:max_fixtures]:
        payload = client.get("historical-odds", fixtureId=fid, bookmakers=reference) or {}
        ref_markets = (payload.get("bookmakers") or {}).get(reference, {}).get("markets", {})
        kickoff = to_epoch(alerts[0]["start_time"])
        for a in alerts:
            m = ref_markets.get(str(a["market_id"]), {})
            info = markets.get(a["market_id"])
            n = info.n_outcomes if info else 2
            store.set_clv(a["id"], *compute_clv(a["price"], a["outcome_id"],
                                                closing_prices(m, kickoff), n))
            updated += 1
    return updated
