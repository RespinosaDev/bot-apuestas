"""Registro de la prueba de disponibilidad: cada alerta se añade como fila a un CSV que la
se completa a mano tras mirar la casa (hora, cuota en la web, disponible, notas).

Formato pensado para Excel en español: separador ';', decimales con coma, UTF-8 con BOM.
"""

from __future__ import annotations

import csv
from pathlib import Path
from zoneinfo import ZoneInfo

from bot_apuestas.catalog import selection_label
from bot_apuestas.detector import LiveSurebet, ValueBet

MADRID = ZoneInfo("Europe/Madrid")
COLUMNS = [
    "alerta", "tipo", "hora_alerta", "partido", "inicio_partido", "casa", "apuesta",
    "cuota_bot",
    # A rellenar a mano:
    "hora_comprobada", "cuota_web", "disponible", "notas",
]


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",")


def _ensure_header(path: Path) -> None:
    if not path.exists() or path.stat().st_size == 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as f:
            csv.writer(f, delimiter=";").writerow(COLUMNS)


def _append(path: Path, rows: list[list[str]]) -> None:
    _ensure_header(path)
    with path.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f, delimiter=";").writerows(rows)


def _now_madrid(now) -> str:
    return now.astimezone(MADRID).strftime("%d/%m %H:%M")


def _base(fx, now) -> list[str]:
    return [_now_madrid(now), f"{fx.home} - {fx.away}",
            fx.start.astimezone(MADRID).strftime("%d/%m %H:%M")]


def log_value_bet(path: Path, alert_id: int, vb: ValueBet, now) -> None:
    fx = vb.fixture
    hora, partido, inicio = _base(fx, now)
    label = selection_label(vb.market, vb.outcome_id, fx.home, fx.away)
    _append(path, [[f"V{alert_id}", "value bet", hora, partido, inicio, vb.bookmaker, label,
                     _num(vb.price), "", "", "", ""]])


def log_surebet(path: Path, surebet_id: int, sb: LiveSurebet, now) -> None:
    """Una fila por pata: cada casa se comprueba por separado."""
    fx = sb.fixture
    hora, partido, inicio = _base(fx, now)
    rows = []
    for oid, (book, price) in sorted(sb.legs.items(), key=lambda kv: kv[1][1], reverse=True):
        label = selection_label(sb.market, oid, fx.home, fx.away)
        rows.append([f"S{surebet_id}", f"surebet +{sb.profit * 100:.1f}%".replace(".", ","),
                     hora, partido, inicio, book, label, _num(price), "", "", "", ""])
    _append(path, rows)


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f, delimiter=";"))
