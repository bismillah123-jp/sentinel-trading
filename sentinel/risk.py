"""Unified risk manager - the layer that actually protects capital.

Ideas folded in from research:
  - Volatility targeting (Jeff Riley's bot): risk budget per position scales
    with realized volatility instead of fixed size.
  - Daily circuit breaker (82-bot CME experiment): hit +target or -limit,
    everything stops for the day.
  - Regime-aware sizing: when the brain says "choppy/uncertain", budgets shrink.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class StrategyBudget:
    name: str
    allocation_pct: float          # % of total equity assigned
    max_position_pct: float = 5.0  # max single position as % of equity
    enabled: bool = True


@dataclass
class UnifiedRiskManager:
    equity: float
    peak_equity: float = 0.0
    day_start_equity: float = 0.0
    daily_loss_limit_pct: float = 3.0   # kill all if day PnL < -3%
    daily_profit_target_pct: float = 2.0  # lock in, stop entries if > +2%
    max_total_drawdown_pct: float = 10.0
    killed: bool = False
    budgets: dict[str, StrategyBudget] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.peak_equity = self.equity
        self.day_start_equity = self.equity

    # -- registration ----------------------------------------------------
    def register(self, name: str, allocation_pct: float,
                 max_position_pct: float = 5.0) -> None:
        self.budgets[name] = StrategyBudget(name, allocation_pct,
                                            max_position_pct)

    # -- global guards ---------------------------------------------------
    def update_equity(self, equity: float) -> str:
        """Returns 'ok' | 'kill' | 'lock_profit'. Call on every equity tick."""
        self.equity = equity
        self.peak_equity = max(self.peak_equity, equity)
        day_pnl_pct = (equity - self.day_start_equity) / self.day_start_equity * 100
        dd_pct = (self.peak_equity - equity) / self.peak_equity * 100

        if dd_pct >= self.max_total_drawdown_pct:
            self.killed = True
            return "kill"
        if day_pnl_pct <= -self.daily_loss_limit_pct:
            self.killed = True
            return "kill"
        if day_pnl_pct >= self.daily_profit_target_pct:
            return "lock_profit"
        return "ok"

    def new_day(self) -> None:
        self.day_start_equity = self.equity
        self.killed = False

    # -- sizing ----------------------------------------------------------
    @staticmethod
    def position_size(equity: float, atr: float, risk_pct: float = 1.0,
                      atr_mult: float = 2.0) -> float:
        """Volatility-targeted notional.

        Risk `risk_pct`% of equity per (atr_mult * ATR) adverse move.
        Wider volatility -> smaller size, automatically.
        """
        if atr <= 0:
            return 0.0
        risk_amount = equity * risk_pct / 100.0
        return risk_amount / (atr * atr_mult)

    def can_open(self, strategy: str, notional: float,
                 regime_confidence: float = 1.0) -> tuple[bool, str]:
        """Gate every order through here."""
        if self.killed:
            return False, "global kill-switch active"
        b = self.budgets.get(strategy)
        if b is None:
            return False, f"unknown strategy '{strategy}'"
        if not b.enabled:
            return False, f"strategy '{strategy}' disabled"
        cap = self.equity * b.max_position_pct / 100.0 * regime_confidence
        if notional > cap:
            return False, (f"notional {notional:.2f} > cap {cap:.2f} "
                           f"(strat={strategy})")
        return True, "ok"

    def set_enabled(self, strategy: str, enabled: bool) -> None:
        if strategy in self.budgets:
            self.budgets[strategy].enabled = enabled
