# apex-quant/src/apex/domain/orderbook.py
"""Level-2 Order Book and Depth Data Models. Pure domain, zero dependencies."""
from dataclasses import dataclass
from datetime import datetime
from typing import Tuple


@dataclass(frozen=True)
class OrderBookLevel:
    """A single price level in the limit order book."""
    price: float
    quantity: float
    orders_count: int = 1


@dataclass(frozen=True)
class OrderBookDepth:
    """Full Level-2 snapshot of top-N bid and ask levels."""
    symbol: str
    timestamp: datetime
    bids: Tuple[OrderBookLevel, ...]
    asks: Tuple[OrderBookLevel, ...]

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0

    @property
    def mid_price(self) -> float:
        if self.best_bid > 0 and self.best_ask > 0:
            return round((self.best_bid + self.best_ask) / 2.0, 2)
        return self.best_bid or self.best_ask

    @property
    def spread(self) -> float:
        if self.best_ask > 0 and self.best_bid > 0:
            return round(self.best_ask - self.best_bid, 2)
        return 0.0
