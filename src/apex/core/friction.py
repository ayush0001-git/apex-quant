# apex-quant/src/apex/core/friction.py
"""Statutory Indian Market Friction Schedule & Transaction Cost Model.

Provides authoritative SEBI and Exchange statutory schedules for Indian Equities:
1. DELIVERY (Cash Equity Swing):
   - STT: 0.1% on Buy AND 0.1% on Sell turnover.
   - Stamp Duty: 0.015% on Buy turnover only.
   - Exchange Turnover Fee (NSE): 0.00325% on total turnover.
   - SEBI Turnover Fee: 0.0001% (₹10 / crore) on total turnover.
   - Brokerage: Flat ₹20 per order or 0.05% (whichever is lower, or ₹0 depending on discount broker).
   - GST: 18% on (Brokerage + Exchange Charges + SEBI Turnover Fee).
2. INTRADAY (MIS / Day Trades):
   - STT: 0.025% on Sell turnover only (0.0% on Buy).
   - Stamp Duty: 0.003% on Buy turnover only.
   - Exchange Turnover Fee: 0.00325% on total turnover.
   - SEBI Turnover Fee: 0.0001% on total turnover.
   - Brokerage: Flat ₹20 per order.
   - GST: 18% on (Brokerage + Exchange Charges + SEBI Turnover Fee).
"""
from dataclasses import dataclass
from typing import Optional, Dict


@dataclass(frozen=True)
class StatutoryBreakdown:
    """Detailed fee breakdown in Indian Rupees (INR)."""
    brokerage: float
    stt: float
    exchange_charges: float
    sebi_charges: float
    stamp_duty: float
    gst: float
    total_statutory_friction: float


class StatutorySchedule:
    """Authoritative SEBI/NSE statutory fee calculator."""

    # Delivery Statutory Rates
    DELIVERY_STT_BUY_PCT: float = 0.0010       # 0.10% on buy
    DELIVERY_STT_SELL_PCT: float = 0.0010      # 0.10% on sell
    DELIVERY_STAMP_DUTY_PCT: float = 0.00015   # 0.015% on buy

    # Intraday Statutory Rates
    INTRADAY_STT_BUY_PCT: float = 0.0000       # 0.0% on buy
    INTRADAY_STT_SELL_PCT: float = 0.00025     # 0.025% on sell
    INTRADAY_STAMP_DUTY_PCT: float = 0.00003   # 0.003% on buy

    # Common Regulatory Charges
    EXCHANGE_TURNOVER_PCT: float = 0.0000325   # NSE 0.00325%
    SEBI_TURNOVER_PCT: float = 0.000001        # SEBI ₹10 / Cr (0.0001%)
    GST_PCT: float = 0.18                      # 18% GST on fees
    DEFAULT_BROKERAGE_PER_ORDER: float = 20.0  # Flat ₹20 per order

    @classmethod
    def calculate_statutory_friction(
        cls,
        turnover: float,
        shares: float,
        is_buy: bool,
        is_delivery: bool = True,
        brokerage_per_order: Optional[float] = None,
    ) -> float:
        """Calculate total statutory fees for a single execution leg."""
        breakdown = cls.breakdown_statutory_friction(
            turnover=turnover,
            shares=shares,
            is_buy=is_buy,
            is_delivery=is_delivery,
            brokerage_per_order=brokerage_per_order,
        )
        return breakdown.total_statutory_friction

    @classmethod
    def breakdown_statutory_friction(
        cls,
        turnover: float,
        shares: float,
        is_buy: bool,
        is_delivery: bool = True,
        brokerage_per_order: Optional[float] = None,
    ) -> StatutoryBreakdown:
        """Compute full itemized fee breakdown for a trade execution leg."""
        if turnover <= 0:
            return StatutoryBreakdown(0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

        flat_brokerage = brokerage_per_order if brokerage_per_order is not None else cls.DEFAULT_BROKERAGE_PER_ORDER
        # Discount broker rule: min(₹20, 0.05% of turnover)
        brokerage = min(flat_brokerage, turnover * 0.0005)

        if is_delivery:
            stt = turnover * (cls.DELIVERY_STT_BUY_PCT if is_buy else cls.DELIVERY_STT_SELL_PCT)
            stamp_duty = (turnover * cls.DELIVERY_STAMP_DUTY_PCT) if is_buy else 0.0
        else:
            stt = turnover * (cls.INTRADAY_STT_BUY_PCT if is_buy else cls.INTRADAY_STT_SELL_PCT)
            stamp_duty = (turnover * cls.INTRADAY_STAMP_DUTY_PCT) if is_buy else 0.0

        exchange_charges = turnover * cls.EXCHANGE_TURNOVER_PCT
        sebi_charges = turnover * cls.SEBI_TURNOVER_PCT
        gst = (brokerage + exchange_charges + sebi_charges) * cls.GST_PCT

        total = round(brokerage + stt + exchange_charges + sebi_charges + stamp_duty + gst, 2)

        return StatutoryBreakdown(
            brokerage=round(brokerage, 2),
            stt=round(stt, 2),
            exchange_charges=round(exchange_charges, 2),
            sebi_charges=round(sebi_charges, 2),
            stamp_duty=round(stamp_duty, 2),
            gst=round(gst, 2),
            total_statutory_friction=total,
        )

    @classmethod
    def roundtrip_friction(
        cls,
        entry_price: float,
        exit_price: float,
        shares: float,
        is_delivery: bool = True,
        brokerage_per_order: Optional[float] = None,
    ) -> StatutoryBreakdown:
        """Calculate complete round-trip (Entry + Exit) statutory friction."""
        buy_turnover = entry_price * shares
        sell_turnover = exit_price * shares

        b1 = cls.breakdown_statutory_friction(buy_turnover, shares, is_buy=True, is_delivery=is_delivery, brokerage_per_order=brokerage_per_order)
        b2 = cls.breakdown_statutory_friction(sell_turnover, shares, is_buy=False, is_delivery=is_delivery, brokerage_per_order=brokerage_per_order)

        return StatutoryBreakdown(
            brokerage=round(b1.brokerage + b2.brokerage, 2),
            stt=round(b1.stt + b2.stt, 2),
            exchange_charges=round(b1.exchange_charges + b2.exchange_charges, 2),
            sebi_charges=round(b1.sebi_charges + b2.sebi_charges, 2),
            stamp_duty=round(b1.stamp_duty + b2.stamp_duty, 2),
            gst=round(b1.gst + b2.gst, 2),
            total_statutory_friction=round(b1.total_statutory_friction + b2.total_statutory_friction, 2),
        )
