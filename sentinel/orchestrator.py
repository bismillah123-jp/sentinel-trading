"""Orchestrator - routes brain signals to the right execution worker.

Design (fleet, not monolith):
  TradingAgents (brain, slow)  -> regime/bias per ticker
  Orchestrator                 -> picks strategy profile for the regime
  Validation gate              -> strategy must hold a passing backtest passport
  Workers                      -> freqtrade adapter (tactical) / arb_worker (neutral)

Regime -> profile map (from research):
  bullish + high vol     -> breakout_atr (MBT-style momentum)
  sideways / low vol     -> grid (range harvesting)
  bearish                -> short breakout / stay in arb only
  uncertain / choppy     -> market-neutral arbitrage only, directional disabled
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .bus import SignalBus
from .risk import UnifiedRiskManager
from .validation import BacktestGate, StrategyPassport


@dataclass
class StrategyProfile:
    name: str
    worker: str            # "freqtrade" | "arb"
    long_only: bool = False
    short_allowed: bool = False


PROFILES: dict[str, StrategyProfile] = {
    "breakout_atr": StrategyProfile("breakout_atr", "freqtrade",
                                    short_allowed=True),
    "grid": StrategyProfile("grid", "freqtrade", long_only=True),
    "arb": StrategyProfile("arb", "arb"),
}


def regime_to_profile(bias: str, volatility: str) -> str:
    if bias == "uncertain":
        return "arb"                      # capital preservation mode
    if volatility == "high" and bias in ("bullish", "bearish"):
        return "breakout_atr"
    if volatility == "low":
        return "grid"
    return "arb"


@dataclass
class Orchestrator:
    bus: SignalBus
    risk: UnifiedRiskManager
    gate: BacktestGate
    active: dict[str, str] = field(default_factory=dict)  # ticker -> profile

    def __post_init__(self) -> None:
        self.bus.subscribe("regime", self.on_regime)
        self.bus.subscribe("risk", self.on_risk)

    # -- event handlers --------------------------------------------------
    def on_regime(self, msg: dict) -> None:
        ticker = msg["ticker"]
        profile_name = regime_to_profile(msg.get("bias", "uncertain"),
                                         msg.get("volatility", "low"))
        passport = self.gate.passport_for(profile_name)
        if passport is None or not passport.passed:
            # No proven strategy for this regime -> fall back to arb / flat.
            self.set_profile(ticker, "arb", reason="no passing passport")
            return
        # Scale size by brain confidence (regime-aware sizing).
        conf = float(msg.get("confidence", 0.5))
        self.bus.publish("risk", {"event": "resize", "scope": profile_name,
                                  "reason": f"brain confidence {conf:.2f}",
                                  "confidence": conf})
        self.set_profile(ticker, profile_name,
                         reason=f"bias={msg.get('bias')} vol={msg.get('volatility')}")

    def on_risk(self, msg: dict) -> None:
        if msg.get("event") == "kill":
            for strat in list(self.risk.budgets):
                self.risk.set_enabled(strat, False)

    def set_profile(self, ticker: str, profile: str, reason: str = "") -> None:
        self.active[ticker] = profile
        self.bus.publish("signal", {"strategy": profile, "ticker": ticker,
                                    "side": "flat", "strength": 0.0,
                                    "meta": {"action": "activate",
                                             "reason": reason}})

    def register_passport(self, passport: StrategyPassport) -> None:
        self.gate.register(passport)
