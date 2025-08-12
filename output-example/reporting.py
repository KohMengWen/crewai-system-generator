from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Dict, Optional, Any, Iterable
import json
import csv
import io


@dataclass
class _Position:
    symbol: str
    quantity: float
    price: float
    cost_basis: Optional[float] = None
    metadata: Dict[str, Any] = None

    def __post_init__(self):
        if self.quantity is None:
            raise ValueError("quantity must be provided and non-null")
        if self.price is None:
            raise ValueError("price must be provided and non-null")
        if self.metadata is None:
            self.metadata = {}

    def market_value(self) -> float:
        return float(self.quantity) * float(self.price)

    def cost_value(self) -> Optional[float]:
        if self.cost_basis is None:
            return None
        return float(self.quantity) * float(self.cost_basis)

    def unrealized_pnl(self) -> Optional[float]:
        if self.cost_basis is None:
            return None
        return self.market_value() - self.cost_value()

    def return_pct(self) -> Optional[float]:
        if self.cost_basis is None or self.cost_basis == 0:
            return None
        return (self.price - self.cost_basis) / float(self.cost_basis)


class PortfolioReport:
    """
    PortfolioReport stores a collection of positions and provides methods
    to compute aggregate metrics and export reports.

    Position fields (per position):
    - symbol: str
    - quantity: float
    - price: float
    - cost_basis: Optional[float]
    - metadata: dict (optional arbitrary metadata, e.g., sector)

    Example usage:
        p = PortfolioReport(name='My Portfolio')
        p.add_position('AAPL', 10, 150, cost_basis=120, metadata={'sector':'Tech'})
        total = p.total_market_value()
        report_text = p.generate_text_report()
    """

    def __init__(self, positions: Optional[Iterable[Dict[str, Any]]] = None, currency: str = 'USD', name: str = 'Portfolio'):
        self.name = name
        self.currency = currency
        self._positions: Dict[str, _Position] = {}
        if positions:
            for pos in positions:
                self.add_position(
                    pos['symbol'],
                    pos.get('quantity', 0),
                    pos.get('price', 0),
                    cost_basis=pos.get('cost_basis'),
                    metadata=pos.get('metadata'),
                )

    # -- CRUD operations --
    def add_position(self, symbol: str, quantity: float, price: float, cost_basis: Optional[float] = None, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a new position or replace existing one with the same symbol."""
        if quantity is None or price is None:
            raise ValueError('quantity and price are required')
        symbol = str(symbol).upper()
        self._positions[symbol] = _Position(symbol=symbol, quantity=float(quantity), price=float(price), cost_basis=(None if cost_basis is None else float(cost_basis)), metadata=(dict(metadata) if metadata else {}))

    def remove_position(self, symbol: str) -> bool:
        """Remove a position by symbol. Returns True if removed, False if not found."""
        symbol = str(symbol).upper()
        return self._positions.pop(symbol, None) is not None

    def update_price(self, symbol: str, price: float) -> None:
        """Update market price for a given symbol. Raises KeyError if not found."""
        symbol = str(symbol).upper()
        pos = self._positions.get(symbol)
        if pos is None:
            raise KeyError(f"Position '{symbol}' not found")
        pos.price = float(price)

    def update_quantity(self, symbol: str, quantity: float) -> None:
        symbol = str(symbol).upper()
        pos = self._positions.get(symbol)
        if pos is None:
            raise KeyError(f"Position '{symbol}' not found")
        pos.quantity = float(quantity)

    def set_cost_basis(self, symbol: str, cost_basis: float) -> None:
        symbol = str(symbol).upper()
        pos = self._positions.get(symbol)
        if pos is None:
            raise KeyError(f"Position '{symbol}' not found")
        pos.cost_basis = float(cost_basis)

    # -- Accessors --
    def positions(self) -> List[Dict[str, Any]]:
        """Return a list of positions as dicts (copies)."""
        return [self._position_to_dict(p) for p in self._positions.values()]

    def _position_to_dict(self, p: _Position) -> Dict[str, Any]:
        d = asdict(p)
        # ensure computed fields are provided
        d['market_value'] = p.market_value()
        d['cost_value'] = p.cost_value()
        d['unrealized_pnl'] = p.unrealized_pnl()
        d['return_pct'] = p.return_pct()
        return d

    # -- Aggregations and metrics --
    def total_market_value(self) -> float:
        return sum(p.market_value() for p in self._positions.values())

    def total_cost_basis(self) -> Optional[float]:
        vals = [p.cost_value() for p in self._positions.values() if p.cost_value() is not None]
        if not vals:
            return None
        return sum(vals)

    def unrealized_pnl(self) -> Optional[float]:
        cost = self.total_cost_basis()
        if cost is None:
            # If no cost basis data available, compute sum of available pnl if any
            vals = [p.unrealized_pnl() for p in self._positions.values() if p.unrealized_pnl() is not None]
            if not vals:
                return None
            return sum(vals)
        return self.total_market_value() - cost

    def weights(self) -> Dict[str, float]:
        """Return weight of each position by market value. Sum may be 0 if no positions."""
        total = self.total_market_value()
        if total == 0:
            # return zero weights
            return {s: 0.0 for s in self._positions}
        return {s: (p.market_value() / total) for s, p in self._positions.items()}

    def returns(self) -> Dict[str, Optional[float]]:
        return {s: p.return_pct() for s, p in self._positions.items()}

    def allocation_by(self, key: str) -> Dict[Any, float]:
        """Aggregate market value by metadata key (e.g., sector).

        Positions missing the key are grouped under None.
        """
        agg: Dict[Any, float] = {}
        for p in self._positions.values():
            k = p.metadata.get(key) if p.metadata else None
            agg[k] = agg.get(k, 0.0) + p.market_value()
        return agg

    def allocation_percentages_by(self, key: str) -> Dict[Any, float]:
        total = self.total_market_value()
        agg = self.allocation_by(key)
        if total == 0:
            return {k: 0.0 for k in agg}
        return {k: (v / total) for k, v in agg.items()}

    # -- Export / Reporting --
    def generate_text_report(self, include_positions: bool = True, decimals: int = 2) -> str:
        lines: List[str] = []
        lines.append(f"Portfolio Report: {self.name}")
        lines.append(f"Currency: {self.currency}")
        lines.append("")
        total_mv = self.total_market_value()
        total_cost = self.total_cost_basis()
        unreal = self.unrealized_pnl()
        lines.append(f"Total Market Value: {total_mv:.{decimals}f}")
        lines.append(f"Total Cost Basis: {('N/A' if total_cost is None else f'{total_cost:.{decimals}f}')}")
        lines.append(f"Unrealized P&L: {('N/A' if unreal is None else f'{unreal:.{decimals}f}')}")
        lines.append("")
        if include_positions:
            hdr = ["Symbol", "Qty", "Price", "Mkt Value", "Cost Value", "Unreal P&L", "Return%"]
            col_widths = [max(len(h), 8) for h in hdr]
            # compute column widths from data
            pos_dicts = self.positions()
            for pd in pos_dicts:
                col_widths[0] = max(col_widths[0], len(str(pd.get('symbol', ''))))
            # header
            lines.append(" | ".join(h.ljust(w) for h, w in zip(hdr, col_widths)))
            lines.append("-" * (sum(col_widths) + 3 * (len(hdr) - 1)))
            for pd in pos_dicts:
                symbol = str(pd.get('symbol', ''))
                qty = pd.get('quantity', 0)
                price = pd.get('price', 0)
                mv = pd.get('market_value', 0)
                cv = pd.get('cost_value')
                upnl = pd.get('unrealized_pnl')
                ret = pd.get('return_pct')
                cv_s = 'N/A' if cv is None else f"{cv:.{decimals}f}"
                upnl_s = 'N/A' if upnl is None else f"{upnl:.{decimals}f}"
                ret_s = 'N/A' if ret is None else f"{ret * 100:.{decimals}f}%"
                row = [
                    symbol.ljust(col_widths[0]),
                    f"{qty:.{decimals}f}".rjust(col_widths[1]),
                    f"{price:.{decimals}f}".rjust(col_widths[2]),
                    f"{mv:.{decimals}f}".rjust(col_widths[3]),
                    cv_s.rjust(col_widths[4]),
                    upnl_s.rjust(col_widths[5]),
                    ret_s.rjust(col_widths[6]),
                ]
                lines.append(" | ".join(row))
        return "\n".join(lines)

    def to_json(self, indent: Optional[int] = 2) -> str:
        payload = {
            'name': self.name,
            'currency': self.currency,
            'total_market_value': self.total_market_value(),
            'total_cost_basis': self.total_cost_basis(),
            'unrealized_pnl': self.unrealized_pnl(),
            'positions': self.positions(),
        }
        return json.dumps(payload, indent=indent, default=str)

    def to_csv(self) -> str:
        """Return CSV string of positions with computed fields."""
        output = io.StringIO()
        fieldnames = ['symbol', 'quantity', 'price', 'market_value', 'cost_basis', 'cost_value', 'unrealized_pnl', 'return_pct']
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for p in self.positions():
            row = {
                'symbol': p.get('symbol'),
                'quantity': p.get('quantity'),
                'price': p.get('price'),
                'market_value': p.get('market_value'),
                'cost_basis': p.get('cost_basis'),
                'cost_value': p.get('cost_value'),
                'unrealized_pnl': p.get('unrealized_pnl'),
                'return_pct': p.get('return_pct'),
            }
            writer.writerow(row)
        return output.getvalue()


# Module quick demonstration when run as script
if __name__ == '__main__':
    # small demo to show functionality
    demo = PortfolioReport(name='Demo Portfolio')
    demo.add_position('AAPL', 10, 150, cost_basis=120, metadata={'sector': 'Technology'})
    demo.add_position('TSLA', 5, 700, cost_basis=650, metadata={'sector': 'Automotive'})
    demo.add_position('GOLD', 1, 1800, cost_basis=None, metadata={'sector': 'Commodity'})
    print(demo.generate_text_report())
    print('\nJSON:')
    print(demo.to_json())