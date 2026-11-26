"""Fase 0.5: reconstrucción de oportunidades de value betting a partir del histórico de cuotas.

Idea: en cada instante antes del partido, la cuota de una casa blanda se compara con la cuota
justa de Pinnacle (sin margen) en ese mismo instante. Un intervalo continuo con
edge >= umbral es una "oportunidad". Para cada una se mide cuánto dura y su CLV frente a la
cuota justa de cierre de Pinnacle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from bot_apuestas.devig import edge, fair_prices_multiplicative, fair_prices_power

MIN_VALID_PRICE = 1.011  # 1.01 suele ser un marcador de mercado suspendido

# Historial de un outcome: [(epoch_s, price, active, stake_limit)], en orden cronológico.
History = list[tuple[float, float, bool, float | None]]


@dataclass
class Opportunity:
    outcome_id: int
    start: float  # epoch s
    end: float
    price: float  # cuota de la casa blanda al empezar
    fair_at_start: float
    edge_at_start: float
    max_edge: float
    pin_limit: float | None
    closing_fair: float | None
    kickoff: float
    closing_prices: list[float] | None = None  # cuotas de cierre de Pinnacle (con margen)
    closing_index: int | None = None  # posición de este outcome en closing_prices

    @property
    def duration_s(self) -> float:
        return self.end - self.start

    @property
    def hours_before_kickoff(self) -> float:
        return (self.kickoff - self.start) / 3600

    @property
    def clv(self) -> float | None:
        """Valor esperado frente al cierre: price / cuota justa de cierre - 1."""
        return None if self.closing_fair is None else edge(self.price, self.closing_fair)

    @property
    def clv_power(self) -> float | None:
        """CLV con devig power (más conservador en cuotas altas)."""
        if self.closing_prices is None or self.closing_index is None:
            return None
        fair = fair_prices_power(self.closing_prices)[self.closing_index]
        return edge(self.price, fair)


def to_epoch(ts: str) -> float:
    return datetime.fromisoformat(ts).timestamp()


def _fair(state: dict[int, tuple[float, bool, float | None]], n_outcomes: int) -> dict[int, float]:
    if len(state) != n_outcomes:
        return {}
    if not all(active and price >= MIN_VALID_PRICE for price, active, _ in state.values()):
        return {}
    ids = list(state)
    fairs = fair_prices_multiplicative([state[i][0] for i in ids])
    return dict(zip(ids, fairs))


def find_opportunities(
    pinnacle: dict[int, History],
    soft: dict[int, History],
    kickoff: float,
    n_outcomes: int,
    threshold: float,
) -> list[Opportunity]:
    """Intervalos (antes del partido) en los que la casa blanda supera la cuota justa en >= threshold."""
    events: list[tuple[float, str, int, float, bool, float | None]] = []
    for src, data in (("pin", pinnacle), ("soft", soft)):
        for oid, hist in data.items():
            events.extend((t, src, oid, p, a, lim) for t, p, a, lim in hist if t < kickoff)
    events.sort(key=lambda e: e[0])

    pin_state: dict[int, tuple[float, bool, float | None]] = {}
    soft_state: dict[int, tuple[float, bool]] = {}
    open_opps: dict[int, Opportunity] = {}
    closed: list[Opportunity] = []

    def evaluate(t: float) -> None:
        fair = _fair(pin_state, n_outcomes)
        for oid in set(open_opps) | set(soft_state):
            e = None
            if oid in fair and oid in soft_state:
                price, active = soft_state[oid]
                if active and price >= MIN_VALID_PRICE:
                    e = edge(price, fair[oid])
            if e is not None and e >= threshold:
                if oid in open_opps:
                    open_opps[oid].max_edge = max(open_opps[oid].max_edge, e)
                else:
                    open_opps[oid] = Opportunity(
                        outcome_id=oid, start=t, end=kickoff, price=soft_state[oid][0],
                        fair_at_start=fair[oid], edge_at_start=e, max_edge=e,
                        pin_limit=pin_state[oid][2], closing_fair=None, kickoff=kickoff,
                    )
            elif oid in open_opps:
                opp = open_opps.pop(oid)
                opp.end = t
                closed.append(opp)

    i = 0
    while i < len(events):
        t = events[i][0]
        while i < len(events) and events[i][0] == t:  # aplicar todos los cambios simultáneos
            _, src, oid, p, a, lim = events[i]
            if src == "pin":
                pin_state[oid] = (p, a, lim)
            else:
                soft_state[oid] = (p, a)
            i += 1
        evaluate(t)

    closed.extend(open_opps.values())  # siguen abiertas al empezar el partido
    closing = _fair(pin_state, n_outcomes)
    ids = list(pin_state)
    for opp in closed:
        opp.closing_fair = closing.get(opp.outcome_id)
        if closing and opp.outcome_id in ids:
            opp.closing_prices = [pin_state[i][0] for i in ids]
            opp.closing_index = ids.index(opp.outcome_id)
    return sorted(closed, key=lambda o: o.start)


def catch_probability(duration_s: float, poll_interval_s: float, reaction_s: float) -> float:
    """Probabilidad de detectar y apostar a tiempo consultando cada poll_interval_s.

    La primera consulta tras abrirse la oportunidad cae uniforme en [0, poll); hay que
    llegar a apostar (reacción) antes de que se cierre.
    """
    if poll_interval_s <= 0:
        return 1.0 if duration_s > reaction_s else 0.0
    return min(1.0, max(0.0, (duration_s - reaction_s) / poll_interval_s))


def expected_bets_and_ev(
    opps: list[Opportunity], poll_interval_s: float, reaction_s: float, use_power: bool = False
) -> tuple[float, float]:
    """Para las oportunidades de UNA selección: (nº esperado de apuestas <= 1, EV esperado por unidad).

    use_power=True valora con el CLV del devig power (más conservador).

    Se apuesta como mucho una vez por selección: en la primera oportunidad que se detecte.
    """
    not_yet = 1.0
    ev = 0.0
    for opp in opps:
        clv = opp.clv_power if use_power else opp.clv
        if clv is None:
            continue
        p = catch_probability(opp.duration_s, poll_interval_s, reaction_s)
        ev += not_yet * p * clv
        not_yet *= 1 - p
    return 1 - not_yet, ev


@dataclass
class Surebet:
    start: float
    end: float
    profit: float  # beneficio garantizado sobre el total apostado: 1/sum(1/cuota) - 1
    max_profit: float
    legs: dict[int, tuple[str, float]]  # outcome_id -> (casa, cuota) al empezar
    kickoff: float

    @property
    def duration_s(self) -> float:
        return self.end - self.start

    @property
    def hours_before_kickoff(self) -> float:
        return (self.kickoff - self.start) / 3600


def find_surebets(
    books: dict[str, dict[int, History]],
    kickoff: float,
    n_outcomes: int,
    max_market_age_s: float | None = None,
) -> list[Surebet]:
    """Intervalos antes del partido en los que la mejor cuota de cada resultado, cada una en su
    casa, cumple sum(1/cuota) < 1.

    max_market_age_s: ignora las cuotas de una casa cuyo mercado lleva más de ese tiempo sin
    ningún cambio (probable cuota desfasada).
    """
    events = []
    for book, outcomes in books.items():
        for oid, hist in outcomes.items():
            events.extend((t, book, oid, p, a) for t, p, a, _ in hist if t < kickoff)
    events.sort(key=lambda e: e[0])

    state: dict[str, dict[int, tuple[float, bool]]] = {}
    last_change: dict[str, float] = {}
    current: Surebet | None = None
    found: list[Surebet] = []

    def best_prices(t: float) -> dict[int, tuple[str, float]]:
        best: dict[int, tuple[str, float]] = {}
        for book, outs in state.items():
            if max_market_age_s is not None and t - last_change[book] > max_market_age_s:
                continue
            for oid, (price, active) in outs.items():
                if active and price >= MIN_VALID_PRICE and (oid not in best or price > best[oid][1]):
                    best[oid] = (book, price)
        return best

    def close(t: float) -> None:
        nonlocal current
        if current is not None:
            current.end = t
            found.append(current)
            current = None

    def evaluate(t: float) -> None:
        nonlocal current
        best = best_prices(t)
        if len(best) == n_outcomes and len({b for b, _ in best.values()}) > 1:
            total = sum(1 / p for _, p in best.values())
            if total < 1:
                profit = 1 / total - 1
                if current is None:
                    current = Surebet(t, kickoff, profit, profit, dict(best), kickoff)
                else:
                    current.max_profit = max(current.max_profit, profit)
                return
        close(t)

    i = 0
    while i < len(events):
        t = events[i][0]
        while i < len(events) and events[i][0] == t:
            _, book, oid, p, a = events[i]
            state.setdefault(book, {})[oid] = (p, a)
            last_change[book] = t
            i += 1
        evaluate(t)
    if current is not None:
        found.append(current)  # sigue abierta al empezar el partido
    return found
