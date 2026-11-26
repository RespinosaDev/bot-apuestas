"""Fase 0.5: descarga el histórico de cuotas (gratuito) de los partidos ya jugados a SQLite.

Reanudable: si se corta, al relanzarlo continúa por donde iba.

Uso:
    python scripts/estudio_descarga.py                 # todos los partidos pendientes
    python scripts/estudio_descarga.py --max 20        # solo 20 partidos (prueba)
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from dotenv import load_dotenv

from bot_apuestas.oddspapi import OddsPapiClient

RAIZ = Path(__file__).resolve().parent.parent
DIR = RAIZ / "data" / "estudio"
DB_PATH = DIR / "historico.sqlite"
TOURNAMENTS = {8: "LaLiga", 17: "Premier League"}

# Máximo 3 casas por llamada. Pinnacle va en el primer grupo como referencia.
BOOK_GROUPS = [
    ("pinnacle", "winamax.es", "codere.es"),
    ("bet365.es", "bwin.es", "betway.es"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS fixtures (
    fixture_id TEXT PRIMARY KEY, tournament TEXT, start_time TEXT,
    home TEXT, away TEXT, status_id INTEGER
);
CREATE TABLE IF NOT EXISTS odds (
    fixture_id TEXT, bookmaker TEXT, market_id INTEGER, outcome_id INTEGER,
    ts TEXT, price REAL, stake_limit REAL, active INTEGER
);
CREATE INDEX IF NOT EXISTS odds_idx ON odds (fixture_id, market_id, bookmaker);
CREATE TABLE IF NOT EXISTS downloaded (
    fixture_id TEXT, book_group TEXT, n_rows INTEGER, PRIMARY KEY (fixture_id, book_group)
);
"""


def kept_market_ids() -> set[int]:
    """1X2, ambos marcan y todas las líneas de Más/Menos del partido completo."""
    catalog = json.loads((RAIZ / "data" / "raw" / "oddspapi_markets_sport10.json").read_text("utf-8"))
    ids = {101, 104}
    ids |= {m["marketId"] for m in catalog if m["marketName"] == "Over Under Full Time"}
    return ids


def rows_from_history(fixture_id: str, payload: dict, markets: set[int]):
    for book, bdata in payload.get("bookmakers", {}).items():
        for mid, mdata in bdata.get("markets", {}).items():
            if int(mid) not in markets:
                continue
            for oid, odata in mdata.get("outcomes", {}).items():
                for entry in odata.get("players", {}).get("0", []):
                    yield (
                        fixture_id, book, int(mid), int(oid), entry["createdAt"],
                        entry.get("price"), entry.get("limit"), int(bool(entry.get("active"))),
                    )


def load_fixtures(db: sqlite3.Connection) -> None:
    for tid, name in TOURNAMENTS.items():
        path = DIR / f"fixtures_{tid}.json"
        if not path.exists():
            sys.exit(f"Falta {path}: descarga antes la lista de partidos.")
        for f in json.loads(path.read_text("utf-8")):
            db.execute(
                "INSERT OR REPLACE INTO fixtures VALUES (?,?,?,?,?,?)",
                (f["fixtureId"], name, f["startTime"], f["participant1Name"],
                 f["participant2Name"], f["statusId"]),
            )
    db.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max", type=int, default=None, help="máximo de partidos a descargar")
    args = parser.parse_args()

    load_dotenv(RAIZ / ".env")
    db = sqlite3.connect(DB_PATH)
    db.executescript(SCHEMA)
    load_fixtures(db)
    markets = kept_market_ids()

    todo = db.execute(
        """SELECT fixture_id, home, away, start_time FROM fixtures WHERE status_id = 2
           AND (SELECT COUNT(*) FROM downloaded d WHERE d.fixture_id = fixtures.fixture_id) < ?
           ORDER BY start_time DESC""",
        (len(BOOK_GROUPS),),
    ).fetchall()
    if args.max:
        todo = todo[: args.max]
    print(f"Partidos pendientes: {len(todo)} (~{len(todo) * len(BOOK_GROUPS) * 6 / 60:.0f} min)")

    client = OddsPapiClient(os.environ["ODDSPAPI_KEY"])
    try:
        for i, (fid, home, away, start) in enumerate(todo, 1):
            for group in BOOK_GROUPS:
                key = ",".join(group)
                if db.execute(
                    "SELECT 1 FROM downloaded WHERE fixture_id=? AND book_group=?", (fid, key)
                ).fetchone():
                    continue
                payload = client.get("historical-odds", fixtureId=fid, bookmakers=key)
                rows = list(rows_from_history(fid, payload, markets)) if payload else []
                db.executemany("INSERT INTO odds VALUES (?,?,?,?,?,?,?,?)", rows)
                db.execute("INSERT INTO downloaded VALUES (?,?,?)", (fid, key, len(rows)))
                db.commit()
            print(f"[{i}/{len(todo)}] {start[:10]} {home} - {away}", flush=True)
    finally:
        client.close()
        db.close()


if __name__ == "__main__":
    main()
