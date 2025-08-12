# account_management.py
"""
Module: account_management
Provides two classes: UserAccount and Portfolio.

Design goals implemented (reasonable, robust defaults):
- Portfolio manages holdings (symbol -> float quantity).
- Portfolio methods: buy, sell, get_quantity, as_dict, from_dict, total_value.
- UserAccount holds username, email, cash balance, and a Portfolio instance.
- UserAccount methods: deposit, withdraw, buy, sell, transfer_to, as_dict, from_dict.
- Validation, clear exceptions, and type hints included.
- Serialization to/from dict and json-compatible structures.

No external dependencies.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, Dict, Optional, Any


class InsufficientFundsError(Exception):
    """Raised when an account does not have enough cash for an operation."""


class InsufficientHoldingsError(Exception):
    """Raised when a portfolio does not have enough of a symbol to sell."""


class InvalidOperationError(Exception):
    """Raised when an operation is invalid (e.g., negative quantity)."""


@dataclass
class Portfolio:
    """A simple portfolio representing holdings of symbols.

    holdings is a mapping from ticker symbol (str) to quantity (float).
    """

    holdings: Dict[str, float] = field(default_factory=dict)

    def buy(self, symbol: str, quantity: float) -> None:
        """Increase holdings of symbol by quantity.

        Args:
            symbol: ticker symbol (case-insensitive internally stored as upper()).
            quantity: positive number of units to add.

        Raises:
            InvalidOperationError: if quantity is not positive.
        """
        if quantity <= 0:
            raise InvalidOperationError("Buy quantity must be positive")
        key = symbol.upper()
        self.holdings[key] = self.holdings.get(key, 0.0) + float(quantity)

    def sell(self, symbol: str, quantity: float) -> None:
        """Decrease holdings of symbol by quantity.

        Args:
            symbol: ticker symbol (case-insensitive).
            quantity: positive number of units to remove.

        Raises:
            InvalidOperationError: if quantity is not positive.
            InsufficientHoldingsError: if holdings are insufficient.
        """
        if quantity <= 0:
            raise InvalidOperationError("Sell quantity must be positive")
        key = symbol.upper()
        current = self.holdings.get(key, 0.0)
        if quantity > current + 1e-12:  # small epsilon for float rounding
            raise InsufficientHoldingsError(
                f"Not enough holdings to sell: {symbol} (have {current}, tried to sell {quantity})"
            )
        new = current - float(quantity)
        if new <= 0:
            # remove symbol to keep holdings tidy
            self.holdings.pop(key, None)
        else:
            self.holdings[key] = new

    def get_quantity(self, symbol: str) -> float:
        """Return the quantity held for a symbol (0.0 if none)."""
        return float(self.holdings.get(symbol.upper(), 0.0))

    def total_value(self, price_source: Optional[Dict[str, float]] = None, price_func: Optional[Callable[[str], float]] = None) -> float:
        """Compute total market value of the portfolio.

        Provide either price_source (a dict mapping symbol->price) or price_func (callable taking symbol and returning price).
        If both provided, price_func takes precedence.

        Raises:
            ValueError: if neither price_source nor price_func is provided.
        """
        if price_func is None and price_source is None:
            raise ValueError("Provide price_source (dict) or price_func(callable) to compute total value")
        total = 0.0
        for sym, qty in self.holdings.items():
            price = None
            if price_func is not None:
                price = price_func(sym)
            else:
                # price_source is not None here
                price = price_source.get(sym)
            if price is None:
                raise ValueError(f"Missing price for symbol: {sym}")
            total += float(qty) * float(price)
        return total

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the portfolio."""
        # ensure quantities are plain floats
        return {sym: float(qty) for sym, qty in sorted(self.holdings.items())}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Portfolio":
        """Create a Portfolio from a dict mapping symbols to quantities."""
        if not isinstance(data, dict):
            raise TypeError("Portfolio.from_dict expects a dict")
        # normalize keys to upper and ensure floats
        normalized: Dict[str, float] = {}
        for k, v in data.items():
            if v is None:
                continue
            try:
                qty = float(v)
            except Exception as e:
                raise TypeError(f"Invalid quantity for symbol {k}: {v!r}") from e
            if qty <= 0:
                # ignore non-positive holdings
                continue
            normalized[k.upper()] = qty
        return cls(holdings=normalized)

    def __repr__(self) -> str:
        return f"Portfolio(holdings={self.holdings})"


@dataclass
class UserAccount:
    """Represents a user account with cash balance and a portfolio.

    Attributes:
        username: unique identifier for the user (string).
        email: contact email.
        balance: cash balance in account currency (float).
        portfolio: Portfolio instance owned by the user.
        created_at: ISO timestamp of account creation.
    """

    username: str
    email: str
    balance: float = 0.0
    portfolio: Portfolio = field(default_factory=Portfolio)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")

    def __post_init__(self) -> None:
        if not isinstance(self.username, str) or not self.username:
            raise ValueError("username must be a non-empty string")
        if not isinstance(self.email, str) or "@" not in self.email:
            raise ValueError("email must be a valid email string")
        try:
            self.balance = float(self.balance)
        except Exception:
            raise TypeError("balance must be numeric")

    def deposit(self, amount: float) -> None:
        """Deposit cash into the account.

        Amount must be positive.
        """
        if amount <= 0:
            raise InvalidOperationError("Deposit amount must be positive")
        self.balance += float(amount)

    def withdraw(self, amount: float) -> None:
        """Withdraw cash from the account. Requires sufficient balance."""
        if amount <= 0:
            raise InvalidOperationError("Withdraw amount must be positive")
        if amount > self.balance + 1e-12:
            raise InsufficientFundsError(f"Insufficient funds: have {self.balance}, tried to withdraw {amount}")
        self.balance -= float(amount)

    def buy(self, symbol: str, quantity: float, price: float) -> None:
        """Buy quantity of symbol at given price per unit.

        Deducts cash (quantity * price) from balance and adds to portfolio holdings.
        Raises InsufficientFundsError if balance is insufficient.
        """
        if quantity <= 0 or price < 0:
            raise InvalidOperationError("Quantity must be positive and price must be non-negative")
        cost = float(quantity) * float(price)
        if cost > self.balance + 1e-12:
            raise InsufficientFundsError(f"Insufficient funds to buy: cost {cost}, balance {self.balance}")
        # perform transaction
        self.balance -= cost
        self.portfolio.buy(symbol, quantity)

    def sell(self, symbol: str, quantity: float, price: float) -> None:
        """Sell quantity of symbol at given price per unit.

        Removes holdings and credits cash (quantity * price) to balance.
        Raises InsufficientHoldingsError if holdings insufficient.
        """
        if quantity <= 0 or price < 0:
            raise InvalidOperationError("Quantity must be positive and price must be non-negative")
        # will raise InsufficientHoldingsError if not enough
        self.portfolio.sell(symbol, quantity)
        proceeds = float(quantity) * float(price)
        self.balance += proceeds

    def transfer_to(self, other: "UserAccount", amount: float) -> None:
        """Transfer cash amount to another UserAccount.

        Raises InsufficientFundsError if source has insufficient balance.
        """
        if not isinstance(other, UserAccount):
            raise TypeError("transfer_to requires another UserAccount instance")
        if amount <= 0:
            raise InvalidOperationError("Transfer amount must be positive")
        if amount > self.balance + 1e-12:
            raise InsufficientFundsError(f"Insufficient funds to transfer: have {self.balance}, tried {amount}")
        self.balance -= float(amount)
        other.balance += float(amount)

    def as_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable representation of the account."""
        return {
            "username": self.username,
            "email": self.email,
            "balance": float(self.balance),
            "portfolio": self.portfolio.as_dict(),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserAccount":
        """Construct a UserAccount from a dict as produced by as_dict."""
        if not isinstance(data, dict):
            raise TypeError("UserAccount.from_dict expects a dict")
        username = data.get("username")
        email = data.get("email")
        balance = data.get("balance", 0.0)
        portfolio_data = data.get("portfolio", {})
        created_at = data.get("created_at", datetime.utcnow().isoformat() + "Z")
        portfolio = Portfolio.from_dict(portfolio_data) if isinstance(portfolio_data, dict) else Portfolio()
        return cls(username=username, email=email, balance=balance, portfolio=portfolio, created_at=created_at)

    def __repr__(self) -> str:
        return (
            f"UserAccount(username={self.username!r}, email={self.email!r}, balance={self.balance:.2f}, "
            f"portfolio={self.portfolio!r}, created_at={self.created_at!r})"
        )


# If run as a script, demonstrate simple usage (kept minimal and safe).
if __name__ == "__main__":
    acc = UserAccount(username="alice", email="alice@example.com", balance=1000.0)
    acc.buy("AAPL", quantity=2, price=150.0)
    acc.sell("AAPL", quantity=1, price=155.0)
    print(acc)
    print("Portfolio value with prices={'AAPL': 160}:", acc.portfolio.total_value(price_source={"AAPL": 160}))

