"""Arbitrage worker - barbotine's idea, hardened.

Barbotine got the core right (cross-exchange, no transfers, fee-aware).
What it lacked - and what killed most retail arb bots by 2026:
  1. Liquidity filter: a "spread" on a 0.001 BTC-deep book is a mirage.
     We require real depth before we believe a quote.
  2. Slippage buffer: top-of-book fills are fantasy at size; demand spread >
     fees + buffer.
  3. Skew-driven rebalance: instead of blind timed rebalancing, rebalance when
     inventory skew actually threatens the next trade.

This module is exchange-agnostic: feed it order books, get opportunities.
Wire real books via ccxt.pro in production (see README).
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class OrderBook:
    bids: list[tuple[float, float]]  # [(price, qty)] best first
    asks: list[tuple[float, float]]


@dataclass
class Opportunity:
    buy_exchange: str
    sell_exchange: str
    buy_price: float
    sell_price: float
    qty: float
    gross_spread_pct: float
    net_profit_usd: float


def top_depth(book: OrderBook, side: str, levels: int) -> float:
    rows = book.bids if side == "bid" else book.asks
    return sum(q for _, q in rows[:levels])


@dataclass
class ArbConfig:
    taker_fee_pct: float = 0.10      # per side, in %
    min_spread_bps: float = 15.0     # minimum net edge after fees, basis points
    slippage_bps: float = 5.0        # assumed adverse move during execution
    depth_levels: int = 3            # top-N levels must hold the size
    min_qty: float = 0.001           # minimum tradable size (base asset)
    max_notional_usd: float = 1000.0


class ArbScanner:
    def __init__(self, cfg: ArbConfig | None = None) -> None:
        self.cfg = cfg or ArbConfig()

    def scan(self, books: dict[str, OrderBook],
             qty: float | None = None) -> Opportunity | None:
        """Return the best executable opportunity, or None."""
        cfg = self.cfg
        best: Opportunity | None = None
        for buy_ex, buy_book in books.items():
            if not buy_book.asks:
                continue
            for sell_ex, sell_book in books.items():
                if sell_ex == buy_ex or not sell_book.bids:
                    continue
                ask, ask_q = buy_book.asks[0][0], top_depth(buy_book, "ask", cfg.depth_levels)
                bid, bid_q = sell_book.bids[0][0], top_depth(sell_book, "bid", cfg.depth_levels)
                if bid <= ask:
                    continue
                size = qty or min(ask_q, bid_q, cfg.max_notional_usd / ask)
                if size < cfg.min_qty:
                    continue  # mirage spread on a thin book
                gross_bps = (bid - ask) / ask * 10_000
                cost_bps = cfg.taker_fee_pct * 100 * 2 + cfg.slippage_bps
                net_bps = gross_bps - cost_bps
                if net_bps < cfg.min_spread_bps:
                    continue
                notional = size * ask
                net_usd = notional * net_bps / 10_000
                opp = Opportunity(buy_ex, sell_ex, ask, bid, size,
                                  gross_bps / 100, net_usd)
                if best is None or opp.net_profit_usd > best.net_profit_usd:
                    best = opp
        return best


@dataclass
class InventoryTracker:
    """Tracks per-exchange base/quote balances; flags skew rebalances."""
    balances: dict[str, dict[str, float]] = field(default_factory=dict)
    # balances[exchange] = {"base": .., "quote": ..}
    skew_threshold_pct: float = 30.0

    def apply(self, opp: Opportunity) -> None:
        b = self.balances.setdefault(opp.buy_exchange, {"base": 0.0, "quote": 0.0})
        s = self.balances.setdefault(opp.sell_exchange, {"base": 0.0, "quote": 0.0})
        b["base"] += opp.qty
        b["quote"] -= opp.qty * opp.buy_price
        s["base"] -= opp.qty
        s["quote"] += opp.qty * opp.sell_price

    def skew(self, exchange: str) -> float:
        """|base_value - quote| / total, in %. High skew = rebalance soon."""
        bal = self.balances.get(exchange)
        if not bal:
            return 0.0
        base_v = abs(bal["base"])  # valued roughly at 1.0 for skew purposes
        quote_v = abs(bal["quote"])
        total = base_v + quote_v
        if total <= 0:
            return 0.0
        return abs(base_v - quote_v) / total * 100

    def needs_rebalance(self) -> list[str]:
        return [ex for ex in self.balances
                if self.skew(ex) >= self.skew_threshold_pct]
