"""Bot de alertas de value bets.

    python -m bot_apuestas once              # una consulta ahora (gasta 1 + nº casas peticiones)
    python -m bot_apuestas run               # bucle: consulta cada N min en horario activo
    python -m bot_apuestas clv               # CLV de alertas ya jugadas (gratis)
    python -m bot_apuestas report            # resumen de alertas y CLV
    python -m bot_apuestas status            # cupo de peticiones restante (gratis)
    python -m bot_apuestas telegram-chat-id  # obtener TELEGRAM_CHAT_ID
"""

from __future__ import annotations

import argparse
import time
import traceback
from datetime import UTC, datetime

from bot_apuestas.catalog import load_markets, load_participants, selection_label
from bot_apuestas.clv import update_clv
from bot_apuestas.config import Config, load_config
from bot_apuestas.detector import find_surebets_live, find_value_bets, parse_odds_payload
from bot_apuestas.muestra import log_surebet, log_value_bet
from bot_apuestas.oddspapi import OddsPapiClient
from bot_apuestas.store import Store
from bot_apuestas.telegram import MADRID, Notifier, find_chat_ids, format_alert, format_surebet


def quota(client: OddsPapiClient) -> tuple[int, int]:
    """(usadas, límite) del mes. /account no consume cupo."""
    sub = client.get("account")["subscriptions"][0]
    return sub["request_count"], sub["request_limit"]


def poll(cfg: Config, client: OddsPapiClient, store: Store, notifier: Notifier) -> None:
    used, limit = quota(client)
    needed = cfg.requests_per_poll + 2  # +2 por si hay que refrescar los catálogos
    if limit - used - cfg.request_reserve < needed:
        print(f"Cupo insuficiente ({used}/{limit}); no se consulta.")
        return
    markets = load_markets(client, cfg.cache_dir)
    participants = load_participants(client, cfg.cache_dir)
    fixtures: dict = {}
    for book in [cfg.reference, *cfg.all_books]:
        payload = client.get(
            "odds-by-tournaments",
            bookmaker=book,
            tournamentIds=",".join(map(str, cfg.tournaments)),
        ) or []
        parse_odds_payload(payload, book, participants, into=fixtures)

    now = datetime.now(UTC)
    vbs = find_value_bets(
        fixtures, markets, cfg.reference, cfg.books, now,
        cfg.min_edge, cfg.max_edge, cfg.min_hours, cfg.max_hours, cfg.max_market_age_h,
    )
    new = 0
    for vb in vbs:
        if store.should_alert(vb):
            aid = store.save_alert(vb, selection_label(vb.market, vb.outcome_id,
                                                       vb.fixture.home, vb.fixture.away))
            log_value_bet(cfg.muestra_path, aid, vb, now)
            notifier.send(f"<b>#V{aid}</b> " + format_alert(vb, cfg.stake_eur))
            new += 1
    sbs = []
    if cfg.surebet_books:
        sbs = find_surebets_live(
            fixtures, markets, cfg.surebet_books, now, cfg.surebet_min_profit,
            cfg.surebet_max_profit, cfg.min_hours, cfg.max_hours, cfg.max_market_age_h,
        )
    for sb in sbs:
        if store.should_alert_surebet(sb):
            sid = store.save_surebet(sb)
            log_surebet(cfg.muestra_path, sid, sb, now)
            notifier.send(f"<b>#S{sid}</b> " + format_surebet(sb, cfg.surebet_stake_eur))
            new += 1
    used, limit = quota(client)
    store.log_poll(len(fixtures), len(vbs), new, used, limit)
    print(f"{datetime.now(MADRID):%d/%m %H:%M} · {len(fixtures)} partidos · {len(vbs)} value bets "
          f"· {len(sbs)} surebets · {new} alertas nuevas · cupo {used}/{limit}")


def run_clv(cfg: Config, client: OddsPapiClient, store: Store) -> None:
    markets = load_markets(client, cfg.cache_dir)
    n = update_clv(store, client, markets, cfg.reference, datetime.now(UTC))
    if n:
        print(f"CLV calculado para {n} alertas.")


def report(store: Store) -> None:
    sb = store.db.execute("SELECT COUNT(*), AVG(profit) FROM surebets").fetchone()
    if sb[0]:
        print(f"Surebets avisadas: {sb[0]} (beneficio medio {sb[1] * 100:.2f} %)\n")
    rows = store.db.execute(
        """SELECT bookmaker, COUNT(*) n, AVG(edge) e, AVG(clv) c, AVG(clv_power) cp,
                  AVG(clv > 0) pos, SUM(clv IS NOT NULL) nc
           FROM alerts GROUP BY bookmaker ORDER BY n DESC"""
    ).fetchall()
    if not rows:
        print("Sin alertas de value bets todavía.")
        return
    print(f"{'casa':<12}{'alertas':>8}{'edge med.':>10}{'con CLV':>9}{'CLV med.':>10}"
          f"{'CLV power':>11}{'CLV>0':>7}")
    for r in rows:
        def f(x):
            return f"{x * 100:+.1f}%" if x is not None else "-"
        print(f"{r['bookmaker']:<12}{r['n']:>8}{f(r['e']):>10}{r['nc']:>9}{f(r['c']):>10}"
              f"{f(r['cp']):>11}{f(r['pos']):>7}")


def in_active_hours(cfg: Config) -> bool:
    h = datetime.now(MADRID).hour
    return cfg.active_hours[0] <= h < cfg.active_hours[1]


def run_loop(cfg: Config, client: OddsPapiClient, store: Store, notifier: Notifier) -> None:
    per_month = (cfg.active_hours[1] - cfg.active_hours[0]) * 60 / cfg.poll_minutes * 30
    print(f"Bot en marcha: cada {cfg.poll_minutes} min de {cfg.active_hours[0]}:00 a "
          f"{cfg.active_hours[1]}:00 (Madrid). Gasto estimado: "
          f"{per_month * cfg.requests_per_poll:.0f} peticiones/mes. Ctrl+C para parar.")
    if not notifier.enabled:
        print("Telegram sin configurar: las alertas se muestran aquí.")
    while True:
        start = time.monotonic()
        if in_active_hours(cfg):
            for step in (lambda: poll(cfg, client, store, notifier),
                         lambda: run_clv(cfg, client, store)):
                try:
                    step()
                except Exception:  # noqa: BLE001 - el bucle no debe morir por un fallo puntual
                    traceback.print_exc()
        time.sleep(max(60.0, cfg.poll_minutes * 60 - (time.monotonic() - start)))


def main() -> None:
    parser = argparse.ArgumentParser(prog="bot_apuestas", description="Bot de value bets")
    parser.add_argument("command", choices=["once", "run", "clv", "report", "status",
                                            "telegram-chat-id"])
    args = parser.parse_args()
    cfg = load_config()

    if args.command == "telegram-chat-id":
        if not cfg.telegram_token:
            raise SystemExit("Pon TELEGRAM_BOT_TOKEN en .env y escribe algo a tu bot primero.")
        chats = find_chat_ids(cfg.telegram_token)
        print("\n".join(f"TELEGRAM_CHAT_ID={cid}  ({name})" for cid, name in chats)
              or "Ningún chat: escribe cualquier mensaje a tu bot en Telegram y repite.")
        return

    client = OddsPapiClient(cfg.oddspapi_key)
    store = Store(cfg.db_path)
    notifier = Notifier(cfg.telegram_token, cfg.telegram_chat_id)
    try:
        if args.command == "once":
            poll(cfg, client, store, notifier)
        elif args.command == "run":
            run_loop(cfg, client, store, notifier)
        elif args.command == "clv":
            run_clv(cfg, client, store)
            report(store)
        elif args.command == "report":
            report(store)
        elif args.command == "status":
            used, limit = quota(client)
            print(f"Peticiones usadas este mes: {used}/{limit}. "
                  f"Consultas posibles: {(limit - used - cfg.request_reserve) // cfg.requests_per_poll}")
    except KeyboardInterrupt:
        print("\nParado.")
    finally:
        client.close()


if __name__ == "__main__":
    main()
