import pytest
from fase0_descarga import find_h2h_surebets, margin, summarize_the_odds_api


def _event(books: dict[str, tuple[float, float, float]], totals: dict | None = None) -> dict:
    """Evento con el formato de The Odds API v4."""
    bookmakers = []
    for key, (home, draw, away) in books.items():
        markets = [
            {
                "key": "h2h",
                "outcomes": [
                    {"name": "Home FC", "price": home},
                    {"name": "Draw", "price": draw},
                    {"name": "Away FC", "price": away},
                ],
            }
        ]
        if totals and key in totals:
            over, under = totals[key]
            markets.append(
                {
                    "key": "totals",
                    "outcomes": [
                        {"name": "Over", "price": over, "point": 2.5},
                        {"name": "Under", "price": under, "point": 2.5},
                        {"name": "Over", "price": 3.0, "point": 3.5},
                    ],
                }
            )
        bookmakers.append({"key": key, "title": key, "markets": markets})
    return {
        "home_team": "Home FC",
        "away_team": "Away FC",
        "commence_time": "2026-11-20T20:00:00Z",
        "bookmakers": bookmakers,
    }


def test_margin_fair_market_is_zero():
    assert margin([2.0, 2.0]) == pytest.approx(0)


def test_margin_typical_book():
    assert margin([1.91, 1.91]) == pytest.approx(0.0471, abs=1e-4)


def test_summary_counts_events_and_ignores_other_total_lines():
    events = [
        _event({"pinnacle": (2.0, 3.5, 4.0)}, totals={"pinnacle": (1.95, 1.95)}),
        _event({"pinnacle": (2.0, 3.5, 4.0), "codere": (1.9, 3.3, 3.8)}),
    ]
    s = summarize_the_odds_api(events)
    assert s["pinnacle"]["events"] == 2
    assert s["codere"]["events"] == 1
    assert s["pinnacle"]["totals_2_5_margin"] == pytest.approx(2 / 1.95 - 1)
    assert s["codere"]["totals_2_5_margin"] is None
    assert s["codere"]["h2h_margin"] > s["pinnacle"]["h2h_margin"]


def test_surebet_detected_across_books():
    # Mejores cuotas: 2.2 (a), 3.9 (b), 4.5 (c) -> 1/2.2 + 1/3.9 + 1/4.5 = 0.933 < 1
    events = [_event({"a": (2.2, 3.3, 3.5), "b": (2.0, 3.9, 3.6), "c": (2.0, 3.4, 4.5)})]
    found = find_h2h_surebets(events)
    assert len(found) == 1
    assert found[0]["legs"]["Draw"] == {"price": 3.9, "book": "b"}
    assert found[0]["profit_pct"] == pytest.approx(7.17, abs=0.01)


def test_no_surebet_in_normal_market():
    events = [_event({"a": (2.0, 3.4, 3.8), "b": (1.95, 3.5, 3.7)})]
    assert find_h2h_surebets(events) == []
