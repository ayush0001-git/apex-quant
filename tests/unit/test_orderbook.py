# apex-quant/tests/unit/test_orderbook.py
"""Unit tests for OrderBookAdapter and Level-2 Microstructure calculations."""
from datetime import datetime
import pytest
from apex.adapters.data.orderbook_adapter import OrderBookAdapter
from apex.core.microstructure import MicrostructureService
from apex.domain.orderbook import OrderBookDepth, OrderBookLevel


def test_orderbook_adapter_synthetic_depth_generation():
    depth = OrderBookAdapter.generate_synthetic_depth("RELIANCE.NS", mid_price=2500.0, levels=5)
    
    assert isinstance(depth, OrderBookDepth)
    assert depth.symbol == "RELIANCE.NS"
    assert len(depth.bids) == 5
    assert len(depth.asks) == 5
    assert depth.best_bid < depth.best_ask
    assert depth.mid_price > 0.0
    assert depth.spread > 0.0


def test_microstructure_l2_ofi_calculation():
    depth1 = OrderBookAdapter.generate_synthetic_depth("TCS.NS", mid_price=3500.0)
    # Simulate an aggressive bid stepping up
    bids2 = (OrderBookLevel(price=depth1.best_bid + 0.05, quantity=2500.0),) + depth1.bids[1:]
    depth2 = OrderBookDepth(symbol="TCS.NS", timestamp=datetime.now(), bids=bids2, asks=depth1.asks)
    
    ofi = MicrostructureService.calculate_l2_ofi(depth1, depth2)
    # Price improvement on bid should produce positive OFI (buying pressure)
    assert ofi > 0.0


def test_microstructure_queue_imbalance_and_spread():
    depth = OrderBookAdapter.generate_synthetic_depth("INFY.NS", mid_price=1800.0)
    
    imb = MicrostructureService.calculate_queue_imbalance(depth)
    spread_bps = MicrostructureService.calculate_depth_weighted_spread(depth)
    
    assert -1.0 <= imb <= 1.0
    assert spread_bps > 0.0

