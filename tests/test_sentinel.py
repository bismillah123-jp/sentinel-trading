"""Smoke tests - run: python3 -m pytest tests/  (or python3 tests/test_sentinel.py)"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from sentinel.bus import SignalBus
from sentinel.risk import UnifiedRiskManager
from sentinel.validation import BacktestGate, BacktestReport
from sentinel.orchestrator import Orchestrator, regime_to_profile
from sentinel.strategies import breakout_atr_signals, grid_levels
from workers.arb_worker import ArbScanner, ArbConfig, InventoryTracker, OrderBook


def test_bus():
    bus = SignalBus()
    got = []
    bus.subscribe("regime", got.append)
    bus.publish("regime", {"ticker": "BTC/USDT"})
    assert got and got[0]["ticker"] == "BTC/USDT" and "ts" in got[0]
    print("bus ok")


def test_risk():
    r = UnifiedRiskManager(equity=10_000)
    r.register("breakout_atr", 50.0)
    assert r.update_equity(10_000) == "ok"
    assert r.update_equity(9_600) == "kill"          # -4% day < -3% limit
    r.new_day()
    assert r.update_equity(10_300) == "lock_profit"  # +3% > +2% target
    # vol targeting: higher ATR -> smaller size
    s1 = UnifiedRiskManager.position_size(10_000, atr=10)
    s2 = UnifiedRiskManager.position_size(10_000, atr=100)
    assert s1 > s2 > 0
    ok, _ = r.can_open("breakout_atr", 100)
    assert ok
    ok, why = r.can_open("nope", 100)
    assert not ok and "unknown" in why
    print("risk ok")


def test_gate():
    g = BacktestGate()
    good = BacktestReport("breakout_atr", 120, 55.0, 1.8, 12.0, 34.0, True, True, True)
    p = g.evaluate(good)
    assert p.passed, p.notes
    bad = BacktestReport("yolo", 5, 90.0, 5.0, 60.0, 200.0, False, False, False)
    p2 = g.evaluate(bad)
    assert not p2.passed and "out-of-sample" in p2.notes
    print("gate ok")


def test_regime_routing():
    assert regime_to_profile("bullish", "high") == "breakout_atr"
    assert regime_to_profile("neutral", "low") == "grid"
    assert regime_to_profile("uncertain", "high") == "arb"
    bus, risk, gate = SignalBus(), UnifiedRiskManager(10_000), BacktestGate()
    risk.register("breakout_atr", 50.0)
    risk.register("grid", 30.0)
    risk.register("arb", 20.0)
    orch = Orchestrator(bus, risk, gate)
    # no passport yet -> falls back to arb
    bus.publish("regime", {"ticker": "BTC/USDT", "bias": "bullish",
                           "volatility": "high", "confidence": 0.8})
    assert orch.active["BTC/USDT"] == "arb"
    # register passing passport -> routes to breakout
    rep = BacktestReport("breakout_atr", 120, 55.0, 1.8, 12.0, 34.0, True, True, True)
    orch.register_passport(gate.evaluate(rep))
    bus.publish("regime", {"ticker": "BTC/USDT", "bias": "bullish",
                           "volatility": "high", "confidence": 0.8})
    assert orch.active["BTC/USDT"] == "breakout_atr"
    print("orchestrator ok")


def test_breakout_signals():
    # flat candles then a real breakout bar
    candles = [{"open": 100 + i * 0.1, "high": 101 + i * 0.1,
                "low": 99 + i * 0.1, "close": 100 + i * 0.1, "volume": 10}
               for i in range(40)]
    candles.append({"open": 104, "high": 112, "low": 103, "close": 111,
                    "volume": 500})
    sigs = breakout_atr_signals(candles)
    assert sigs and sigs[-1]["side"] == "long" and sigs[-1]["stop"] < 111
    assert grid_levels(90, 110, 5) == [90.0, 95.0, 100.0, 105.0, 110.0]
    print("strategies ok")


def test_arb():
    deep = [(p, 2.0) for p in [100.0, 99.9, 99.8]]
    scanner = ArbScanner(ArbConfig(min_spread_bps=10))
    books = {
        "binance": OrderBook(bids=[(100.5, 2.0)], asks=[(100.0, 2.0)]),
        "kucoin": OrderBook(bids=[(101.5, 2.0)], asks=[(101.0, 2.0)]),
    }
    opp = scanner.scan(books)
    assert opp is not None and opp.buy_exchange == "binance"
    assert opp.sell_exchange == "kucoin" and opp.net_profit_usd > 0
    # thin book = mirage -> rejected
    thin = {"a": OrderBook(bids=[(100.5, 2.0)], asks=[(100.0, 0.00001)]),
            "b": OrderBook(bids=[(101.5, 2.0)], asks=[(101.0, 2.0)])}
    assert scanner.scan(thin) is None
    # skew tracking
    inv = InventoryTracker()
    inv.apply(opp)
    assert inv.needs_rebalance()  # one-sided trade skews inventory hard
    print("arb ok")


if __name__ == "__main__":
    test_bus(); test_risk(); test_gate(); test_regime_routing()
    test_breakout_signals(); test_arb()
    print("ALL SMOKE TESTS PASSED")
