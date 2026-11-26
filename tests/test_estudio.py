import pytest

from bot_apuestas.devig import edge, fair_prices_multiplicative, fair_prices_power
from bot_apuestas.estudio import (
    catch_probability,
    expected_bets_and_ev,
    find_opportunities,
)

H = 3600.0


def test_fair_prices_remove_margin():
    fair = fair_prices_multiplicative([1.91, 1.91])
    assert fair == pytest.approx([2.0, 2.0], abs=0.001)
    assert sum(1 / f for f in fair) == pytest.approx(1)


def test_power_devig_sums_to_one_and_penalises_longshot():
    prices = [1.25, 4.20]
    power = fair_prices_power(prices)
    mult = fair_prices_multiplicative(prices)
    assert sum(1 / f for f in power) == pytest.approx(1)
    assert power[1] > mult[1]  # la cuota alta se considera más larga (más margen)
    assert power[0] < mult[0]


def test_edge():
    assert edge(2.2, 2.0) == pytest.approx(0.10)


def _pin_2way(t, over, under, limit=1000.0):
    return {1: [(t, over, True, limit)], 2: [(t, under, True, limit)]}


def test_opportunity_opens_and_closes_when_soft_price_drops():
    kickoff = 10 * H
    pin = _pin_2way(0, 1.91, 1.91)  # justa 2.00 / 2.00
    soft = {1: [(1 * H, 2.10, True, None), (3 * H, 1.95, True, None)]}
    opps = find_opportunities(pin, soft, kickoff, n_outcomes=2, threshold=0.03)
    assert len(opps) == 1
    o = opps[0]
    assert o.start == 1 * H and o.end == 3 * H
    assert o.edge_at_start == pytest.approx(0.05, abs=0.002)
    assert o.clv == pytest.approx(0.05, abs=0.002)


def test_pinnacle_lengthening_closes_opportunity_with_negative_clv():
    kickoff = 10 * H
    pin = {
        1: [(0, 1.91, True, 500.0), (5 * H, 2.02, True, 3000.0)],
        2: [(0, 1.91, True, 500.0), (5 * H, 1.80, True, 3000.0)],
    }
    soft = {1: [(1 * H, 2.10, True, None)]}
    opps = find_opportunities(pin, soft, kickoff, n_outcomes=2, threshold=0.03)
    assert len(opps) == 1
    assert opps[0].end == 5 * H  # Pinnacle subió la cuota: el edge desaparece
    assert opps[0].pin_limit == 500.0
    closing_fair = fair_prices_multiplicative([2.02, 1.80])[0]
    assert opps[0].clv == pytest.approx(2.10 / closing_fair - 1)
    assert opps[0].clv < 0  # la línea se movió en contra: era un falso value


def test_pinnacle_shortening_raises_clv_above_initial_edge():
    kickoff = 10 * H
    pin = {
        1: [(0, 1.91, True, None), (5 * H, 1.80, True, None)],
        2: [(0, 1.91, True, None), (5 * H, 2.02, True, None)],
    }
    soft = {1: [(1 * H, 2.10, True, None)]}
    opps = find_opportunities(pin, soft, kickoff, n_outcomes=2, threshold=0.03)
    assert len(opps) == 1 and opps[0].end == kickoff
    assert opps[0].max_edge > opps[0].edge_at_start
    assert opps[0].clv > opps[0].edge_at_start


def test_no_opportunity_when_market_incomplete_or_suspended():
    kickoff = 10 * H
    pin_incomplete = {1: [(0, 1.91, True, None)]}
    soft = {1: [(1 * H, 2.5, True, None)]}
    assert find_opportunities(pin_incomplete, soft, kickoff, 2, 0.03) == []
    pin = _pin_2way(0, 1.91, 1.91)
    suspended = {1: [(1 * H, 2.5, False, None)]}
    assert find_opportunities(pin, suspended, kickoff, 2, 0.03) == []
    placeholder = {1: [(1 * H, 1.01, True, None)]}
    assert find_opportunities(pin, placeholder, kickoff, 2, 0.03) == []


def test_open_at_kickoff_and_events_after_kickoff_ignored():
    kickoff = 10 * H
    pin = _pin_2way(0, 1.91, 1.91)
    soft = {1: [(9 * H, 2.2, True, None), (11 * H, 1.5, True, None)]}
    opps = find_opportunities(pin, soft, kickoff, 2, 0.03)
    assert len(opps) == 1 and opps[0].end == kickoff


def test_catch_probability():
    assert catch_probability(60 * 60, 30 * 60, 180) == 1.0
    assert catch_probability(10 * 60, 30 * 60, 180) == pytest.approx(7 / 30)
    assert catch_probability(2 * 60, 30 * 60, 180) == 0.0


def test_expected_bets_bets_at_most_once_per_selection():
    kickoff = 100 * H
    pin = _pin_2way(0, 1.91, 1.91)
    soft = {1: [(1 * H, 2.10, True, None), (3 * H, 1.9, True, None), (5 * H, 2.10, True, None)]}
    opps = find_opportunities(pin, soft, kickoff, 2, 0.03)
    assert len(opps) == 2
    bets, ev = expected_bets_and_ev(opps, poll_interval_s=1800, reaction_s=180)
    assert bets == pytest.approx(1.0)
    assert ev == pytest.approx(opps[0].clv)


def test_surebet_across_two_books_and_closes_when_price_drops():
    from bot_apuestas.estudio import find_surebets
    kickoff = 10 * H
    books = {
        "a": {1: [(1 * H, 2.10, True, None), (3 * H, 1.90, True, None)], 2: [(1 * H, 1.80, True, None)]},
        "b": {1: [(1 * H, 1.85, True, None)], 2: [(2 * H, 2.05, True, None)]},
    }
    sbs = find_surebets(books, kickoff, n_outcomes=2)
    assert len(sbs) == 1
    sb = sbs[0]
    assert sb.start == 2 * H and sb.end == 3 * H
    assert sb.legs == {1: ("a", 2.10), 2: ("b", 2.05)}
    assert sb.profit == pytest.approx(1 / (1 / 2.10 + 1 / 2.05) - 1)


def test_no_surebet_within_one_book_or_with_stale_leg():
    from bot_apuestas.estudio import find_surebets
    kickoff = 100 * H
    one_book = {"a": {1: [(0, 2.10, True, None)], 2: [(0, 2.05, True, None)]}}
    assert find_surebets(one_book, kickoff, 2) == []
    books = {
        "a": {1: [(0, 2.10, True, None)], 2: [(0, 1.70, True, None)]},  # "a" no cambia más
        "b": {1: [(0, 1.80, True, None)], 2: [(0, 1.90, True, None), (48 * H, 2.05, True, None)]},
    }
    assert len(find_surebets(books, kickoff, 2)) == 1
    assert find_surebets(books, kickoff, 2, max_market_age_s=24 * H) == []
