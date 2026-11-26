"""¿El CLV del estudio viene de cuotas "congeladas" (desfasadas) de las casas blandas?

Para cada oportunidad mide la antigüedad de la cuota de la casa blanda al abrirse:
- edad del outcome: tiempo desde el último cambio registrado de ESA cuota
- edad del mercado: tiempo desde el último cambio de CUALQUIER cuota de ese mercado en la casa
  (si nada del mercado se mueve en días, probablemente ya no se ofrece en la web)

y compara el CLV y el beneficio esperado por tramos de antigüedad.

Uso:
    python scripts/estudio_frescura.py
"""

from __future__ import annotations

import sqlite3
import statistics as st
from bisect import bisect_right
from collections import defaultdict
from pathlib import Path

from estudio_analisis import (
    DB_PATH,
    MATCHES_PER_MONTH,
    REACTION_S,
    SCENARIO_MARKETS,
    STAKE_EUR,
    histories,
    load_catalog,
    market_group,
)

from bot_apuestas.estudio import expected_bets_and_ev, find_opportunities, to_epoch

RAIZ = Path(__file__).resolve().parent.parent
REPORT = RAIZ / "docs" / "estudio_frescura_datos.md"
BOOKS = ["winamax.es", "codere.es", "bet365.es", "bwin.es"]
THRESHOLD = 0.03
POLL_S = 30 * 60
MAX_FRESH_H = 24
SCENARIOS = [("winamax.es", "codere.es"), ("winamax.es", "codere.es", "bet365.es"),
             ("winamax.es", "codere.es", "bet365.es", "bwin.es"), ("codere.es", "bet365.es"),
             ("codere.es", "bet365.es", "bwin.es")]
BUCKETS = [(0, 1, "< 1 h"), (1, 6, "1-6 h"), (6, 24, "6-24 h"), (24, 72, "1-3 días"),
           (72, 1e9, "> 3 días")]


def bucket(hours: float) -> str:
    return next(name for lo, hi, name in BUCKETS if lo <= hours < hi)


def last_change_before(times: list[float], t: float) -> float | None:
    i = bisect_right(times, t)
    return times[i - 1] if i else None


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    names, lengths = load_catalog()
    fixtures = db.execute(
        """SELECT f.fixture_id, f.start_time FROM fixtures f WHERE f.status_id = 2
           AND (SELECT COUNT(*) FROM downloaded d WHERE d.fixture_id = f.fixture_id) = 2"""
    ).fetchall()

    # (book, tipo_edad, tramo) -> selección -> [Opportunity]
    groups: dict[tuple, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))
    coverage: dict[str, set] = defaultdict(set)
    raw_ages = defaultdict(list)
    fresh: dict[str, dict[tuple, list]] = defaultdict(lambda: defaultdict(list))

    for fid, start in fixtures:
        kickoff = to_epoch(start)
        rows = db.execute(
            """SELECT bookmaker, market_id, outcome_id, ts, price, stake_limit, active
               FROM odds WHERE fixture_id = ? AND bookmaker IN (?,?,?,?,?)""",
            (fid, "pinnacle", *BOOKS),
        ).fetchall()
        h = histories(rows)
        pin = h.get("pinnacle", {})
        for book in BOOKS:
            for mid, soft in h.get(book, {}).items():
                if market_group(mid, names) not in SCENARIO_MARKETS or mid not in pin:
                    continue
                coverage[book].add(fid)
                outcome_times = {oid: [e[0] for e in hist] for oid, hist in soft.items()}
                market_times = sorted(t for ts in outcome_times.values() for t in ts)
                for o in find_opportunities(pin[mid], soft, kickoff, lengths[mid], THRESHOLD):
                    if o.edge_at_start > 0.30 or o.clv is None:
                        continue
                    own = last_change_before(outcome_times[o.outcome_id], o.start)
                    mkt = last_change_before(market_times, o.start)
                    if own is None or mkt is None:
                        continue
                    age_own = (o.start - own) / 3600
                    age_mkt = (o.start - mkt) / 3600
                    raw_ages[book].append(age_mkt)
                    sel = (fid, mid, o.outcome_id)
                    groups[(book, "outcome", bucket(age_own))][sel].append(o)
                    groups[(book, "mercado", bucket(age_mkt))][sel].append(o)
                    if age_mkt < MAX_FRESH_H:
                        fresh[book][sel].append(o)

    def summarize(sels: dict, book: str) -> tuple[int, float, float, float, float]:
        flat = [o for os_ in sels.values() for o in os_]
        k = MATCHES_PER_MONTH / max(len(coverage[book]), 1)
        ev_m = sum(expected_bets_and_ev(os_, POLL_S, REACTION_S)[1] for os_ in sels.values())
        ev_p = sum(expected_bets_and_ev(os_, POLL_S, REACTION_S, use_power=True)[1]
                   for os_ in sels.values())
        return (len(sels), st.mean(o.clv for o in flat),
                st.mean(o.clv_power for o in flat if o.clv_power is not None),
                ev_m * k * STAKE_EUR, ev_p * k * STAKE_EUR)

    lines = [
        "# ¿Cuotas desfasadas? CLV según la antigüedad de la cuota (generado automáticamente)",
        "",
        (f"Edge ≥ {THRESHOLD:.0%}, mercados {', '.join(SCENARIO_MARKETS)}, consulta cada 30 min, "
        f"{STAKE_EUR} €/apuesta."),
        "",
        "- **Edad del outcome**: horas desde el último cambio de esa cuota al abrirse la oportunidad.",
        ("- **Edad del mercado**: horas desde el último cambio de cualquier cuota de ese mercado en "
        "la casa. Un mercado que no se mueve en días probablemente ya no se ofrece."),
    ]
    for kind in ("mercado", "outcome"):
        lines += ["", f"## Por edad del {kind}", "",
                  "| Casa | Edad | Selecciones | CLV medio | CLV power | €/mes (mult.) | €/mes (power) |",
                  "|---|---|---|---|---|---|---|"]
        for book in BOOKS:
            for _, _, name in BUCKETS:
                sels = groups.get((book, kind, name))
                if not sels:
                    continue
                n, c, cp, em, ep = summarize(sels, book)
                lines.append(f"| {book} | {name} | {n} | {c:+.1%} | {cp:+.1%} "
                             f"| {em:+.0f} | {ep:+.0f} |")
    # Escenario solo con mercados "vivos": algún cambio en las últimas MAX_FRESH_H horas.
    lines += ["", f"## Escenario solo con mercados vivos (último cambio < {MAX_FRESH_H} h)", "",
              "Cada selección cuenta una vez (primera oportunidad con mercado vivo).", "",
              "| Casas | Apuestas/mes | €/mes (mult.) | €/mes (power) |", "|---|---|---|---|"]
    for books in SCENARIOS:
        bets = em = ep = 0.0
        for book in books:
            k = MATCHES_PER_MONTH / max(len(coverage[book]), 1)
            for sel, os_ in fresh[book].items():
                b, e = expected_bets_and_ev(os_, POLL_S, REACTION_S)
                _, p = expected_bets_and_ev(os_, POLL_S, REACTION_S, use_power=True)
                bets, em, ep = bets + b * k, em + e * k, ep + p * k
        lines.append(f"| {' + '.join(books)} | {bets:.0f} | {em * STAKE_EUR:+.0f} "
                     f"| {ep * STAKE_EUR:+.0f} |")
    lines += ["", "## Mediana de la edad del mercado al abrirse la oportunidad", ""]
    lines += [f"- {b}: {st.median(a):.1f} h (n={len(a)})" for b, a in raw_ages.items()]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
