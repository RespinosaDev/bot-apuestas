"""Detección de value bets en una foto de cuotas: casa blanda frente a Pinnacle sin margen."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from bot_apuestas.catalog import MarketInfo, is_surebet_market, is_target_market
from bot_apuestas.devig import edge, fair_prices_multiplicative, fair_prices_power

MIN_VALID_PRICE = 1.011


@dataclass(frozen=True)
class Quote:
    price: float
    changed_at: str | None
    limit: float | None


@dataclass
class FixtureOdds:
    fixture_id: str
    home: str
    away: str
    start: datetime
    tournament_id: int
    # bookmaker -> market_id -> outcome_id -> Quote (solo cotizaciones activas y válidas)
    books: dict[str, dict[int, dict[int, Quote]]]
    links: dict[str, str]
    # Mercados que OddsPapi marca marketActive=false aunque sus cuotas estén activas.
    # No es fiable (la mitad de Winamax/Codere sale así); se avisa en vez de descartar.
    flagged_markets: dict[str, set[int]] = field(default_factory=dict)


@dataclass
class ValueBet:
    fixture: FixtureOdds
    bookmaker: str
    market: MarketInfo
    outcome_id: int
    price: float
    fair: float
    fair_power: float
    edge: float
    edge_power: float
    ref_limit: float | None
    hours_to_kickoff: float
    market_flagged: bool = False
    quote_age_h: float | None = None  # horas desde el último cambio de la cuota de la casa

    @property
    def key(self) -> tuple[str, str, int, int]:
        return (self.fixture.fixture_id, self.bookmaker, self.market.market_id, self.outcome_id)


def parse_odds_payload(
    payload: list[dict], bookmaker: str, participants: dict[int, str],
    into: dict[str, FixtureOdds] | None = None,
) -> dict[str, FixtureOdds]:
    """Convierte la respuesta de /odds-by-tournaments de una casa y la añade a `into`."""
    fixtures = into if into is not None else {}
    for fx in payload:
        fid = fx["fixtureId"]
        if fid not in fixtures:
            fixtures[fid] = FixtureOdds(
                fixture_id=fid,
                home=participants.get(fx["participant1Id"], str(fx["participant1Id"])),
                away=participants.get(fx["participant2Id"], str(fx["participant2Id"])),
                start=datetime.fromisoformat(fx["startTime"]),
                tournament_id=fx.get("tournamentId"),
                books={},
                links={},
            )
        bdata = (fx.get("bookmakerOdds") or {}).get(bookmaker)
        if not bdata or bdata.get("suspended") or not bdata.get("bookmakerIsActive", True):
            continue
        markets: dict[int, dict[int, Quote]] = {}
        flagged: set[int] = set()
        for mid, mdata in (bdata.get("markets") or {}).items():
            outcomes = {}
            for oid, odata in (mdata.get("outcomes") or {}).items():
                q = (odata.get("players") or {}).get("0") or {}
                price = q.get("price")
                if q.get("active") and price and price >= MIN_VALID_PRICE:
                    outcomes[int(oid)] = Quote(price, q.get("changedAt"), q.get("limit"))
            if outcomes:
                markets[int(mid)] = outcomes
                if mdata.get("marketActive") is False:
                    flagged.add(int(mid))
        fixtures[fid].books[bookmaker] = markets
        fixtures[fid].flagged_markets[bookmaker] = flagged
        if bdata.get("fixturePath"):
            fixtures[fid].links[bookmaker] = bdata["fixturePath"]
    return fixtures


def _age_hours(changed_at: str | None, now: datetime) -> float | None:
    if not changed_at:
        return None
    return (now - datetime.fromisoformat(changed_at)).total_seconds() / 3600


def find_value_bets(
    fixtures: dict[str, FixtureOdds],
    markets: dict[int, MarketInfo],
    reference: str,
    books: list[str],
    now: datetime,
    min_edge: float,
    max_edge: float,
    min_hours: float,
    max_hours: float,
    max_market_age_h: float | None = None,
) -> list[ValueBet]:
    """max_market_age_h: descarta mercados de la casa sin ningún cambio en ese tiempo
    (probables cuotas desfasadas que ya no están en la web; ver docs/estudio_viabilidad.md)."""
    found = []
    for fx in fixtures.values():
        hours = (fx.start - now).total_seconds() / 3600
        if not min_hours <= hours <= max_hours:
            continue
        ref = fx.books.get(reference, {})
        for mid, ref_outcomes in ref.items():
            info = markets.get(mid)
            if info is None or not is_target_market(info) or len(ref_outcomes) != info.n_outcomes:
                continue
            ids = list(ref_outcomes)
            prices = [ref_outcomes[i].price for i in ids]
            fair = dict(zip(ids, fair_prices_multiplicative(prices)))
            fair_pow = dict(zip(ids, fair_prices_power(prices)))
            for book in books:
                soft = fx.books.get(book, {}).get(mid, {})
                ages = [a for q in soft.values() if (a := _age_hours(q.changed_at, now)) is not None]
                if max_market_age_h is not None and ages and min(ages) > max_market_age_h:
                    continue
                for oid, q in soft.items():
                    if oid not in fair:
                        continue
                    e = edge(q.price, fair[oid])
                    if min_edge <= e <= max_edge:
                        found.append(ValueBet(
                            fixture=fx, bookmaker=book, market=info, outcome_id=oid,
                            price=q.price, fair=fair[oid], fair_power=fair_pow[oid], edge=e,
                            edge_power=edge(q.price, fair_pow[oid]),
                            ref_limit=ref_outcomes[oid].limit, hours_to_kickoff=hours,
                            market_flagged=mid in fx.flagged_markets.get(book, set()),
                            quote_age_h=_age_hours(q.changed_at, now),
                        ))
    return sorted(found, key=lambda v: -v.edge)


@dataclass
class LiveSurebet:
    fixture: FixtureOdds
    market: MarketInfo
    legs: dict[int, tuple[str, float]]  # outcome_id -> (casa, cuota)
    profit: float  # beneficio garantizado sobre el total apostado
    hours_to_kickoff: float
    flagged_books: set[str] = field(default_factory=set)  # casas con marketActive=false

    @property
    def key(self) -> tuple[str, int]:
        return (self.fixture.fixture_id, self.market.market_id)

    def stakes(self, total: float) -> dict[int, float]:
        """Reparto del total para cobrar lo mismo salga lo que salga."""
        inv = {oid: 1 / price for oid, (_, price) in self.legs.items()}
        s = sum(inv.values())
        return {oid: total * v / s for oid, v in inv.items()}

    def payout(self, total: float) -> float:
        return total * (1 + self.profit)


def find_surebets_live(
    fixtures: dict[str, FixtureOdds],
    markets: dict[int, MarketInfo],
    books: list[str],
    now: datetime,
    min_profit: float,
    max_profit: float,
    min_hours: float,
    max_hours: float,
    max_market_age_h: float | None = None,
) -> list[LiveSurebet]:
    """Mejor cuota de cada resultado entre casas; surebet si sum(1/cuota) < 1 con >= 2 casas."""
    found = []
    for fx in fixtures.values():
        hours = (fx.start - now).total_seconds() / 3600
        if not min_hours <= hours <= max_hours:
            continue
        market_ids = {mid for b in books for mid in fx.books.get(b, {})}
        for mid in market_ids:
            info = markets.get(mid)
            if info is None or not is_surebet_market(info):
                continue
            best: dict[int, tuple[str, float]] = {}
            for book in books:
                soft = fx.books.get(book, {}).get(mid, {})
                ages = [a for q in soft.values() if (a := _age_hours(q.changed_at, now)) is not None]
                if max_market_age_h is not None and ages and min(ages) > max_market_age_h:
                    continue
                for oid, q in soft.items():
                    if oid not in best or q.price > best[oid][1]:
                        best[oid] = (book, q.price)
            if len(best) != info.n_outcomes or len({b for b, _ in best.values()}) < 2:
                continue
            total = sum(1 / p for _, p in best.values())
            profit = 1 / total - 1
            if min_profit <= profit <= max_profit:
                found.append(LiveSurebet(
                    fixture=fx, market=info, legs=best, profit=profit, hours_to_kickoff=hours,
                    flagged_books={b for b, _ in best.values()
                                   if mid in fx.flagged_markets.get(b, set())},
                ))
    return sorted(found, key=lambda s: -s.profit)
