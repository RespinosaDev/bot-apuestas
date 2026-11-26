"""Persistencia del bot en SQLite: alertas enviadas, su CLV posterior y registro de consultas."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from bot_apuestas.detector import LiveSurebet, ValueBet

SCHEMA = """
CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    fixture_id TEXT NOT NULL, tournament_id INTEGER, home TEXT, away TEXT, start_time TEXT,
    bookmaker TEXT NOT NULL, market_id INTEGER NOT NULL, outcome_id INTEGER NOT NULL,
    selection TEXT, price REAL, fair REAL, fair_power REAL, edge REAL, edge_power REAL,
    ref_limit REAL, hours_to_kickoff REAL, market_flagged INTEGER, quote_age_h REAL,
    closing_fair REAL, closing_fair_power REAL, clv REAL, clv_power REAL, clv_checked_at TEXT
);
CREATE INDEX IF NOT EXISTS alerts_sel ON alerts (fixture_id, bookmaker, market_id, outcome_id);
CREATE TABLE IF NOT EXISTS surebets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    fixture_id TEXT NOT NULL, tournament_id INTEGER, home TEXT, away TEXT, start_time TEXT,
    market_id INTEGER NOT NULL, legs TEXT, profit REAL, hours_to_kickoff REAL,
    flagged_books TEXT
);
CREATE INDEX IF NOT EXISTS surebets_sel ON surebets (fixture_id, market_id);
CREATE TABLE IF NOT EXISTS polls (
    at TEXT NOT NULL, fixtures INTEGER, value_bets INTEGER, new_alerts INTEGER,
    requests_used INTEGER, request_limit INTEGER
);
"""


def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def should_alert(self, vb: ValueBet) -> bool:
        """Avisar si la selección es nueva o si la cuota ha mejorado desde la última alerta."""
        row = self.db.execute(
            """SELECT MAX(price) FROM alerts
               WHERE fixture_id=? AND bookmaker=? AND market_id=? AND outcome_id=?""",
            vb.key,
        ).fetchone()
        return row[0] is None or vb.price > row[0]

    def save_alert(self, vb: ValueBet, selection: str) -> int:
        fx = vb.fixture
        cur = self.db.execute(
            """INSERT INTO alerts (created_at, fixture_id, tournament_id, home, away, start_time,
               bookmaker, market_id, outcome_id, selection, price, fair, fair_power, edge,
               edge_power, ref_limit, hours_to_kickoff, market_flagged, quote_age_h)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), fx.fixture_id, fx.tournament_id, fx.home, fx.away, fx.start.isoformat(),
             vb.bookmaker, vb.market.market_id, vb.outcome_id, selection, vb.price, vb.fair,
             vb.fair_power, vb.edge, vb.edge_power, vb.ref_limit, vb.hours_to_kickoff,
             int(vb.market_flagged), vb.quote_age_h),
        )
        self.db.commit()
        return cur.lastrowid

    def should_alert_surebet(self, sb: LiveSurebet, min_improvement: float = 0.005) -> bool:
        """Nueva para ese partido y mercado, o con un beneficio claramente mejor que la última."""
        row = self.db.execute(
            "SELECT MAX(profit) FROM surebets WHERE fixture_id=? AND market_id=?", sb.key
        ).fetchone()
        return row[0] is None or sb.profit >= row[0] + min_improvement

    def save_surebet(self, sb: LiveSurebet) -> int:
        fx = sb.fixture
        legs = {str(oid): {"book": b, "price": p} for oid, (b, p) in sb.legs.items()}
        cur = self.db.execute(
            """INSERT INTO surebets (created_at, fixture_id, tournament_id, home, away, start_time,
               market_id, legs, profit, hours_to_kickoff, flagged_books)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (now_iso(), fx.fixture_id, fx.tournament_id, fx.home, fx.away, fx.start.isoformat(),
             sb.market.market_id, json.dumps(legs), sb.profit, sb.hours_to_kickoff,
             ",".join(sorted(sb.flagged_books))),
        )
        self.db.commit()
        return cur.lastrowid

    def log_poll(self, fixtures: int, value_bets: int, new_alerts: int,
                 used: int | None, limit: int | None) -> None:
        self.db.execute("INSERT INTO polls VALUES (?,?,?,?,?,?)",
                        (now_iso(), fixtures, value_bets, new_alerts, used, limit))
        self.db.commit()

    def alerts_pending_clv(self, now: datetime) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT * FROM alerts WHERE clv_checked_at IS NULL AND start_time < ? ORDER BY start_time",
            (now.isoformat(),),
        ).fetchall()

    def set_clv(self, alert_id: int, closing_fair: float | None, closing_fair_power: float | None,
                clv: float | None, clv_power: float | None) -> None:
        self.db.execute(
            """UPDATE alerts SET closing_fair=?, closing_fair_power=?, clv=?, clv_power=?,
               clv_checked_at=? WHERE id=?""",
            (closing_fair, closing_fair_power, clv, clv_power, now_iso(), alert_id),
        )
        self.db.commit()
