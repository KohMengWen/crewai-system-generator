import json
import csv
import io
import pytest

import reporting


def make_demo_report():
    p = reporting.PortfolioReport(name='Demo')
    p.add_position('AAPL', 10, 150, cost_basis=120, metadata={'sector': 'Tech'})
    p.add_position('TSLA', 5, 700, cost_basis=650, metadata={'sector': 'Auto'})
    p.add_position('GOLD', 1, 1800, cost_basis=None, metadata={'sector': 'Commodity'})
    return p


def test_position_basic_computations():
    pos = reporting._Position(symbol='X', quantity=2, price=10, cost_basis=8, metadata={'foo': 'bar'})
    assert pos.market_value() == 20.0
    assert pos.cost_value() == 16.0
    assert pos.unrealized_pnl() == pytest.approx(4.0)
    assert pos.return_pct() == pytest.approx((10 - 8) / 8)


def test_position_none_cost_basis_behaviour():
    pos = reporting._Position(symbol='Y', quantity=3, price=5, cost_basis=None)
    assert pos.cost_value() is None
    assert pos.unrealized_pnl() is None
    assert pos.return_pct() is None


def test_position_invalid_init_raises():
    with pytest.raises(ValueError):
        reporting._Position(symbol='Z', quantity=None, price=1)
    with pytest.raises(ValueError):
        reporting._Position(symbol='Z', quantity=1, price=None)


def test_add_and_remove_position_and_normalization():
    pr = reporting.PortfolioReport(name='T')
    pr.add_position('aapl', 1, 2, cost_basis=1)
    # symbol should be upper-cased in storage
    positions = pr.positions()
    assert any(p['symbol'] == 'AAPL' for p in positions)
    # remove returns True
    assert pr.remove_position('aapl') is True
    # removing again returns False
    assert pr.remove_position('aapl') is False


def test_add_position_requires_quantity_and_price():
    pr = reporting.PortfolioReport()
    with pytest.raises(ValueError):
        pr.add_position('X', None, 1)
    with pytest.raises(ValueError):
        pr.add_position('X', 1, None)


def test_update_methods_and_set_cost_basis_errors():
    pr = reporting.PortfolioReport()
    pr.add_position('ABC', 2, 3)
    pr.update_price('abc', 10)
    assert any(p['price'] == 10.0 for p in pr.positions())
    pr.update_quantity('ABC', 5)
    assert any(p['quantity'] == 5.0 for p in pr.positions())
    pr.set_cost_basis('abc', 2)
    assert any(p['cost_basis'] == 2.0 for p in pr.positions())
    # operations on missing symbols raise KeyError
    with pytest.raises(KeyError):
        pr.update_price('MISSING', 1)
    with pytest.raises(KeyError):
        pr.update_quantity('MISSING', 1)
    with pytest.raises(KeyError):
        pr.set_cost_basis('MISSING', 1)


def test_aggregations_and_metrics():
    pr = make_demo_report()
    # market values
    mv = pr.total_market_value()
    assert mv == pytest.approx(1500 + 3500 + 1800)
    # cost basis excludes GOLD (None)
    total_cost = pr.total_cost_basis()
    assert total_cost == pytest.approx(10 * 120 + 5 * 650)
    # unrealized pnl computed as mv - cost where cost exists
    assert pr.unrealized_pnl() == pytest.approx(mv - total_cost)
    # returns mapping
    rets = pr.returns()
    assert rets['AAPL'] == pytest.approx((150 - 120) / 120)
    assert rets['GOLD'] is None


def test_weights_and_zero_total_behaviour():
    pr = reporting.PortfolioReport()
    # empty -> empty weights
    assert pr.weights() == {}
    # positions with zero prices produce zero total and zero weights per symbol
    pr.add_position('Z1', 1, 0)
    pr.add_position('Z2', 2, 0)
    weights = pr.weights()
    assert set(weights.keys()) == {'Z1', 'Z2'}
    assert all(w == 0.0 for w in weights.values())


def test_allocation_by_and_percentages():
    pr = make_demo_report()
    alloc = pr.allocation_by('sector')
    # keys are the sectors provided
    assert alloc['Tech'] == pytest.approx(1500)
    assert alloc['Auto'] == pytest.approx(3500)
    assert alloc['Commodity'] == pytest.approx(1800)
    # percentages sum to ~1.0
    pct = pr.allocation_percentages_by('sector')
    assert pytest.approx(sum(pct.values()), rel=1e-6) == 1.0
    # if total mv is zero, percentages are zeros
    pr_zero = reporting.PortfolioReport()
    pr_zero.add_position('A', 1, 0, metadata={'g': 'x'})
    pct_zero = pr_zero.allocation_percentages_by('g')
    assert all(v == 0.0 for v in pct_zero.values())


def test_positions_include_computed_fields_and_to_json_and_csv():
    pr = make_demo_report()
    pos_list = pr.positions()
    assert all(
        'market_value' in p and 'cost_value' in p and 'unrealized_pnl' in p and 'return_pct' in p
        for p in pos_list
    )

    # to_json parseable and contains expected keys
    js = pr.to_json()
    payload = json.loads(js)
    assert payload['name'] == 'Demo'
    assert 'positions' in payload
    assert isinstance(payload['positions'], list)

    # to_csv returns header and rows matching number of positions
    csv_text = pr.to_csv()
    lines = [l for l in csv_text.splitlines() if l.strip()]
    header = lines[0]
    assert header.startswith('symbol,quantity,price')
    assert len(lines) == 1 + len(pr.positions())


def test_generate_text_report_variations():
    pr = make_demo_report()
    text = pr.generate_text_report()
    # contains key summary lines
    assert 'Portfolio Report: Demo' in text
    assert 'Total Market Value' in text
    # when excluding positions, header 'Symbol' should not appear
    text_no_pos = pr.generate_text_report(include_positions=False)
    assert 'Symbol' not in text_no_pos


def test_unrealized_pnl_when_no_costs_but_some_positions_have_costs():
    # create report with one position without cost and one with cost
    pr = reporting.PortfolioReport()
    pr.add_position('P1', 1, 100, cost_basis=None)
    pr.add_position('P2', 2, 50, cost_basis=40)
    # total_cost_basis is only from P2
    assert pr.total_cost_basis() == pytest.approx(2 * 40)
    # unrealized uses total_mv - total_cost
    assert pr.unrealized_pnl() == pytest.approx(pr.total_market_value() - pr.total_cost_basis())


def test_return_pct_none_when_cost_basis_zero():
    pr = reporting.PortfolioReport()
    pr.add_position('ZERO', 10, 5, cost_basis=0)
    positions = pr.positions()
    assert positions[0]['return_pct'] is None
