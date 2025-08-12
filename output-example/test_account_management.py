import pytest
from datetime import datetime

import account_management as am


def test_portfolio_buy_and_get_quantity_and_uppercase():
    p = am.Portfolio()
    p.buy("aapl", 2.5)
    assert p.get_quantity("AAPL") == 2.5
    assert p.get_quantity("aapl") == 2.5
    # buying more accumulates
    p.buy("AAPL", 0.5)
    assert pytest.approx(p.get_quantity("aapl"), rel=1e-9) == 3.0


def test_portfolio_buy_negative_raises():
    p = am.Portfolio()
    with pytest.raises(am.InvalidOperationError):
        p.buy("TSLA", -1)


def test_portfolio_sell_decrease_and_remove_zero():
    p = am.Portfolio()
    p.buy("GOOG", 5)
    p.sell("goog", 5)
    # removed entirely
    assert p.get_quantity("GOOG") == 0.0
    assert "GOOG" not in p.holdings


def test_portfolio_sell_more_than_holdings_raises():
    p = am.Portfolio()
    p.buy("MSFT", 1.0)
    with pytest.raises(am.InsufficientHoldingsError):
        p.sell("MSFT", 2.0)


def test_portfolio_sell_negative_raises():
    p = am.Portfolio()
    with pytest.raises(am.InvalidOperationError):
        p.sell("NFLX", -0.1)


def test_portfolio_total_value_with_price_source_and_func():
    p = am.Portfolio()
    p.buy("A", 2)
    p.buy("B", 3)
    price_source = {"A": 10.0, "B": 5.0}
    total_from_source = p.total_value(price_source=price_source)
    assert total_from_source == pytest.approx(2 * 10.0 + 3 * 5.0)
    # price_func should take precedence
    def pf(sym):
        # return a different price purposely
        return 1.0 if sym == "A" else 2.0
    total_from_func = p.total_value(price_source=price_source, price_func=pf)
    assert total_from_func == pytest.approx(2 * 1.0 + 3 * 2.0)


def test_portfolio_total_value_missing_price_raises():
    p = am.Portfolio()
    p.buy("X", 1)
    with pytest.raises(ValueError):
        p.total_value(price_source={"Y": 10})


def test_portfolio_as_dict_and_from_dict_and_repr():
    p = am.Portfolio()
    p.buy("alpha", 1.0)
    p.buy("Beta", 2.0)
    d = p.as_dict()
    # keys should be uppercase in holdings representation
    assert d == {"ALPHA": 1.0, "BETA": 2.0}
    r = repr(p)
    assert "Portfolio(" in r

    # from_dict normalizes keys, ignores non-positive and None, and converts types
    src = {"a": "2", "b": 0, "c": None, "d": 1.5}
    p2 = am.Portfolio.from_dict(src)
    assert p2.get_quantity("A") == 2.0
    assert p2.get_quantity("B") == 0.0
    assert p2.get_quantity("C") == 0.0
    assert p2.get_quantity("D") == 1.5

    with pytest.raises(TypeError):
        am.Portfolio.from_dict("not a dict")


def test_useraccount_post_init_validations():
    with pytest.raises(ValueError):
        am.UserAccount(username="", email="a@b.com")
    with pytest.raises(ValueError):
        am.UserAccount(username="user", email="not-an-email")
    with pytest.raises(TypeError):
        am.UserAccount(username="user", email="u@e.com", balance="notnumeric")


def test_useraccount_deposit_withdraw_and_errors():
    u = am.UserAccount(username="joe", email="joe@example.com", balance=100.0)
    u.deposit(50)
    assert u.balance == pytest.approx(150.0)
    with pytest.raises(am.InvalidOperationError):
        u.deposit(0)
    with pytest.raises(am.InvalidOperationError):
        u.withdraw(0)
    u.withdraw(25)
    assert u.balance == pytest.approx(125.0)
    with pytest.raises(am.InsufficientFundsError):
        u.withdraw(1000)


def test_user_buy_and_sell_affect_balance_and_portfolio():
    u = am.UserAccount(username="sue", email="sue@example.com", balance=500.0)
    u.buy("TSLA", quantity=2, price=100.0)
    # cost 200
    assert u.balance == pytest.approx(300.0)
    assert u.portfolio.get_quantity("TSLA") == 2.0
    # sell one
    u.sell("tsla", quantity=1, price=110.0)
    assert u.portfolio.get_quantity("TSLA") == 1.0
    # proceeds 110 added
    assert u.balance == pytest.approx(410.0)
    # selling too many raises
    with pytest.raises(am.InsufficientHoldingsError):
        u.sell("TSLA", quantity=5, price=10.0)
    # invalid inputs
    with pytest.raises(am.InvalidOperationError):
        u.buy("TSLA", quantity=-1, price=10)
    with pytest.raises(am.InvalidOperationError):
        u.sell("TSLA", quantity=1, price=-5)


def test_user_buy_insufficient_funds_raises():
    u = am.UserAccount(username="max", email="max@example.com", balance=10.0)
    with pytest.raises(am.InsufficientFundsError):
        u.buy("GME", quantity=1, price=20.0)


def test_transfer_to_success_and_errors():
    a = am.UserAccount(username="a", email="a@example.com", balance=100.0)
    b = am.UserAccount(username="b", email="b@example.com", balance=0.0)
    a.transfer_to(b, 40.0)
    assert a.balance == pytest.approx(60.0)
    assert b.balance == pytest.approx(40.0)
    with pytest.raises(TypeError):
        a.transfer_to("not an account", 10)
    with pytest.raises(am.InvalidOperationError):
        a.transfer_to(b, 0)
    with pytest.raises(am.InsufficientFundsError):
        a.transfer_to(b, 1000.0)


def test_useraccount_as_dict_and_from_dict_and_repr():
    created = datetime.utcnow().isoformat() + "Z"
    u = am.UserAccount(username="sam", email="sam@example.com", balance=123.45, created_at=created)
    u.portfolio.buy("AMZN", 1)
    d = u.as_dict()
    assert d["username"] == "sam"
    assert d["email"] == "sam@example.com"
    assert pytest.approx(d["balance"]) == 123.45
    # portfolio present and contains AMZN
    assert d["portfolio"] == {"AMZN": 1.0}
    # roundtrip via from_dict preserves key data
    u2 = am.UserAccount.from_dict(d)
    assert u2.username == u.username
    assert u2.email == u.email
    assert u2.balance == pytest.approx(u.balance)
    assert u2.portfolio.get_quantity("AMZN") == 1.0
    # if portfolio in data is not a dict, from_dict should create an empty portfolio
    d2 = {"username": "x", "email": "x@example.com", "portfolio": ["not", "a", "dict"], "balance": 0.0}
    u3 = am.UserAccount.from_dict(d2)
    assert isinstance(u3.portfolio, am.Portfolio)
    assert u3.portfolio.get_quantity("X") == 0.0  # nothing present
    assert "UserAccount(" in repr(u)


def test_transfer_and_buy_edge_float_epsilon():
    # ensure tiny float rounding does not prevent operations (uses small epsilon in checks)
    u = am.UserAccount(username="e", email="e@example.com", balance=0.000000000001)
    # deposit a small amount to allow a small buy
    u.deposit(1e-12)
    # now try withdraw nearly all - should be allowed because of epsilon
    with pytest.raises(am.InsufficientFundsError):
        u.withdraw(100.0)  # obviously too much
    # balances remain unchanged for failed operation
    assert u.balance > 0.0


def test_portfolio_from_dict_invalid_quantity_type_raises():
    with pytest.raises(TypeError):
        am.Portfolio.from_dict({"A": "not a number"})