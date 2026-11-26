"""Fase 0.5: analiza el histórico descargado y genera docs/estudio_viabilidad_datos.md.

Uso:
    python scripts/estudio_analisis.py
"""

from __future__ import annotations

import csv
import json
import sqlite3
import statistics as st
from collections import defaultdict
from pathlib import Path

from bot_apuestas.estudio import (
    Opportunity,
    catch_probability,
    expected_bets_and_ev,
    find_opportunities,
    to_epoch,
)

RAIZ = Path(__file__).resolve().parent.parent
DB_PATH = RAIZ / "data" / "estudio" / "historico.sqlite"
CSV_PATH = RAIZ / "data" / "estudio" / "oportunidades.csv"
REPORT_PATH = RAIZ / "docs" / "estudio_viabilidad_datos.md"

SOFT_BOOKS = ["winamax.es", "codere.es", "bet365.es", "bwin.es", "betway.es"]
THRESHOLDS = [0.02, 0.03, 0.05]
POLL_MIN = [0, 5, 15, 30, 60]  # 0 = tiempo real
REACTION_S = 180  # tiempo en abrir la casa y apostar
MAX_PLAUSIBLE_EDGE = 0.30  # por encima: probable error de datos o error palpable (se aparta)
MATCHES_PER_MONTH = 80  # LaLiga + Premier: ~10 partidos por jornada y liga, ~4 jornadas/mes
STAKE_EUR = 10
# 1X2 y líneas asiáticas fuera: CLV dudoso o negativo y reglas no comparables.
SCENARIO_MARKETS = ["Más/Menos 2.5", "Más/Menos otras líneas .5", "Ambos marcan"]
SCENARIO_BOOKS = [
    ("winamax.es", "codere.es"),  # plan mínimo (~55 $/mes)
    ("winamax.es", "codere.es", "bet365.es"),  # +30 $/mes
    ("winamax.es", "codere.es", "bet365.es", "bwin.es"),  # +20 $/mes
]
SCENARIO_POLL_MIN = [5, 15, 30]
GROUPS = ["1X2", "Más/Menos 2.5", "Más/Menos otras líneas .5", "Ambos marcan",
          "Más/Menos asiático (.0/.25/.75)"]


def market_group(market_id: int, names: dict[int, tuple[str, float]]) -> str | None:
    if market_id == 101:
        return "1X2"
    if market_id == 104:
        return "Ambos marcan"
    name, handicap = names.get(market_id, ("", 0))
    if name == "Over Under Full Time":
        if handicap == 2.5:
            return "Más/Menos 2.5"
        if handicap % 1 == 0.5:
            return "Más/Menos otras líneas .5"
        return "Más/Menos asiático (.0/.25/.75)"  # reglas de devolución: menos fiable
    return None


def load_catalog() -> tuple[dict[int, tuple[str, float]], dict[int, int]]:
    catalog = json.loads((RAIZ / "data" / "raw" / "oddspapi_markets_sport10.json").read_text("utf-8"))
    names = {m["marketId"]: (m["marketName"], m["handicap"]) for m in catalog}
    lengths = {m["marketId"]: m["marketLength"] for m in catalog}
    return names, lengths


def histories(rows) -> dict[str, dict[int, dict[int, list]]]:
    """bookmaker -> market_id -> outcome_id -> [(t, price, active, limit)]"""
    out: dict = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))
    for book, mid, oid, ts, price, limit, active in rows:
        if price is None:
            continue
        out[book][mid][oid].append((to_epoch(ts), price, bool(active), limit))
    for book in out.values():
        for market in book.values():
            for hist in market.values():
                hist.sort(key=lambda e: e[0])
    return out


def bucket_hours(h: float) -> str:
    if h < 6:
        return "< 6 h"
    if h < 24:
        return "6-24 h"
    if h < 72:
        return "1-3 días"
    return "> 3 días"


def pct(x: float) -> str:
    return f"{x * 100:.1f} %"


def fmt_minutes(seconds: float) -> str:
    m = seconds / 60
    return f"{m:.0f} min" if m < 120 else f"{m / 60:.1f} h"


def main() -> None:
    db = sqlite3.connect(DB_PATH)
    names, lengths = load_catalog()
    fixtures = db.execute(
        """SELECT f.fixture_id, f.tournament, f.start_time, f.home, f.away FROM fixtures f
           WHERE f.status_id = 2 AND (SELECT COUNT(*) FROM downloaded d
                                      WHERE d.fixture_id = f.fixture_id) = 2
           ORDER BY f.start_time"""
    ).fetchall()

    # (book, group, threshold) -> {selection_key: [Opportunity]}
    opps: dict[tuple, dict[tuple, list[Opportunity]]] = defaultdict(lambda: defaultdict(list))
    coverage: dict[tuple[str, str], int] = defaultdict(int)  # (book, group) -> nº partidos
    implausible: dict[str, int] = defaultdict(int)
    csv_rows = []

    for fid, tournament, start, home, away in fixtures:
        kickoff = to_epoch(start)
        rows = db.execute(
            """SELECT bookmaker, market_id, outcome_id, ts, price, stake_limit, active
               FROM odds WHERE fixture_id = ?""",
            (fid,),
        ).fetchall()
        h = histories(rows)
        pin = h.get("pinnacle", {})
        for book in SOFT_BOOKS:
            seen_groups = set()
            for mid, soft_market in h.get(book, {}).items():
                group = market_group(mid, names)
                if group is None or mid not in pin:
                    continue
                seen_groups.add(group)
                for thr in THRESHOLDS:
                    for o in find_opportunities(pin[mid], soft_market, kickoff, lengths[mid], thr):
                        if o.edge_at_start > MAX_PLAUSIBLE_EDGE:
                            if thr == THRESHOLDS[0]:
                                implausible[book] += 1
                            continue
                        opps[(book, group, thr)][(fid, mid, o.outcome_id)].append(o)
                        if thr == THRESHOLDS[0]:
                            csv_rows.append(
                                [fid, tournament, start, home, away, book, group, mid,
                                 o.outcome_id, o.price, round(o.fair_at_start, 3),
                                 round(o.edge_at_start, 4), round(o.max_edge, 4),
                                 round(o.duration_s / 60, 1), round(o.hours_before_kickoff, 1),
                                 o.pin_limit, None if o.clv is None else round(o.clv, 4),
                                 None if o.clv_power is None else round(o.clv_power, 4)]
                            )
            for g in seen_groups:
                coverage[(book, g)] += 1

    with CSV_PATH.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["fixture_id", "liga", "inicio", "local", "visitante", "casa", "mercado",
                    "market_id", "outcome_id", "cuota", "cuota_justa", "edge_inicio",
                    "edge_max", "duracion_min", "horas_antes", "limite_pinnacle", "clv", "clv_power"])
        w.writerows(csv_rows)

    n = len(fixtures)
    lines = [
        "# Estudio de viabilidad: resultados (generado automáticamente)",
        "",
        (f"- Partidos analizados: **{n}** (LaLiga + Premier League, terminados, "
        f"{fixtures[0][2][:10] if fixtures else '-'} → {fixtures[-1][2][:10] if fixtures else '-'})"),
        "- Referencia: Pinnacle sin margen (devig multiplicativo) en el mismo instante.",
        (f"- CLV: cuota apostada frente a la cuota justa de Pinnacle al cierre. "
        f"Reacción supuesta: {REACTION_S // 60} min. "
        f"Edge > {pct(MAX_PLAUSIBLE_EDGE)} se aparta como posible error de datos."),
        f"- Extrapolación mensual: {MATCHES_PER_MONTH} partidos/mes, {STAKE_EUR} € por apuesta.",
        "",
        "## Cobertura (partidos con el mercado en la casa y en Pinnacle)",
        "",
        "| Casa | " + " | ".join(GROUPS) + " |",
        "|---|" + "---|" * len(GROUPS),
    ]
    for book in SOFT_BOOKS:
        cells = [str(coverage.get((book, g), 0)) for g in
                 GROUPS]
        lines.append(f"| {book} | " + " | ".join(cells) + " |")

    for thr in THRESHOLDS:
        lines += [
            "",
            f"## Oportunidades con edge ≥ {pct(thr)}",
            "",
            "| Casa | Mercado | Selecciones | Intervalos | Duración mediana | Duran > 30 min "
            "| CLV medio | CLV medio (power) | CLV > 0 | " + " | ".join(
                f"€/mes @{'real' if p == 0 else f'{p} min'}" for p in POLL_MIN) + " |",
            "|---|---|---|---|---|---|---|---|---|" + "---|" * len(POLL_MIN),
        ]
        for (book, group, t), sels in sorted(opps.items()):
            if t != thr:
                continue
            flat = [o for os_ in sels.values() for o in os_]
            clvs = [o.clv for o in flat if o.clv is not None]
            clvp = [o.clv_power for o in flat if o.clv_power is not None]
            if not flat:
                continue
            money = []
            for p in POLL_MIN:
                ev_total = sum(expected_bets_and_ev(os_, p * 60, REACTION_S)[1] for os_ in sels.values())
                n_cov = max(coverage.get((book, group), 0), 1)
                money.append(f"{ev_total / n_cov * MATCHES_PER_MONTH * STAKE_EUR:+.1f}")
            lines.append(
                f"| {book} | {group} | {len(sels)} | {len(flat)} "
                f"| {fmt_minutes(st.median(o.duration_s for o in flat))} "
                f"| {pct(sum(o.duration_s > 1800 for o in flat) / len(flat))} "
                f"| {pct(st.mean(clvs)) if clvs else '-'} "
                f"| {pct(st.mean(clvp)) if clvp else '-'} "
                f"| {pct(sum(c > 0 for c in clvs) / len(clvs)) if clvs else '-'} | "
                + " | ".join(money) + " |"
            )

    # Desglose por antelación para el umbral intermedio: ¿cuándo aparecen las buenas?
    thr = THRESHOLDS[1]
    by_bucket: dict[tuple[str, str], list[Opportunity]] = defaultdict(list)
    for (book, _group, t), sels in opps.items():
        if t == thr:
            for os_ in sels.values():
                for o in os_:
                    by_bucket[(book, bucket_hours(o.hours_before_kickoff))].append(o)
    lines += [
        "",
        f"## Edge ≥ {pct(thr)} según la antelación al partido",
        "",
        "| Casa | Antelación | Intervalos | CLV medio | Duración mediana | Prob. de pillarla @30 min |",
        "|---|---|---|---|---|---|",
    ]
    for (book, b), os_ in sorted(by_bucket.items()):
        clvs = [o.clv for o in os_ if o.clv is not None]
        catch = st.mean(catch_probability(o.duration_s, 1800, REACTION_S) for o in os_)
        lines.append(
            f"| {book} | {b} | {len(os_)} | {pct(st.mean(clvs)) if clvs else '-'} "
            f"| {fmt_minutes(st.median(o.duration_s for o in os_))} | {pct(catch)} |"
        )

    # Escenarios operativos: solo mercados fiables, umbral intermedio.
    thr = THRESHOLDS[1]
    lines += [
        "",
        f"## Escenarios (edge ≥ {pct(thr)}, mercados: {', '.join(SCENARIO_MARKETS)})",
        "",
        ("Apuestas/mes y beneficio esperado/mes con "
        f"{STAKE_EUR} € por apuesta (CLV multiplicativo / power)."),
        "",
        "| Casas | Consulta cada | Apuestas/mes | €/mes (mult.) | €/mes (power) |",
        "|---|---|---|---|---|",
    ]
    for books in SCENARIO_BOOKS:
        for poll in SCENARIO_POLL_MIN:
            bets = ev_m = ev_p = 0.0
            for (book, group, t), sels in opps.items():
                if t != thr or book not in books or group not in SCENARIO_MARKETS:
                    continue
                # Normalizar por los partidos que la casa cubre en ese mercado, no por el total:
                # algunas casas solo tienen datos desde mayo.
                k = MATCHES_PER_MONTH / max(coverage.get((book, group), 0), 1)
                for os_ in sels.values():
                    b, e = expected_bets_and_ev(os_, poll * 60, REACTION_S)
                    _, ep = expected_bets_and_ev(os_, poll * 60, REACTION_S, use_power=True)
                    bets, ev_m, ev_p = bets + b * k, ev_m + e * k, ev_p + ep * k
            lines.append(
                f"| {' + '.join(books)} | {poll} min | {bets:.0f} "
                f"| {ev_m * STAKE_EUR:+.0f} | {ev_p * STAKE_EUR:+.0f} |"
            )

    lines += ["", "## Apartadas por edge implausible (> 30 %)", ""]
    lines += [f"- {b}: {c}" for b, c in sorted(implausible.items())] or ["- ninguna"]
    lines += ["", (f"Detalle de cada oportunidad (edge ≥ {pct(THRESHOLDS[0])}): "
              "`data/estudio/oportunidades.csv` (no se sube al repo).")]

    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
