"""¿Cuántas surebets reales hubo entre casas españolas? (histórico de la Fase 0.5)

Surebet = la mejor cuota de cada resultado, cada una en su casa, con sum(1/cuota) < 1.
Se mide con todas las cuotas y solo con mercados "vivos" (algún cambio en las últimas 24 h),
porque las cuotas congeladas de OddsPapi crean surebets falsas.

Uso:
    python scripts/estudio_surebets.py
"""

from __future__ import annotations

import sqlite3
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

from estudio_analisis import DB_PATH, MATCHES_PER_MONTH, histories, load_catalog

from bot_apuestas.estudio import catch_probability, find_surebets, to_epoch

RAIZ = Path(__file__).resolve().parent.parent
REPORT = RAIZ / "docs" / "estudio_surebets_datos.md"
BOOKS = ["winamax.es", "codere.es", "bet365.es", "bwin.es", "betway.es"]
MAX_PLAUSIBLE = 0.10  # > 10 % garantizado: casi seguro error de datos
FRESH_S = 24 * 3600
REACTION_S = 5 * 60  # dos apuestas en dos casas: más lento que una
STAKE_TOTAL_EUR = 100  # total repartido entre las patas


def group_of(mid: int, names) -> str | None:
    if mid == 101:
        return "1X2"
    if mid == 104:
        return "Ambos marcan"
    name, handicap = names.get(mid, ("", 0))
    if name == "Over Under Full Time" and handicap % 1 == 0.5:
        return "Más/Menos .5"
    return None


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    names, lengths = load_catalog()
    fixtures = db.execute(
        """SELECT f.fixture_id, f.start_time FROM fixtures f WHERE f.status_id = 2
           AND (SELECT COUNT(*) FROM downloaded d WHERE d.fixture_id = f.fixture_id) = 2"""
    ).fetchall()

    results: dict[str, list] = {"todas": [], "vivas": []}  # (fixture, grupo, Surebet)
    implausible = Counter()
    covered = 0
    for fid, start in fixtures:
        kickoff = to_epoch(start)
        rows = db.execute(
            """SELECT bookmaker, market_id, outcome_id, ts, price, stake_limit, active
               FROM odds WHERE fixture_id = ? AND bookmaker != 'pinnacle'""",
            (fid,),
        ).fetchall()
        h = histories(rows)
        if sum(b in h for b in BOOKS) >= 2:
            covered += 1
        by_market: dict[int, dict] = defaultdict(dict)
        for book in BOOKS:
            for mid, outs in h.get(book, {}).items():
                if group_of(mid, names):
                    by_market[mid][book] = outs
        for mid, books in by_market.items():
            if len(books) < 2:
                continue
            for kind, age in (("todas", None), ("vivas", FRESH_S)):
                for sb in find_surebets(books, kickoff, lengths[mid], age):
                    if sb.profit > MAX_PLAUSIBLE:
                        implausible[kind] += 1
                        continue
                    results[kind].append((fid, group_of(mid, names), sb))

    k = MATCHES_PER_MONTH / max(covered, 1)
    lines = [
        "# Surebets entre casas españolas (generado automáticamente)",
        "",
        f"- Partidos con ≥ 2 casas: {covered}. Casas: {', '.join(BOOKS)}.",
        "- Mercados: 1X2, Ambos marcan, Más/Menos (líneas .5). Sin exchanges ni casas sin licencia.",
        f"- Beneficio > {MAX_PLAUSIBLE:.0%} garantizado se aparta como error de datos.",
        (f"- €/mes: {STAKE_TOTAL_EUR} € repartidos por surebet, {REACTION_S // 60} min para "
        f"poner las dos apuestas, {MATCHES_PER_MONTH} partidos/mes. Una vez por partido y mercado."),
    ]
    for kind, label in (("todas", "Todas las cuotas"),
                        ("vivas", "Solo mercados vivos (cambio < 24 h en cada casa)")):
        sbs = results[kind]
        lines += ["", f"## {label}", ""]
        if not sbs:
            lines.append("Ninguna.")
            continue
        profits = [s.profit for _, _, s in sbs]
        durs = [s.duration_s for _, _, s in sbs]
        lines += [
            (f"- Intervalos con surebet: **{len(sbs)}** ({len(sbs) * k:.0f}/mes); "
            f"partido-mercado distintos: {len({(f, g, tuple(s.legs)) for f, g, s in sbs})}"),
            (f"- Beneficio garantizado: mediana {st.median(profits):.2%}, "
            f"media {st.mean(profits):.2%}, p90 {sorted(profits)[int(0.9 * len(profits))]:.2%}"),
            (f"- Duración: mediana {st.median(durs) / 60:.0f} min; "
            f"> 5 min {sum(d > 300 for d in durs) / len(durs):.0%}; "
            f"> 30 min {sum(d > 1800 for d in durs) / len(durs):.0%}"),
            f"- Apartadas por posible error de datos (> {MAX_PLAUSIBLE:.0%}): {implausible[kind]}",
            "",
            "| Mercado | Surebets | /mes | Beneficio medio | Duración mediana |",
            "|---|---|---|---|---|",
        ]
        by_group = defaultdict(list)
        for _, g, s in sbs:
            by_group[g].append(s)
        for g, ss in sorted(by_group.items()):
            lines.append(f"| {g} | {len(ss)} | {len(ss) * k:.1f} | "
                         f"{st.mean(s.profit for s in ss):.2%} | "
                         f"{st.median(s.duration_s for s in ss) / 60:.0f} min |")
        pairs = Counter(" + ".join(sorted({b for b, _ in s.legs.values()})) for _, _, s in sbs)
        lines += ["", "| Casas implicadas | Surebets |", "|---|---|"]
        lines += [f"| {p} | {n} |" for p, n in pairs.most_common(8)]

        lines += ["", "| Consulta cada | Surebets pilladas/mes | €/mes |", "|---|---|---|"]
        for poll in (0, 5, 15, 30):
            best: dict[tuple, list] = defaultdict(list)
            for f, g, s in sbs:
                best[(f, g)].append(s)
            n_caught = ev = 0.0
            for ss in best.values():
                not_yet = 1.0
                for s in sorted(ss, key=lambda s: s.start):
                    p = catch_probability(s.duration_s, poll * 60, REACTION_S)
                    n_caught += not_yet * p
                    ev += not_yet * p * s.profit
                    not_yet *= 1 - p
            lines.append(f"| {'tiempo real' if poll == 0 else f'{poll} min'} | {n_caught * k:.1f} "
                         f"| {ev * k * STAKE_TOTAL_EUR:+.1f} |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
