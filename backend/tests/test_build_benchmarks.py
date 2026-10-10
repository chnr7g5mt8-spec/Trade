import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import build_benchmarks as bb  # noqa: E402

from app.benchmarks import parse  # noqa: E402
from app.models import StockData  # noqa: E402


def test_quantiles_match_linear_interpolation():
    q = dict(bb.quantiles([float(x) for x in range(1, 101)]))
    assert q[0.5] == pytest.approx(50.5)
    assert q[0.05] == pytest.approx(5.95)
    assert q[0.95] == pytest.approx(95.05)
    assert dict(bb.quantiles([7.0]))[0.5] == 7.0


def test_loss_makers_and_negative_equity_are_left_out_of_peer_norms():
    companies = [StockData(ticker=f"T{i}", pe_ratio=pe, debt_to_equity=de)
                 for i, (pe, de) in enumerate([(10, 0.5), (20, 1.0), (30, -1.0), (-1.0, 2.0), (40, 1.5)])]
    g = bb.group_stats("X", "industry", companies)
    assert g["metrics"]["pe_ratio"]["count"] == 4  # the loss-maker is excluded
    assert g["metrics"]["debt_to_equity"]["count"] == 4  # negative equity excluded
    assert g["companies"] == 5


def test_metrics_with_too_few_values_are_omitted():
    g = bb.group_stats("X", "industry", [StockData(ticker="A", pe_ratio=10), StockData(ticker="B", pe_ratio=12)])
    assert "pe_ratio" not in g["metrics"]


def test_groups_round_trip_through_the_app_loader():
    records = []
    for i in range(12):
        records.append(("Technology", "Software—Infrastructure", StockData(ticker=f"S{i}", pe_ratio=20 + i)))
        records.append(("Technology", "Semiconductors", StockData(ticker=f"C{i}", pe_ratio=10 + i)))
    b = parse({"generated_at": "2026-10-01", "groups": bb.compute_groups(records)})
    ind, sec = b.lookup("Software - Infrastructure", "Technology")
    assert ind.companies == 12 and sec.companies == 24
    group, dist = b.for_metric("pe_ratio", ind, sec)
    assert group.level == "industry"
    assert dist.median == pytest.approx(25.5)


def test_only_relative_metrics_are_benchmarked():
    keys = {s.key for s in bb.RELATIVE_SPECS}
    assert "pe_ratio" in keys and "return_on_equity" in keys and "dividend_yield" in keys
    assert "return_1y" not in keys and "beta" not in keys and "interest_coverage" not in keys
