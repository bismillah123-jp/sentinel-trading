"""Validation gate - Jesse-inspired: no strategy trades live without a passport.

A passport is earned by a backtest that is:
  - statistically meaningful (min trades)
  - profitable after fees (profit factor, not just win rate)
  - bounded in pain (max drawdown)
  - honest about the future (out-of-sample slice, no look-ahead flag)

Win rate alone never passes the gate: a 90% win-rate strategy that blows up
on the 10% is worse than a 40% one with asymmetric payoffs.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class BacktestReport:
    strategy: str
    trades: int
    win_rate_pct: float
    profit_factor: float      # gross profit / gross loss
    max_drawdown_pct: float
    total_return_pct: float
    out_of_sample: bool       # tested on data the strategy never saw in tuning
    lookahead_clean: bool     # passed lookahead-bias analysis
    fees_included: bool = True


@dataclass
class StrategyPassport:
    strategy: str
    passed: bool
    report: BacktestReport
    notes: str = ""


@dataclass
class GateThresholds:
    min_trades: int = 30
    min_profit_factor: float = 1.2
    max_drawdown_pct: float = 25.0
    min_return_pct: float = 0.0


class BacktestGate:
    def __init__(self, thresholds: GateThresholds | None = None) -> None:
        self.thresholds = thresholds or GateThresholds()
        self._passports: dict[str, StrategyPassport] = {}

    def evaluate(self, report: BacktestReport) -> StrategyPassport:
        t = self.thresholds
        reasons: list[str] = []
        if report.trades < t.min_trades:
            reasons.append(f"only {report.trades} trades (< {t.min_trades})")
        if report.profit_factor < t.min_profit_factor:
            reasons.append(f"profit factor {report.profit_factor:.2f} "
                           f"(< {t.min_profit_factor})")
        if report.max_drawdown_pct > t.max_drawdown_pct:
            reasons.append(f"drawdown {report.max_drawdown_pct:.1f}% "
                           f"(> {t.max_drawdown_pct}%)")
        if report.total_return_pct < t.min_return_pct:
            reasons.append("negative total return")
        if not report.out_of_sample:
            reasons.append("no out-of-sample test (likely overfit)")
        if not report.lookahead_clean:
            reasons.append("look-ahead bias not cleared")
        if not report.fees_included:
            reasons.append("fees not included (fantasy numbers)")
        passed = not reasons
        passport = StrategyPassport(
            strategy=report.strategy, passed=passed, report=report,
            notes="; ".join(reasons) if reasons else "all checks passed")
        self._passports[report.strategy] = passport
        return passport

    def register(self, passport: StrategyPassport) -> None:
        self._passports[passport.strategy] = passport

    def passport_for(self, strategy: str) -> StrategyPassport | None:
        return self._passports.get(strategy)
