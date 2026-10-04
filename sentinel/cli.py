"""Sentinel CLI - one entry point for everything.

Usage:
  sentinel demo     Full end-to-end simulation (no exchange, no keys needed)
  sentinel doctor   Check environment: python, TA dir, freqtrade reachability
  sentinel run      Paper-mode orchestration loop (reads config.yml)
  sentinel version  Show version
"""
from __future__ import annotations

import argparse
import os
import sys
import time

from sentinel import __version__  # noqa: F401  (single source of truth below)


def cmd_version(_args) -> int:
    print("sentinel-trading 0.1.0")
    return 0


def cmd_doctor(_args) -> int:
    from adapters.freqtrade_adapter import FreqtradeClient

    ok = True
    print(f"python: {sys.version.split()[0]}")
    ta_dir = os.environ.get("SENTINEL_TA_DIR", os.path.expanduser("~/tradingagents"))
    ta_sh = os.path.join(ta_dir, "ta.sh")
    if os.path.exists(ta_sh):
        print(f"brain (TradingAgents): OK ({ta_sh})")
    else:
        print(f"brain (TradingAgents): not found at {ta_sh} (demo mode will simulate)")
    try:
        c = FreqtradeClient()
        bal = c.balance()
        print(f"freqtrade: OK ({c.base_url})")
    except Exception as e:
        print(f"freqtrade: not reachable ({e}) - deploy it first, see README")
    if os.path.exists(".env"):
        print("WARNING: .env found in repo dir - never commit it!")
        ok = False
    else:
        print("secrets: no .env in repo dir (good)")
    return 0 if ok else 1


def cmd_demo(_args) -> int:
    from sentinel.bus import SignalBus
    from sentinel.risk import UnifiedRiskManager
    from sentinel.validation import BacktestGate, BacktestReport
    from sentinel.orchestrator import Orchestrator
    from workers.arb_worker import ArbScanner, ArbConfig, InventoryTracker, OrderBook

    print("=== SENTINEL end-to-end demo (simulated) ===\n")
    bus, risk, gate = SignalBus(), UnifiedRiskManager(equity=10_000.0), BacktestGate()
    for name, alloc in [("breakout_atr", 50.0), ("grid", 30.0), ("arb", 20.0)]:
        risk.register(name, alloc)
    orch = Orchestrator(bus, risk, gate)

    events: list[str] = []
    bus.subscribe("signal", lambda m: events.append(
        f"signal -> {m['strategy']} on {m['ticker']} ({m['meta']['reason']})"))
    bus.subscribe("risk", lambda m: events.append(
        f"risk   -> {m['event']} scope={m.get('scope')} ({m.get('reason')})"))

    # 1. brain says bullish BTC, high vol - but no passport yet -> arb fallback
    bus.publish("regime", {"ticker": "BTC/USDT", "bias": "bullish",
                           "volatility": "high", "confidence": 0.8})
    # 2. backtest passes -> same regime now routes to breakout
    gate_rep = BacktestReport("breakout_atr", 120, 55.0, 1.8, 12.0, 34.0,
                              True, True, True)
    orch.register_passport(gate.evaluate(gate_rep))
    bus.publish("regime", {"ticker": "BTC/USDT", "bias": "bullish",
                           "volatility": "high", "confidence": 0.8})
    # 3. brain uncertain on ETH -> capital preservation (arb only)
    bus.publish("regime", {"ticker": "ETH/USDT", "bias": "uncertain",
                           "volatility": "high", "confidence": 0.3})
    # 4. risk: a bad day trips the kill switch
    print(f"equity 10000 -> {risk.update_equity(10_000)}")
    print(f"equity  9600 -> {risk.update_equity(9_600)}  (daily -4% < -3% limit)")
    bus.publish("risk", {"event": "kill", "scope": "global",
                         "reason": "daily loss limit"})
    ok, why = risk.can_open("breakout_atr", 100)
    print(f"can_open after kill: {ok} ({why})")
    # 5. arb worker finds a real (simulated) opportunity
    scanner = ArbScanner(ArbConfig(min_spread_bps=10))
    books = {
        "binance": OrderBook(bids=[(100.5, 2.0)], asks=[(100.0, 2.0)]),
        "kucoin": OrderBook(bids=[(101.5, 2.0)], asks=[(101.0, 2.0)]),
    }
    opp = scanner.scan(books)
    inv = InventoryTracker()
    if opp:
        inv.apply(opp)
        print(f"arb: buy {opp.buy_exchange} @ {opp.buy_price} -> "
              f"sell {opp.sell_exchange} @ {opp.sell_price} "
              f"= +${opp.net_profit_usd:.2f} net")
        print(f"rebalance needed on: {inv.needs_rebalance()}")

    print("\n--- event log ---")
    for e in events:
        print(e)
    print("\nactive profiles:", orch.active)
    print("\nDEMO COMPLETE: brain -> gate -> router -> risk -> workers all wired.")
    return 0


def cmd_run(args) -> int:
    """Paper-mode loop. Real orders are NEVER placed by this command."""
    import yaml

    cfg_path = args.config
    if not os.path.exists(cfg_path):
        print(f"config not found: {cfg_path} (copy config.example.yml first)")
        return 1
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)

    from sentinel.bus import SignalBus
    from sentinel.risk import UnifiedRiskManager
    from sentinel.validation import BacktestGate
    from sentinel.orchestrator import Orchestrator

    bus = SignalBus()
    rcfg = cfg.get("risk", {})
    risk = UnifiedRiskManager(
        equity=float(cfg.get("paper_equity", 10_000)),
        daily_loss_limit_pct=float(rcfg.get("daily_loss_limit_pct", 3.0)),
        daily_profit_target_pct=float(rcfg.get("daily_profit_target_pct", 2.0)),
        max_total_drawdown_pct=float(rcfg.get("max_total_drawdown_pct", 10.0)),
    )
    for name, alloc in cfg.get("allocations", {}).items():
        risk.register(name, float(alloc))
    gate = BacktestGate()
    orch = Orchestrator(bus, risk, gate)
    bus.subscribe("signal", lambda m: print(
        f"[{time.strftime('%H:%M:%S')}] route {m['ticker']} -> {m['strategy']} "
        f"({m['meta']['reason']})"))
    bus.subscribe("risk", lambda m: print(
        f"[{time.strftime('%H:%M:%S')}] RISK {m['event']}: {m.get('reason')}"))

    tickers = cfg.get("tickers", ["BTC/USDT"])
    interval = int(cfg.get("brain_interval_sec", 600))
    use_brain = os.path.exists(os.path.join(
        os.environ.get("SENTINEL_TA_DIR", os.path.expanduser("~/tradingagents")),
        "ta.sh"))
    print(f"paper loop started | tickers={tickers} | brain={'live' if use_brain else 'simulated'}")
    print("PAPER MODE: no real orders. Ctrl+C to stop.")
    try:
        n = 0
        while True:
            for t in tickers:
                if use_brain:
                    from adapters.tradingagents_adapter import analyze
                    msg = analyze(t)
                else:
                    msg = {"ticker": t, "bias": "uncertain", "confidence": 0.3,
                           "volatility": "low", "horizon": "swing"}
                bus.publish("regime", msg)
            n += 1
            if args.once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nstopped.")
    print(f"completed {n} cycle(s). active: {orch.active}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sentinel", description="Sentinel trading orchestration")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="full end-to-end simulation")
    sub.add_parser("doctor", help="check environment")
    rp = sub.add_parser("run", help="paper-mode orchestration loop")
    rp.add_argument("--config", default="config.yml")
    rp.add_argument("--once", action="store_true", help="single cycle then exit")
    sub.add_parser("version", help="show version")
    return p


def main() -> int:
    args = build_parser().parse_args()
    return {"demo": cmd_demo, "doctor": cmd_doctor,
            "run": cmd_run, "version": cmd_version}[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
