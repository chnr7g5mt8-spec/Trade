import random
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import backtest as bt  # noqa: E402

from app.sources.yahoo import Chart, Point  # noqa: E402

DAY = 86400


def test_spearman():
    xs = [float(i) for i in range(30)]
    assert bt.spearman(xs, [x * 2 for x in xs]) == pytest.approx(1.0)
    assert bt.spearman(xs, [-x for x in xs]) == pytest.approx(-1.0)
    assert bt.spearman(xs[:5], xs[:5]) is None  # too few
    tied = [1.0] * 15 + [2.0] * 15
    assert bt.spearman(tied, xs) > 0.8


def test_quintiles_lowest_scores_first():
    scored = [(float(i), i / 100) for i in range(100)]
    q = bt.quintile_returns(scored)
    assert q == sorted(q)
    assert q[0] == pytest.approx(0.095) and q[4] == pytest.approx(0.895)
    assert bt.quintile_returns(scored[:10]) is None


def test_published_respects_reporting_lag():
    annual = {"annualTotalRevenue": [Point("2023-12-31", 1, "USD", "12M"), Point("2024-12-31", 2, "USD", "12M")]}
    assert len(bt.published(annual, date(2025, 3, 1))["annualTotalRevenue"]) == 1  # FY2024 not out yet
    assert len(bt.published(annual, date(2025, 3, 31))["annualTotalRevenue"]) == 2


def make_chart(start: date, closes):
    t0 = bt._ts(start)
    ts = [int(t0 + i * DAY) for i in range(len(closes))]
    return Chart("X", {"currency": "USD"}, ts, list(closes), list(closes), [])


def test_forward_return_and_truncate():
    c = make_chart(date(2024, 1, 1), [100 * 1.001 ** i for i in range(800)])
    r = bt.forward_return(c, date(2024, 6, 1))
    assert r == pytest.approx(1.001 ** 365 - 1, rel=1e-3)
    assert bt.forward_return(c, date(2026, 1, 1)) is None  # future not known yet
    t = bt.truncate(c, bt._ts(date(2024, 1, 31)))
    assert len(t.closes) == 31 and t.timestamps[-1] <= bt._ts(date(2024, 1, 31))


def test_evaluate_detects_a_score_that_predicts_returns():
    rng = random.Random(1)
    rows = []
    for d in ("2024-03-31", "2024-06-30", "2024-09-30", "2024-12-31"):
        for i in range(100):
            score = rng.uniform(0, 100)
            rows.append({"date": d, "symbol": f"S{i}", "score": score, "label": bt.label_for(round(score)),
                         "categories": {"good": score, "noise": rng.uniform(0, 100)},
                         "forward_return": score / 500 + rng.gauss(0, 0.05)})
    rep = bt.evaluate(rows, ["good", "noise"])
    s = rep["summary"]
    assert s["test_dates"] == 4 and s["observations"] == 400
    assert s["top_minus_bottom"] > 0.1
    assert s["top_beat_bottom_share"] == 1.0
    assert s["rank_correlation"] > 0.5 and s["rank_correlation_t"] > 3
    assert s["category_rank_correlation"]["good"] > 0.5
    assert abs(s["category_rank_correlation"]["noise"]) < 0.2
    assert s["quintile_returns"] == sorted(s["quintile_returns"])
    assert set(s["by_label"]) <= {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}


def test_evaluate_with_no_usable_dates():
    assert bt.evaluate([], ["x"]) == {"periods": []}


def test_stock_at_uses_only_published_figures_and_prices_until_then():
    c = make_chart(date(2022, 1, 1), [50.0 + i * 0.05 for i in range(1300)])
    annual = {
        "annualTotalRevenue": [Point("2022-12-31", 100, "USD", "12M"), Point("2023-12-31", 120, "USD", "12M")],
        "annualDilutedEPS": [Point("2022-12-31", 2, "USD", "12M"), Point("2023-12-31", 4, "USD", "12M")],
        "annualOrdinarySharesNumber": [Point("2022-12-31", 10, "USD", "12M"), Point("2023-12-31", 10, "USD", "12M")],
    }
    company = bt.Company("X", "Technology", "Software—Application", c, annual)
    early = bt.stock_at(company, date(2024, 2, 1), None)  # FY2023 not yet published
    later = bt.stock_at(company, date(2024, 6, 1), None)
    price_early = c.raw_closes[sum(1 for t in c.timestamps if t <= bt._ts(date(2024, 2, 1))) - 1]
    assert early.pe_ratio == pytest.approx(price_early / 2)
    assert later.revenue_growth == pytest.approx(0.2)
    assert later.earnings_growth == pytest.approx(1.0)
