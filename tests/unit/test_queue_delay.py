# apex-quant/tests/unit/test_queue_delay.py
"""Unit tests for Queue-Delay Slippage and Fill Realism."""
from apex.core.slippage import DynamicSlippageModel, FillStatus
from apex.domain.orderbook import OrderBookDepth, OrderBookLevel
from datetime import datetime


def test_queue_delay_deep_penetration_full_fill():
    model = DynamicSlippageModel()
    report = model.evaluate_limit_order_fill(
        limit_price=2500.0,
        order_shares=100.0,
        is_buy=True,
        bar_high=2515.0,
        bar_low=2485.0,
        bar_close=2502.0,
        bar_volume=150_000.0,
    )
    assert report.status == FillStatus.FILLED
    assert report.fill_ratio == 1.0
    assert report.shares_filled == 100.0
    assert report.fill_probability >= 0.80
    assert report.effective_fill_price == 2500.0


def test_queue_delay_touch_only_partial_or_unfilled():
    model = DynamicSlippageModel()
    # Bar low strictly touches limit price 2500.0
    report = model.evaluate_limit_order_fill(
        limit_price=2500.0,
        order_shares=100.0,
        is_buy=True,
        bar_high=2515.0,
        bar_low=2500.0,
        bar_close=2508.0,
        bar_volume=50_000.0,
    )
    # Touch only should suffer severe queue penalty
    assert report.fill_probability <= 0.40
    assert report.status in (FillStatus.PARTIAL, FillStatus.UNFILLED)
    assert report.shares_filled < 100.0


def test_queue_delay_unreached_order_unfilled():
    model = DynamicSlippageModel()
    # Bar low never touches limit buy price 2500.0
    report = model.evaluate_limit_order_fill(
        limit_price=2500.0,
        order_shares=100.0,
        is_buy=True,
        bar_high=2530.0,
        bar_low=2505.0,
        bar_close=2510.0,
        bar_volume=100_000.0,
    )
    assert report.status == FillStatus.UNFILLED
    assert report.fill_ratio == 0.0
    assert report.shares_filled == 0.0


def test_queue_delay_with_l2_depth_book():
    depth = OrderBookDepth(
        symbol="RELIANCE.NS",
        timestamp=datetime.now(),
        bids=(
            OrderBookLevel(price=2500.0, quantity=5000.0),
            OrderBookLevel(price=2499.0, quantity=10000.0),
        ),
        asks=(
            OrderBookLevel(price=2501.0, quantity=4000.0),
            OrderBookLevel(price=2502.0, quantity=8000.0),
        ),
    )
    model = DynamicSlippageModel()
    report = model.evaluate_limit_order_fill(
        limit_price=2500.0,
        order_shares=500.0,
        is_buy=True,
        bar_high=2508.0,
        bar_low=2495.0,
        bar_close=2498.0,
        bar_volume=80_000.0,
        l2_depth=depth,
    )
    assert report.queue_ahead_shares >= 5000.0
    assert report.queue_delay_ms > 0.0


def test_market_order_latency_penalty():
    model = DynamicSlippageModel()
    quote_limit = model.estimate_slippage(turnover=100000.0, shares=40.0, spot_price=2500.0, is_market_order=False)
    quote_market = model.estimate_slippage(turnover=100000.0, shares=40.0, spot_price=2500.0, is_market_order=True)

    # Market order should pay latency penalty
    assert quote_market.latency_penalty_bps > 0.0
    assert quote_market.slippage_bps > quote_limit.slippage_bps

