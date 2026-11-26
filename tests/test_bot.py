from datetime import UTC, datetime, timedelta

import pytest

from bot_apuestas.catalog import MarketInfo, is_target_market, selection_label
from bot_apuestas.clv import closing_prices, compute_clv
from bot_apuestas.detector import find_value_bets, parse_odds_payload
from bot_apuestas.store import Store
from bot_apuestas.telegram import format_alert

NOW = datetime(2026, 11, 18, 12, 0, tzinfo=UTC)
OU25 = MarketInfo(1010, "Over Under Full Time", 2.5, 2, {1010: "Over", 1011: "Under"})
OU3 = MarketInfo(1012, "Over Under Full Time", 3.0, 2, {1012: "Over", 1013: "Under"})
X12 = MarketInfo(101, "Full Time Result", 0.0, 3, {101: "1", 102: "X", 103: "2"})
BTTS = MarketInfo(104, "Both Teams To Score", 0.0, 2, {104: "Yes", 105: "No"})
MARKETS = {m.market_id: m for m in (OU25, OU3, X12, BTTS)}


def _outcome(price, active=True):
    return {"players": {"0": {"price": price, "active": active,
                              "changedAt": "2026-11-18T11:00:00Z", "limit": 2000.0}}}


def _payload(book, start, markets, market_active=True):
    return [{
        "fixtureId": "f1", "participant1Id": 1, "participant2Id": 2, "tournamentId": 8,
        "startTime": start.isoformat().replace("+00:00", "Z"),
        "bookmakerOdds": {book: {
            "bookmakerIsActive": True, "suspended": False,
            "fixturePath": f"https://{book}/evento",
            "markets": {
                str(mid): {"marketActive": market_active,
                           "outcomes": {str(oid): _outcome(p) for oid, p in outs.items()}}
                for mid, outs in markets.items()
            },
        }},
    }]


def _fixtures(start, ref_markets, soft_markets, soft_market_active=True):
    names = {1: "Real Betis", 2: "Sevilla FC"}
    fx = parse_odds_payload(_payload("pinnacle", start, ref_markets), "pinnacle", names)
    parse_odds_payload(_payload("winamax.es", start, soft_markets, soft_market_active),
                       "winamax.es", names, into=fx)
    return fx


def _detect(fx, **kw):
    params = {"min_edge": 0.03, "max_edge": 0.30, "min_hours": 0, "max_hours": 72}
    params.update(kw)
    return find_value_bets(fx, MARKETS, "pinnacle", ["winamax.es"], NOW, **params)


def test_target_markets_exclude_1x2_and_asian_lines():
    assert is_target_market(OU25) and is_target_market(BTTS)
    assert not is_target_market(X12) and not is_target_market(OU3)


def test_detects_value_on_over_under():
    fx = _fixtures(NOW + timedelta(hours=20),
                   {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})
    vbs = _detect(fx)
    assert len(vbs) == 1
    vb = vbs[0]
    assert vb.outcome_id == 1010 and vb.price == 2.10
    assert vb.edge == pytest.approx(0.05, abs=0.002)
    assert vb.fixture.home == "Real Betis"
    assert vb.ref_limit == 2000.0


def test_ignores_1x2_outside_window_and_inactive_markets():
    ref = {101: {101: 2.0, 102: 3.5, 103: 4.0}, 1010: {1010: 1.91, 1011: 1.91}}
    soft = {101: {101: 2.5, 102: 3.5, 103: 4.0}, 1010: {1010: 2.10, 1011: 1.70}}
    assert _detect(_fixtures(NOW + timedelta(hours=100), ref, soft)) == []  # > 72 h
    assert _detect(_fixtures(NOW - timedelta(hours=1), ref, soft)) == []  # ya empezado
    flagged = _detect(_fixtures(NOW + timedelta(hours=20), ref, soft, soft_market_active=False))
    assert [v.market_flagged for v in flagged] == [True]  # se avisa, no se descarta
    assert "inactivo" in format_alert(flagged[0], 10)
    vbs = _detect(_fixtures(NOW + timedelta(hours=20), ref, soft))
    assert [v.market.market_id for v in vbs] == [1010]  # el 1X2 nunca se alerta


def test_ignores_implausible_edge_and_incomplete_reference():
    soft = {1010: {1010: 3.50, 1011: 1.70}}
    assert _detect(_fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}}, soft)) == []
    assert _detect(_fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91}},
                             {1010: {1010: 2.10}})) == []


def test_store_alerts_once_unless_price_improves(tmp_path):
    store = Store(tmp_path / "bot.sqlite")
    fx = _fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})
    vb = _detect(fx)[0]
    assert store.should_alert(vb)
    store.save_alert(vb, "Más de 2.5 goles")
    assert not store.should_alert(vb)
    vb.price = 2.15
    assert store.should_alert(vb)


def test_alert_text():
    fx = _fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})
    text = format_alert(_detect(fx)[0], stake_eur=20)
    assert "winamax.es" in text and "Más de 2.5 goles" in text and "2.10" in text
    assert "Real Betis - Sevilla FC" in text and "https://winamax.es/evento" in text
    assert selection_label(BTTS, 105) == "Ambos marcan: No"


def test_closing_prices_and_clv():
    kickoff = datetime(2026, 11, 18, 20, tzinfo=UTC).timestamp()
    hist = {"outcomes": {
        "1010": {"players": {"0": [
            {"createdAt": "2026-11-18T10:00:00Z", "price": 1.91, "active": True},
            {"createdAt": "2026-11-18T19:55:00Z", "price": 1.80, "active": True},
            {"createdAt": "2026-11-18T20:30:00Z", "price": 1.20, "active": True},  # en juego
        ]}},
        "1011": {"players": {"0": [
            {"createdAt": "2026-11-18T19:55:00Z", "price": 2.02, "active": True},
        ]}},
    }}
    closing = closing_prices(hist, kickoff)
    assert closing == {1010: 1.80, 1011: 2.02}
    fair, _fair_p, clv, clv_p = compute_clv(2.10, 1010, closing, n_outcomes=2)
    assert clv == pytest.approx(2.10 / fair - 1) and clv > 0.1
    assert clv_p is not None
    assert compute_clv(2.10, 1010, {1010: 1.8}, 2) == (None, None, None, None)


def test_quote_age_and_stale_warning():
    fx = _fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})
    vb = _detect(fx)[0]
    assert vb.quote_age_h == pytest.approx(1.0)
    assert "desfasada" not in format_alert(vb, 10)
    vb.quote_age_h = 72
    assert "desfasada" in format_alert(vb, 10)


def test_stale_market_filtered_when_max_age_set():
    fx = _fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})  # cambios hace 1 h
    assert len(_detect(fx, max_market_age_h=24)) == 1
    assert _detect(fx, max_market_age_h=0.5) == []


def _two_books(start, a_markets, b_markets, names=None):
    names = names or {1: "Real Betis", 2: "Sevilla FC"}
    fx = parse_odds_payload(_payload("codere.es", start, a_markets), "codere.es", names)
    parse_odds_payload(_payload("betway.es", start, b_markets), "betway.es", names, into=fx)
    return fx


def _sure(fx, **kw):
    from bot_apuestas.detector import find_surebets_live
    params = {"min_profit": 0.005, "max_profit": 0.10, "min_hours": 0, "max_hours": 72}
    params.update(kw)
    return find_surebets_live(fx, MARKETS, ["codere.es", "betway.es"], NOW, **params)


def test_live_surebet_and_stakes_pay_the_same():
    fx = _two_books(NOW + timedelta(hours=10),
                    {1010: {1010: 2.10, 1011: 1.75}}, {1010: {1010: 1.80, 1011: 2.05}})
    sbs = _sure(fx)
    assert len(sbs) == 1
    sb = sbs[0]
    assert sb.legs == {1010: ("codere.es", 2.10), 1011: ("betway.es", 2.05)}
    assert sb.profit == pytest.approx(1 / (1 / 2.10 + 1 / 2.05) - 1)
    stakes = sb.stakes(100)
    assert sum(stakes.values()) == pytest.approx(100)
    assert stakes[1010] * 2.10 == pytest.approx(stakes[1011] * 2.05)
    assert stakes[1010] * 2.10 == pytest.approx(sb.payout(100))


def test_live_surebet_1x2_and_no_surebet_when_margin_positive():
    fx = _two_books(NOW + timedelta(hours=10),
                    {101: {101: 2.30, 102: 3.20, 103: 3.00}},
                    {101: {101: 2.00, 102: 3.70, 103: 4.20}})
    sbs = _sure(fx)
    assert len(sbs) == 1 and sbs[0].market.market_id == 101
    normal = _two_books(NOW + timedelta(hours=10),
                        {1010: {1010: 1.95, 1011: 1.85}}, {1010: {1010: 1.90, 1011: 1.90}})
    assert _sure(normal) == []


def test_live_surebet_ignores_stale_market_and_implausible_profit():
    fx = _two_books(NOW + timedelta(hours=10),
                    {1010: {1010: 2.10, 1011: 1.75}}, {1010: {1010: 1.80, 1011: 2.05}})
    assert _sure(fx, max_market_age_h=0.5) == []  # las cuotas tienen 1 h
    huge = _two_books(NOW + timedelta(hours=10),
                      {1010: {1010: 3.00, 1011: 1.20}}, {1010: {1010: 1.20, 1011: 3.00}})
    assert _sure(huge) == []  # 50 % garantizado: error de datos


def test_surebet_alert_text_and_store_dedup(tmp_path):
    from bot_apuestas.telegram import format_surebet
    fx = _two_books(NOW + timedelta(hours=10),
                    {101: {101: 2.30, 102: 3.20, 103: 3.00}},
                    {101: {101: 2.00, 102: 3.70, 103: 4.20}})
    sb = _sure(fx)[0]
    text = format_surebet(sb, 100)
    assert "SUREBET" in text and "Gana Real Betis" in text and "Empate" in text
    assert "codere.es" in text and "betway.es" in text and "pase lo que pase" in text
    store = Store(tmp_path / "bot.sqlite")
    assert store.should_alert_surebet(sb)
    store.save_surebet(sb)
    assert not store.should_alert_surebet(sb)
    sb.profit += 0.01
    assert store.should_alert_surebet(sb)


def test_muestra_csv_rows_for_value_bet_and_surebet(tmp_path):
    from bot_apuestas.muestra import COLUMNS, log_surebet, log_value_bet, read_rows
    path = tmp_path / "prueba.csv"
    fx = _fixtures(NOW + timedelta(hours=20), {1010: {1010: 1.91, 1011: 1.91}},
                   {1010: {1010: 2.10, 1011: 1.70}})
    log_value_bet(path, 7, _detect(fx)[0], NOW)
    sfx = _two_books(NOW + timedelta(hours=10),
                     {1010: {1010: 2.10, 1011: 1.75}}, {1010: {1010: 1.80, 1011: 2.05}})
    log_surebet(path, 3, _sure(sfx)[0], NOW)
    rows = read_rows(path)
    assert list(rows[0]) == COLUMNS
    assert [r["alerta"] for r in rows] == ["V7", "S3", "S3"]
    assert rows[0]["cuota_bot"] == "2,10" and rows[0]["apuesta"] == "Más de 2.5 goles"
    assert rows[0]["hora_alerta"] == "18/11 13:00"  # hora de Madrid
    assert {r["casa"] for r in rows[1:]} == {"codere.es", "betway.es"}
    assert all(r["cuota_web"] == "" and r["disponible"] == "" for r in rows)
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")  # BOM: Excel lo abre en UTF-8
